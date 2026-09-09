.PHONY: help dev-build dev-up dev-up-full dev-down dev-restart dev-logs dev-ps dev-health dev-rebuild \
	prod-build prod-pull prod-migrate prod-up prod-down prod-logs prod-scale prod-small prod-medium prod-large migrate test clean \
	build up down restart logs ps health build-prod up-prod down-prod logs-prod \
	app-logs identity-logs parser-logs frontend-logs discord-logs balancer-logs stream-logs \
	app-restart identity-restart parser-restart frontend-restart \
	monitoring-up monitoring-down monitoring-logs monitoring-ps \
	backup-up backup-down backup-logs backup-setup backup-run backup-ls \
	app-rebuild identity-rebuild parser-rebuild frontend-rebuild \
	loadtest loadtest-ui

COMPOSE = docker compose
PROD_COMPOSE = docker compose -f docker-compose.production.yml
# Log storage (loki+promtail) and traces (tempo+otel-collector) are compose
# profiles: metrics run everywhere, those two only where there is RAM to spare.
#   make monitoring-up MONITORING_PROFILES="logs traces"
MONITORING_PROFILES ?=
MONITORING_COMPOSE = docker compose -f docker-compose.monitoring.yml $(foreach p,$(MONITORING_PROFILES),--profile $(p))
# Контур бэкапов: свой проект (owt-backup) и свой env-файл, чтобы жизненный цикл
# не зависел от прода. См. docs/backup-rustfs.md.
BACKUP_ENV = ops/backup/backup.env
BACKUP_COMPOSE = docker compose -f docker-compose.backup.yml --env-file $(BACKUP_ENV)

# Workers safe to replicate: RabbitMQ competing-consumers spread RPC calls + jobs
# across replicas automatically, cache lives in shared Redis, DB access goes via
# pgBouncer. balancer-svc is safe too (its draft clock is guarded by a per-draft
# Redis lock — shared/services/distributed_lock.py — so only one replica drives
# each live draft); kept out of every size because each replica can eat ~4 CPU.
# Do NOT scale analytics-worker: it starts an APScheduler on every replica
# (scheduled jobs would multi-fire) and its jobs aren't idempotent — it needs
# leader-election first.
#
# Sizes, calibrated by measured CPU per request (one faststream process = one
# event loop = 1 core ceiling, ~0.85 usable): tournament ~46 ms/req on its
# hottest uncacheable route (registration/form) = ~18 rps per replica, app-svc
# ~20 ms on live routes plus ~107 ms per response-cache miss on user profiles,
# identity ~6-12 ms and bounded by SESSIONS, not rps (the gateway caches each
# validate_token verdict for 30s). small = this 4 CPU / 8G box, large needs 8.
# `make prod-up` / `make prod-scale` / GitHub release all honour PROD_SIZE so a
# plain `docker compose up -d` cannot silently restore leftover replica counts.
# Override a size on the CLI, e.g. make prod-up PROD_SIZE=medium
# or poke one service: make prod-up PROD_SCALE='app-svc=2 balancer-svc=2'
PROD_SIZE ?= small
PROD_SCALE_small  := app-svc=1 identity-svc=1 tournament-svc=2 frontend=2
PROD_SCALE_medium := app-svc=2 identity-svc=1 tournament-svc=2 frontend=2
PROD_SCALE_large  := app-svc=2 identity-svc=2 tournament-svc=4 frontend=3
PROD_SCALE ?= $(PROD_SCALE_$(PROD_SIZE))

