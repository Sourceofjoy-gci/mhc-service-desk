"""OIDC JWT authentication for the MHC e-Ticketing backend.

Tokens issued by Keycloak are verified against the realm's JWKS. The
``sub`` claim is the source of truth for identity; the ``groups`` and
``realm_access.roles`` claims drive authorisation.
"""

from __future__ import annotations

import json
import logging
from typing import TypeGuard

import requests
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework import authentication, exceptions
from rest_framework.request import Request
from rest_framework_simplejwt.tokens import AccessToken

from .authority_lock import lock_user_authorities
from .models import User

logger = logging.getLogger(__name__)

_JWKS_CACHE_KEY = "keycloak_jwks"
_JWKS_TTL = 3600

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]


def _is_json_value(value: object) -> TypeGuard[JSONValue]:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _is_json_object(value: object) -> TypeGuard[JSONObject]:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_json_value(item) for key, item in value.items()
    )


def _require_json_object(value: object, *, source: str) -> JSONObject:
    if not _is_json_object(value):
        raise TypeError(f"{source} must be a JSON object")
    return value


def _get_jwks() -> JSONObject:
    cached: object = cache.get(_JWKS_CACHE_KEY)
    if cached:
        return _require_json_object(cached, source="Cached JWKS")
    url: object = settings.KEYCLOAK["VERIFICATION_KEYS_URL"]
    if not isinstance(url, str):
        raise TypeError("KEYCLOAK verification URL must be a string")
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    data = _require_json_object(r.json(), source="JWKS response")
    cache.set(_JWKS_CACHE_KEY, data, timeout=_JWKS_TTL)
    return data


def _select_key(jwks: JSONObject, kid: str) -> JSONObject | None:
    keys = jwks.get("keys", [])
    if not isinstance(keys, list):
        return None
    for key in keys:
        if _is_json_object(key) and key.get("kid") == kid:
            return key
    return None


class KeycloakJWTAuthentication(authentication.BaseAuthentication):
    """Validates a Bearer access token issued by the Keycloak realm.

    In DEBUG mode, also accepts a dev token of the form ``dev:<username>:<groups>``
    so local development does not require a full OIDC round-trip. This fallback
    is automatically disabled when DEBUG is False.
    """

    keyword = "Bearer"

    def authenticate(self, request: Request) -> tuple[User, JSONObject] | None:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(f"{self.keyword} "):
            return None
        token = header.split(" ", 1)[1].strip()

        # --- Dev fallback (DEBUG only) -------------------------------------
        if settings.DEBUG and token.startswith("dev:"):
            parts = token.split(":")
            if len(parts) >= 2:
                username = parts[1]
                groups = parts[2].split(",") if len(parts) > 2 and parts[2] else []
                dev_user = _resolve_local_user(
                    keycloak_subject=f"dev:{username}",
                    preferred_username=username,
                    email="",
                    mfa_enabled=False,
                )
                groups = _normalize_groups(groups)
                _synchronize_groups(dev_user, groups)
                group_claims: list[JSONValue] = list(groups)
                return dev_user, {
                    "sub": f"dev:{username}",
                    "groups": group_claims,
                }
        # --------------------------------------------------------------------

        try:
            AccessToken(token, verify=False)
        except Exception as exc:
            raise exceptions.AuthenticationFailed(f"Malformed token: {exc}") from exc

        unverified_header = _decode_unverified_header(token)
        kid = unverified_header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise exceptions.AuthenticationFailed("Token missing kid header")

        jwks = _get_jwks()
        key = _select_key(jwks, kid)
        if not key:
            # JWKS rotation — drop cache and retry once
            cache.delete(_JWKS_CACHE_KEY)
            jwks = _get_jwks()
            key = _select_key(jwks, kid)
        if not key:
            raise exceptions.AuthenticationFailed("Unknown signing key")

        try:
            public_key = _build_public_key(key)
        except Exception as exc:  # pragma: no cover - defensive
            raise exceptions.AuthenticationFailed(f"Invalid signing key: {exc}") from exc

        try:
            audience: object = settings.KEYCLOAK["AUDIENCE"]
            if not isinstance(audience, str):
                raise TypeError("KEYCLOAK audience must be a string")
            payload = _verify_jwt(token, public_key, audience=audience)
        except Exception as exc:
            raise exceptions.AuthenticationFailed(f"Token verification failed: {exc}") from exc

        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise exceptions.AuthenticationFailed("Token missing sub")

        raw_username = payload.get("preferred_username", sub)
        preferred_username = raw_username[:150] if isinstance(raw_username, str) else sub[:150]
        raw_email = payload.get("email", "")
        email = raw_email if isinstance(raw_email, str) else ""
        mfa_enabled = bool(payload.get("acr") in ("mfa", "urn:mace:incommon:iap:silver"))

        # Look up by keycloak_subject first (the stable link to the IdP).
        user = _resolve_local_user(
            keycloak_subject=sub,
            preferred_username=preferred_username,
            email=email,
            mfa_enabled=mfa_enabled,
        )
        if email and email != user.email:
            user.email = email
            user.save(update_fields=["email"])
        # Persist the IdP snapshot and retain a request-local copy for scope
        # calculation so one request cannot observe an in-flight refresh.
        groups = _normalize_groups(payload.get("groups"))
        _synchronize_groups(user, groups)
        return user, payload

    def authenticate_header(self, request: Request) -> str:
        return f'{self.keyword} realm="{settings.KEYCLOAK["REALM"]}"'


