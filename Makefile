.PHONY: help dev-build dev-up dev-up-full dev-down dev-restart dev-logs dev-ps dev-health dev-rebuild \
	prod-build prod-up prod-down prod-logs prod-scale migrate test clean \
	build up down restart logs ps health build-prod up-prod down-prod logs-prod \
	app-logs identity-logs parser-logs frontend-logs discord-logs balancer-logs \
	app-restart identity-restart parser-restart frontend-restart \
	monitoring-up monitoring-down monitoring-logs monitoring-ps \
	app-rebuild identity-rebuild parser-rebuild frontend-rebuild

COMPOSE = docker compose
PROD_COMPOSE = docker compose -f docker-compose.production.yml
MONITORING_COMPOSE = docker compose -f docker-compose.monitoring.yml

# Stateless RPC workers that are safe to replicate: competing consumers on
# RabbitMQ spread RPC calls across replicas automatically, cache lives in shared
# Redis, and DB access goes through pgBouncer. Do NOT add balancer-svc (owns the
# draft clock) or analytics-worker (jobs not yet idempotent) — those are
# singletons. Override on the CLI, e.g. `make prod-scale PROD_SCALE='app-svc=3'`.
PROD_SCALE ?= app-svc=2 identity-svc=2

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
	@echo "  make prod-build     - Build production images"
	@echo "  make prod-up        - Start production stack (app only, no monitoring)"
	@echo "  make prod-down      - Stop production stack"
	@echo "  make prod-logs      - Follow production logs"
	@echo "  make prod-scale     - Scale stateless RPC workers (PROD_SCALE='app-svc=3 ...')"
	@echo ""
	@echo "  make monitoring-up  - Start monitoring stack (requires prod-up first)"
	@echo "  make monitoring-down- Stop monitoring stack"
	@echo "  make monitoring-logs- Follow monitoring logs"
	@echo "  make monitoring-ps  - Show monitoring services"
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

prod-build:
	$(PROD_COMPOSE) build

prod-up:
	$(PROD_COMPOSE) up -d --wait

prod-down:
	$(PROD_COMPOSE) down --remove-orphans

prod-logs:
	$(PROD_COMPOSE) logs -f

# Horizontally scale the stateless RPC workers in $(PROD_SCALE). RabbitMQ
# competing-consumers distribute RPC calls across replicas with no extra config.
# PREREQUISITE: enable pgBouncer first (DB_PGBOUNCER=true, see
# backend/env/common.env.example) or the replicas will exhaust Postgres
# connections. Scale back down by passing =1, e.g. PROD_SCALE='app-svc=1'.
prod-scale:
	$(PROD_COMPOSE) up -d --wait $(foreach s,$(PROD_SCALE),--scale $(s))

migrate:
	$(COMPOSE) exec app-svc alembic upgrade head

test:
	$(COMPOSE) exec app-svc pytest

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
