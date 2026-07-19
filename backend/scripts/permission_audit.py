"""Permission audit — list every scope/auth annotation in the codebase.

Run from the backend directory:

    docker compose exec -T -w /app backend python scripts/permission_audit.py

Helps reviewers verify that the matrix in `docs/permission-matrix.md`
matches the actual code. Drift should be caught in PR review.
"""
from __future__ import annotations

import os
import sys

# Ensure /app is on sys.path so `config.urls` is importable inside the
# container (where the CWD is /app but sys.path is not set automatically
# when running a script via `docker compose exec`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django
django.setup()

import inspect

from rest_framework.views import APIView
from django.urls import get_resolver


def _walk_views():
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
    found = 0
    for path, cls in sorted(_walk_views()):
        perms = ", ".join(p.__name__ for p in getattr(cls, "permission_classes", []))
        scope = getattr(cls, "required_scope", None)
        is_public = getattr(cls, "_public", False)
        suffix = "PUBLIC" if is_public else (str(scope) if scope else "any auth")
        print(f"{path:<55} {perms:<35} {suffix}")
        found += 1
    # The @api_view-decorated function-based views do not show up in
    # the class-based resolver walk. Print a one-liner summary of the
    # views that were introspected.
    print(f"\nintrospected {found} class-based views (function-based views "
          f"are listed in docs/permission-matrix.md manually)")


if __name__ == "__main__":
    main()