help:
	@echo "Available commands:"
	@echo "  make dev-build      - Build dev images"
	@echo "  make dev-up         - Start core dev stack (no workers)"
	@echo "  make dev-up-full    - Start dev stack with workers"
	@echo "  make dev-down       - Stop dev stack"
	@echo "  make dev-logs       - Follow dev logs"
	@echo "  make dev-ps         - Show dev services"
	@echo "  make dev-health     - Show dev health status"
	@echo "  make dev-rebuild    - Rebuild and restart core dev stack"
	@echo ""
	@echo "  make prod-build     - Build production images locally (CI normally builds them)"
	@echo "  make prod-pull      - Pull the images CI built (IMAGE_TAG=<release> to pin)"
	@echo "  make prod-migrate   - alembic upgrade head from the pulled image"
	@echo "  make prod-up        - Start production stack (PROD_SIZE=small|medium|large)"
	@echo "  make prod-down      - Stop production stack"
	@echo "  make prod-logs      - Follow production logs"
	@echo "  make prod-scale     - Re-apply replica counts for PROD_SIZE"
	@echo "  make prod-small     - Scale production to small (1 tournament/app/identity/frontend)"
	@echo "  make prod-medium    - Scale production to medium (2 of each)"
	@echo "  make prod-large     - Scale production to large (4 tournament, 3 frontend)"
	@echo ""
	@echo "  make monitoring-up  - Start monitoring stack, metrics only (requires prod-up first)"
	@echo "                        add MONITORING_PROFILES=\"logs traces\" for loki/tempo"
	@echo "  make monitoring-down- Stop monitoring stack"
	@echo "  make monitoring-logs- Follow monitoring logs"
	@echo "  make monitoring-ps  - Show monitoring services"
	@echo "  make backup-up      - Start backup rustfs (source, dd-new)"
	@echo "  make backup-setup   - (Re)configure buckets + replication to home"
	@echo "  make backup-run     - Run a backup now (dump -> rustfs -> replica check)"
	@echo "  make backup-ls      - List what is stored in the replica (home)"
	@echo "  make backup-down    - Stop backup rustfs"
	@echo "  make backup-logs    - Follow backup rustfs logs"
	@echo ""
	@echo "  make migrate        - Run backend migrations"
	@echo "  make test           - Run backend tests"
	@echo "  make clean          - Remove compose resources"

dev-build:
	$(COMPOSE) build

dev-up:
	$(COMPOSE) up -d --wait

dev-up-full:
	$(COMPOSE) --profile workers up -d --wait

dev-down:
	$(COMPOSE) down --remove-orphans

dev-restart:
	$(COMPOSE) restart

dev-logs:
	$(COMPOSE) logs -f

dev-ps:
	$(COMPOSE) ps

dev-health:
	$(COMPOSE) ps --format "table {{.Service}}\t{{.State}}\t{{.Health}}"

dev-rebuild:
	$(COMPOSE) up -d --build --wait

# Local build. Production images normally come from CI (GitHub Actions builds
# and pushes them to GHCR; see .github/workflows/deploy-production.yml), so this
# is for a box that has to build for itself — a hotfix with no release, or a
# host CI cannot reach.
prod-build:
	$(PROD_COMPOSE) build

# Fetch what CI built. IMAGE_TAG selects a release (defaults to :latest).
prod-pull:
	$(PROD_COMPOSE) pull

# Starts the production stack with the workers in $(PROD_SCALE) replicated
# from the first boot — no separate `prod-scale` call needed. RabbitMQ
# competing-consumers distribute RPC calls across replicas with no extra config.
# PREREQUISITE: enable pgBouncer first (DB_PGBOUNCER=true, see
# backend/env/common.env.example) or the replicas will exhaust Postgres
# connections.
prod-up:
	@test -n "$(PROD_SCALE)" || (echo "unknown PROD_SIZE=$(PROD_SIZE) (want small|medium|large)"; exit 1)
	$(PROD_COMPOSE) up -d --remove-orphans --wait $(foreach s,$(PROD_SCALE),--scale $(s))

prod-down:
	$(PROD_COMPOSE) down --remove-orphans

prod-logs:
	$(PROD_COMPOSE) logs -f

# Re-apply replica counts on an already-running stack (same knob as `prod-up`).
prod-scale: prod-up

prod-small:
	$(MAKE) prod-scale PROD_SIZE=small

prod-medium:
	$(MAKE) prod-scale PROD_SIZE=medium

prod-large:
	$(MAKE) prod-scale PROD_SIZE=large

# Dev stack. The production one is `prod-migrate`: it runs alembic in a one-off
# container off the NEW image, which is what makes the schema land before the
# code that reads it.
migrate:
	$(COMPOSE) exec app-svc alembic upgrade head

