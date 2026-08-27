"""Permission audit — list every scope/auth annotation in the codebase.

Run from the backend directory:

    docker compose exec -T -w /app backend python scripts/permission_audit.py

Helps reviewers verify that the matrix in `docs/permission-matrix.md`
matches the actual code. Drift should be caught in PR review.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from dataclasses import dataclass
from itertools import groupby

# Ensure /app is on sys.path so `config.urls` is importable inside the
# container (where the CWD is /app but sys.path is not set automatically
# when running a script via `docker compose exec`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: I001

django.setup()

# These imports consume configured Django/DRF settings and must follow setup.
from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402
from rest_framework.permissions import AllowAny  # noqa: E402, I001
from rest_framework.views import APIView  # noqa: E402


@dataclass(frozen=True)
class AuditedRoute:
    path: str
    method: str
    action: str
    authentication_classes: tuple[str, ...]
    permission_classes: tuple[str, ...]
    required_scope: str | None
    is_public: bool


REQUIRED_ROUTE_FAMILIES = {
    "lifecycle": (
        ("PATCH", "work_state", "api/v1/tickets/<number>/work-state/"),
        ("GET", "assignees", "api/v1/tickets/<number>/assignees/"),
        ("POST", "transition", "api/v1/tickets/<number>/transition/"),
        ("GET", "activity", "api/v1/tickets/<number>/activity/"),
    ),
    "attachment": (
        ("GET", "ticket-attachments", "api/v1/tickets/<ticket_number>/attachments/"),
        ("POST", "ticket-attachments", "api/v1/tickets/<ticket_number>/attachments/"),
        ("GET", "attachment-download", "api/v1/attachments/<attachment_id>/download/"),
    ),
    "reporting": (
        ("GET", "export-tickets-csv", "api/v1/reports/tickets.csv"),
        ("GET", "dashboard-operational", "api/v1/reports/dashboard/operational"),
        ("GET", "dashboard-it", "api/v1/reports/dashboard/it"),
        ("GET", "flow-metrics", "api/v1/reports/flow"),
    ),
}


def _normalise_path(path: str) -> str:
    path = path.replace("^", "").replace("$", "").replace("\\Z", "")
    path = re.sub(r"\(\?P<([^>]+)>[^)]+\)", r"<\1>", path)
    path = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"<\1>", path)
    return path.replace("\\.", ".").replace("/?", "/")


def _class_names(classes) -> tuple[str, ...]:
    return tuple(item.__name__ for item in classes)


def _route_methods(callback, cls, pattern_name):
    actions = getattr(callback, "actions", None)
    if actions:
        yield from sorted((method.upper(), action) for method, action in actions.items())
        return

    for method in cls.http_method_names:
        if method == "options" or not hasattr(cls, method):
            continue
        yield method.upper(), pattern_name or method


def _walk_patterns(patterns, prefix=""):
    for pattern in patterns:
        full_path = f"{prefix}{pattern.pattern}"
        if isinstance(pattern, URLResolver):
            yield from _walk_patterns(pattern.url_patterns, full_path)
            continue
        if not isinstance(pattern, URLPattern):
            continue

        callback = pattern.callback
        cls = getattr(callback, "cls", None)
        if not (inspect.isclass(cls) and issubclass(cls, APIView)):
            continue

        path = _normalise_path(full_path)
        if not path.startswith("api/v1/") or "<format>" in path:
            continue
        initkwargs = getattr(callback, "initkwargs", {})
        permissions = tuple(initkwargs.get("permission_classes", cls.permission_classes))
        authentication = initkwargs.get(
            "authentication_classes",
            cls.authentication_classes,
        )
        required_scope = initkwargs.get(
            "required_scope",
            getattr(cls, "required_scope", None),
        )
        is_public = bool(
            getattr(callback, "_public", False)
            or getattr(cls, "_public", False)
            or any(issubclass(permission, AllowAny) for permission in permissions)
        )
        for method, action in _route_methods(callback, cls, pattern.name):
            yield AuditedRoute(
                path=path,
                method=method,
                action=action,
                authentication_classes=_class_names(authentication),
                permission_classes=_class_names(permissions),
                required_scope=str(required_scope) if required_scope else None,
                is_public=is_public,
            )


def _walk_views():
    yield from _walk_patterns(get_resolver().url_patterns)


def _missing_required_routes(routes):
    observed = {(route.method, route.action, route.path) for route in routes}
    return {
        family: [required for required in requirements if required not in observed]
        for family, requirements in REQUIRED_ROUTE_FAMILIES.items()
        if any(required not in observed for required in requirements)
    }


def _route_sort_key(route):
    return (
        route.path,
        route.method,
        route.action,
        route.authentication_classes,
        route.permission_classes,
        route.required_scope or "",
        route.is_public,
    )


def _route_identity(route):
    return route.path, route.method, route.action


def _deduplicate_routes(routes):
    deduplicated = []
    conflicts = []
    unique_routes = sorted(set(routes), key=_route_sort_key)
    for identity, grouped_routes in groupby(unique_routes, key=_route_identity):
        candidates = tuple(grouped_routes)
        deduplicated.append(candidates[0])
        if len(candidates) > 1:
            conflicts.append((identity, candidates))
    return deduplicated, conflicts


def _metadata_label(route):
    authentication = ", ".join(route.authentication_classes) or "none"
    permissions = ", ".join(route.permission_classes) or "none"
    access = "PUBLIC" if route.is_public else (route.required_scope or "any auth")
    return f"AUTH={authentication} | PERMISSIONS={permissions} | ACCESS={access}"


def main():
    routes, conflicts = _deduplicate_routes(_walk_views())
    print("METHOD ACTION PATH | AUTHENTICATION | PERMISSIONS | SCOPE / PUBLIC")
    print("-" * 120)
    for route in routes:
        print(f"{route.method} {route.action} {route.path} " f"| {_metadata_label(route)}")

    if not routes:
        print("\nERROR: no API views found")
        return 1

    if conflicts:
        for (path, method, action), candidates in conflicts:
            print(f"\nERROR: conflicting metadata for {method} {action} {path}")
            for candidate in candidates:
                print(f"  {_metadata_label(candidate)}")
        return 1

    missing = _missing_required_routes(routes)
    if missing:
        for family, requirements in missing.items():
            print(f"\nERROR: missing required {family} routes")
            for method, action, path in requirements:
                print(f"  {method} {path} (action={action})")
        return 1

    path_count = len({route.path for route in routes})
    print(f"\naudit passed: {len(routes)} route actions across {path_count} API paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
