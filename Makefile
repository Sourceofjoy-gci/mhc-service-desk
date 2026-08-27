.PHONY: help up watch down logs build ps restart migrate seed backup restore test lint type verify pilot-smoke fmt clean keycloak-export

define run_frontend
docker compose run --rm --no-deps --build --volume /app/node_modules frontend $(1)
endef

help:
	@echo "MHC e-Ticketing — make targets"
	@echo "  up            Start full stack"
	@echo "  watch         Start full stack with frontend live-reload (use while editing UI)"
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
	@echo "  verify        Run the complete backend + frontend quality gate"
	@echo "  pilot-smoke   Exercise the pilot workflow against development data"
	@echo "  fmt           Auto-format"
	@echo "  keycloak-export  Export current realm to infrastructure/keycloak/realm-export.json"

up:
	docker compose up -d

# Frontend edits are copied into the container as you save them. The container
# has no source bind mount, so plain `up` serves whatever the image was built
# with — use this target while working on the UI.
watch:
	docker compose up -d
	docker compose watch frontend

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
	docker compose exec backend pytest -q
	$(call run_frontend,env VITE_API_BASE_URL= npm test -- --run)

lint:
	docker compose exec backend ruff check .
	$(call run_frontend,npm run lint)

type:
	docker compose exec backend mypy apps config
	$(call run_frontend,npm run typecheck)

pilot-smoke:
	docker compose exec backend python /app/scripts/pilot_foundation_smoke.py

verify:
	docker compose run --rm --no-deps --volume .:/workspace:ro backend python /workspace/scripts/check_prod_compose.py
	docker compose exec backend python manage.py makemigrations --check --dry-run
	docker compose exec backend pytest -q
	docker compose exec backend ruff check .
	$(call run_frontend,env VITE_API_BASE_URL= npm test -- --run)
	$(call run_frontend,npm run typecheck)
	$(call run_frontend,npm run lint)
	$(call run_frontend,npm run build)

fmt:
	docker compose exec backend ruff format .
	docker compose exec frontend npm run format

keycloak-export:
	docker compose exec keycloak /opt/keycloak/bin/kc.sh export --realm mhc --file /tmp/realm.json
	docker cp $$(docker compose ps -q keycloak):/tmp/realm.json infrastructure/keycloak/realm-export.json

clean:
	docker compose down -v