prod-migrate:
	$(PROD_COMPOSE) run --rm --no-deps app-svc alembic upgrade head

test:
	$(COMPOSE) exec app-svc pytest


# Locust load tests against the running edge (see loadtests/README.md).
# loadtest-ui opens the web UI on :8089; loadtest runs headless.
# Override e.g.: make loadtest LOAD_USERS=200 LOAD_TIME=10m LOAD_HOST=https://staging.example.com
LOAD_USERS ?= 50
LOAD_RATE ?= 5
LOAD_TIME ?= 5m
LOAD_HOST ?= http://localhost

loadtest:
	cd loadtests && uv run locust --headless -u $(LOAD_USERS) -r $(LOAD_RATE) -t $(LOAD_TIME) --host $(LOAD_HOST) --csv results --html report.html

loadtest-ui:
	cd loadtests && uv run locust --host $(LOAD_HOST)

clean:
	$(COMPOSE) down -v --remove-orphans

# Backward-compatible aliases
build: dev-build
up: dev-up
down: dev-down
restart: dev-restart
logs: dev-logs
ps: dev-ps
health: dev-health
build-prod: prod-build
up-prod: prod-up
down-prod: prod-down
logs-prod: prod-logs

app-logs:
	$(COMPOSE) logs -f app-svc

identity-logs:
	$(COMPOSE) logs -f identity-svc

parser-logs:
	$(COMPOSE) logs -f parser-svc

frontend-logs:
	$(COMPOSE) logs -f frontend

discord-logs:
	$(COMPOSE) logs -f discord-worker

balancer-logs:
	$(COMPOSE) logs -f balancer-svc

stream-logs:
	$(COMPOSE) logs -f stream-svc

app-restart:
	$(COMPOSE) restart app-svc

identity-restart:
	$(COMPOSE) restart identity-svc

parser-restart:
	$(COMPOSE) restart parser-svc

frontend-restart:
	$(COMPOSE) restart frontend

app-rebuild:
	$(COMPOSE) up -d --build --wait app-svc

identity-rebuild:
	$(COMPOSE) up -d --build --wait identity-svc

parser-rebuild:
	$(COMPOSE) up -d --build --wait parser-svc

frontend-rebuild:
	$(COMPOSE) stop frontend && $(COMPOSE) rm -f frontend
	-docker volume rm owt_frontend-node-modules 2>/dev/null
	-docker volume rm owt_frontend-next 2>/dev/null
	$(COMPOSE) up -d --build --wait frontend

# ==============================================================================
# Monitoring stack (separate Compose project: owt-monitoring)
# Attaches to the production stack's network, so the prod stack must be up
# first (`make prod-up`) — it creates the shared `owt_app-network`.
# ==============================================================================
monitoring-up:
	$(MONITORING_COMPOSE) up -d

monitoring-down:
	$(MONITORING_COMPOSE) down

monitoring-logs:
	$(MONITORING_COMPOSE) logs -f

monitoring-ps:
	$(MONITORING_COMPOSE) ps

# ==============================================================================
# Контур резервных копий (отдельный проект owt-backup, хост dd-new).
# Полная процедура установки и восстановления — docs/backup-rustfs.md.
# ==============================================================================
backup-up:
	$(BACKUP_COMPOSE) up -d --wait

backup-down:
	$(BACKUP_COMPOSE) down

backup-logs:
	$(BACKUP_COMPOSE) logs -f

# Идемпотентно: бакеты, версионирование, ILM, ключ реплики, правило репликации
# и проверка round-trip.
backup-setup:
	ops/backup/setup.sh $(BACKUP_ENV)

# Прогон вне расписания (то же, что делает таймер systemd).
backup-run:
	ops/backup/backup.sh $(BACKUP_ENV)

# Что реально лежит на home. Единственный ответ на вопрос «есть ли бэкап».
# Через bash -c: рецепты make исполняет /bin/sh, а lib.sh — bash-скрипт.
backup-ls:
	@bash -c 'source ops/backup/lib.sh; load_env $(BACKUP_ENV); mc ls --recursive "replica/$$BACKUP_BUCKET/"'
