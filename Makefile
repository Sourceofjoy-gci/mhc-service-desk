.PHONY: help up down logs build ps restart migrate seed backup restore test lint type fmt clean keycloak-export

help:
	@echo "MHC e-Ticketing — make targets"
	@echo "  up            Start full stack"
	@echo "  down          Stop stack"
	@echo "  logs          Tail logs"
	@echo "  build         Rebuild images"
	@echo "  ps            Show running services"
	@echo "  restart       Restart a service (e.g. make restart svc=backend)"
	@echo "  migrate       Run Django migrations"
	@echo "  seed          Load seed data"
	@echo "  backup        Snapshot DB + object store"
	@echo "  restore       Restore latest backup (CONFIRM=1 required)"
	@echo "  test          Run backend + frontend tests"
	@echo "  lint          Run ruff + eslint"
	@echo "  type          Run mypy + tsc"
	@echo "  fmt           Auto-format"
	@echo "  keycloak-export  Export current realm to infrastructure/keycloak/realm-export.json"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

build:
	docker compose build

ps:
	docker compose ps

restart:
	docker compose restart $(svc)

migrate:
	docker compose exec backend python manage.py migrate

seed:
	docker compose exec backend python manage.py loaddata seed/initial.json

backup:
	bash scripts/backup.sh

restore:
	@if [ "$(CONFIRM)" != "1" ]; then echo "Refusing to restore without CONFIRM=1"; exit 2; fi
	bash scripts/restore.sh

test:
	docker compose exec backend pytest
	docker compose exec frontend npm test --silent

lint:
	docker compose exec backend ruff check .
	docker compose exec frontend npm run lint

type:
	docker compose exec backend mypy backend
	docker compose exec frontend npm run typecheck

fmt:
	docker compose exec backend ruff format .
	docker compose exec frontend npm run format

keycloak-export:
	docker compose exec keycloak /opt/keycloak/bin/kc.sh export --realm mhc --file /tmp/realm.json
	docker cp $$(docker compose ps -q keycloak):/tmp/realm.json infrastructure/keycloak/realm-export.json

clean:
	docker compose down -v
