"""Permission audit — list every scope/auth annotation in the codebase.

Run from the backend directory:

    docker compose exec -T backend python /app/scripts/permission_audit.py

Helps reviewers verify that this matrix in `docs/permission-matrix.md`
matches the actual code. Drift should be caught in PR review.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import config.urls  # noqa: F401  (forces URL setup)


def _walk_views():
    from rest_framework.views import APIView
    from django.urls import get_resolver
    resolver = get_resolver()
    for prefix, viewset_or_callable in resolver.reverse_dict.items():
        if not isinstance(prefix, str):
            continue
        if not prefix.startswith("api/v1/"):
            continue
        cls = getattr(viewset_or_callable, "cls", None)
        if cls is None:
            continue
        if not (inspect.isclass(cls) and issubclass(cls, APIView)):
            continue
        yield prefix, cls


def main():
    print(f"{'PATH':<55} {'PERMISSION_CLASSES':<35} SCOPE / PUBLIC")
    print("-" * 110)
    for path, cls in sorted(_walk_views()):
        perms = ", ".join(p.__name__ for p in getattr(cls, "permission_classes", []))
        scope = getattr(cls, "required_scope", None)
        is_public = getattr(cls, "_public", False)
        suffix = "PUBLIC" if is_public else (str(scope) if scope else "any auth")
        print(f"{path:<55} {perms:<35} {suffix}")


if __name__ == "__main__":
    main()