# --- helpers ----------------------------------------------------------------


def _resolve_local_user(
    *,
    keycloak_subject: str,
    preferred_username: str,
    email: str,
    mfa_enabled: bool,
) -> User:
    user = User.objects.filter(keycloak_subject=keycloak_subject).first()
    if user is None:
        if User.objects.filter(username=preferred_username).exists():
            raise exceptions.AuthenticationFailed(
                "Local identity requires explicit reconciliation."
            )
        try:
            with transaction.atomic():
                user = User.objects.create(
                    keycloak_subject=keycloak_subject,
                    username=preferred_username,
                    email=email,
                    mfa_enabled=mfa_enabled,
                )
        except IntegrityError as exc:
            raise exceptions.AuthenticationFailed(
                "Local identity requires explicit reconciliation."
            ) from exc
    if not user.is_active:
        raise exceptions.AuthenticationFailed("User account is disabled.")
    return user


def _normalize_groups(raw_groups: object) -> list[str]:
    if not isinstance(raw_groups, list | tuple):
        return []
    return [str(group) for group in raw_groups if group is not None]


def _synchronize_groups(user: User, groups: list[str]) -> None:
    with transaction.atomic():
        locked = lock_user_authorities((user.id,))[user.id].user
        if locked.keycloak_groups != groups:
            locked.keycloak_groups = groups
            locked.save(update_fields=["keycloak_groups"])
        user.keycloak_groups = list(locked.keycloak_groups)
    vars(user)["_groups"] = list(groups)


def _decode_unverified_header(token: str) -> JSONObject:
    import jwt

    return _require_json_object(
        jwt.get_unverified_header(token),
        source="JWT header",
    )


def _build_public_key(jwk: JSONObject) -> RSAPublicKey:
    from jwt.algorithms import RSAAlgorithm

    public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
    if not isinstance(public_key, RSAPublicKey):
        raise TypeError("JWK must contain an RSA public key")
    return public_key


def _verify_jwt(
    token: str,
    public_key: RSAPublicKey,
    audience: str,
) -> JSONObject:
    import jwt

    return _require_json_object(
        jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=audience,
            options={"verify_aud": True, "verify_iat": True, "verify_exp": True},
        ),
        source="JWT payload",
    )
