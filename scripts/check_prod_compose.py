"""Validate production Compose wiring that Docker cannot infer from syntax alone."""

from pathlib import Path


def main() -> None:
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.prod.yml"
    compose = compose_path.read_text(encoding="utf-8")

    expected = "KC_DB_PASSWORD: ${POSTGRES_PASSWORD}"
    if expected not in compose or "KCRAW_DB_PASSWORD" in compose:
        raise SystemExit(
            "production compose must pass POSTGRES_PASSWORD to Keycloak as "
            "KC_DB_PASSWORD"
        )

    print("production compose Keycloak database password wiring passed")


if __name__ == "__main__":
    main()
