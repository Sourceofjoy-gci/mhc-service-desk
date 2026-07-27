"""OIDC JWT authentication for the MHC e-Ticketing backend.

Tokens issued by Keycloak are verified against the realm's JWKS. The
``sub`` claim is the source of truth for identity; the ``groups`` and
``realm_access.roles`` claims drive authorisation.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework import authentication, exceptions
from rest_framework_simplejwt.tokens import AccessToken

from .models import User

logger = logging.getLogger(__name__)

_JWKS_CACHE_KEY = "keycloak_jwks"
_JWKS_TTL = 3600


def _get_jwks() -> dict[str, Any]:
    cached = cache.get(_JWKS_CACHE_KEY)
    if cached:
        return cached
    url = settings.KEYCLOAK["VERIFICATION_KEYS_URL"]
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    data = r.json()
    cache.set(_JWKS_CACHE_KEY, data, timeout=_JWKS_TTL)
    return data


def _select_key(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


class KeycloakJWTAuthentication(authentication.BaseAuthentication):
    """Validates a Bearer access token issued by the Keycloak realm.

    In DEBUG mode, also accepts a dev token of the form ``dev:<username>:<groups>``
    so local development does not require a full OIDC round-trip. This fallback
    is automatically disabled when DEBUG is False.
    """

    keyword = "Bearer"

    def authenticate(self, request):
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
                user, _ = User.objects.get_or_create(
                    username=username,
                    defaults={"keycloak_subject": f"dev:{username}"},
                )
                groups = _normalize_groups(groups)
                _synchronize_groups(user, groups)
                return user, {"sub": f"dev:{username}", "groups": groups}
        # --------------------------------------------------------------------

        try:
            AccessToken(token, verify=False)
        except Exception as exc:
            raise exceptions.AuthenticationFailed(f"Malformed token: {exc}") from exc

        unverified_header = _decode_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
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
            payload = _verify_jwt(token, public_key, audience=settings.KEYCLOAK["AUDIENCE"])
        except Exception as exc:
            raise exceptions.AuthenticationFailed(f"Token verification failed: {exc}") from exc

        sub = payload.get("sub")
        if not sub:
            raise exceptions.AuthenticationFailed("Token missing sub")

        preferred_username = payload.get("preferred_username", sub)[:150]
        email = payload.get("email", "")
        mfa_enabled = bool(payload.get("acr") in ("mfa", "urn:mace:incommon:iap:silver"))

        # Look up by keycloak_subject first (the stable link to the IdP).
        user = User.objects.filter(keycloak_subject=sub).first()
        if user is None:
            # Fallback: a stale user with the same username (e.g. the IdP was
            # re-bootstrapped and minted a new sub). Re-link them.
            user = User.objects.filter(username=preferred_username).first()
            if user is not None:
                user.keycloak_subject = sub
                user.email = email or user.email
                user.mfa_enabled = mfa_enabled
                user.save(update_fields=["keycloak_subject", "email", "mfa_enabled"])
        if user is None:
            # Brand-new IdP user — create the local mirror.
            user = User.objects.create(
                keycloak_subject=sub,
                username=preferred_username,
                email=email,
                mfa_enabled=mfa_enabled,
            )
        elif email and email != user.email:
            user.email = email
            user.save(update_fields=["email"])
        # Persist the IdP snapshot and retain a request-local copy for scope
        # calculation so one request cannot observe an in-flight refresh.
        groups = _normalize_groups(payload.get("groups"))
        _synchronize_groups(user, groups)
        return user, payload

    def authenticate_header(self, request):
        return f'{self.keyword} realm="{settings.KEYCLOAK["REALM"]}"'


# --- helpers ----------------------------------------------------------------

def _normalize_groups(raw_groups: object) -> list[str]:
    if not isinstance(raw_groups, list | tuple):
        return []
    return [str(group) for group in raw_groups if group is not None]


def _synchronize_groups(user: User, groups: list[str]) -> None:
    if user.keycloak_groups != groups:
        user.keycloak_groups = groups
        user.save(update_fields=["keycloak_groups"])
    user._groups = list(groups)

def _decode_unverified_header(token: str) -> dict[str, Any]:
    import jwt
    return jwt.get_unverified_header(token)


def _build_public_key(jwk: dict[str, Any]):
    from jwt.algorithms import RSAAlgorithm
    return RSAAlgorithm.from_jwk(jwk)


def _verify_jwt(token: str, public_key, audience: str) -> dict[str, Any]:
    import jwt
    return jwt.decode(
        token,
        key=public_key,
        algorithms=["RS256"],
        audience=audience,
        options={"verify_aud": True, "verify_iat": True, "verify_exp": True},
    )
