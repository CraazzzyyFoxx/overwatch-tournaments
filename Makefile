.PHONY: help dev-build dev-up dev-up-full dev-down dev-restart dev-logs dev-ps dev-health dev-rebuild \
	prod-build prod-up prod-down prod-logs migrate test clean \
	build up down restart logs ps health build-prod up-prod down-prod logs-prod \
	backend-logs auth-logs parser-logs frontend-logs discord-logs balancer-logs \
	backend-restart auth-restart parser-restart frontend-restart \
	monitoring-up monitoring-down monitoring-logs monitoring-ps \
	backend-rebuild auth-rebuild parser-rebuild frontend-rebuild

COMPOSE = docker compose
PROD_COMPOSE = docker compose -f docker-compose.production.yml
MONITORING_COMPOSE = docker compose -f docker-compose.monitoring.yml

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

migrate:
	$(COMPOSE) exec backend alembic upgrade head

test:
	$(COMPOSE) exec backend pytest

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

backend-logs:
	$(COMPOSE) logs -f backend

auth-logs:
	$(COMPOSE) logs -f auth

parser-logs:
	$(COMPOSE) logs -f parser

frontend-logs:
	$(COMPOSE) logs -f frontend

discord-logs:
	$(COMPOSE) logs -f discord

balancer-logs:
	$(COMPOSE) logs -f balancer

backend-restart:
	$(COMPOSE) restart backend

auth-restart:
	$(COMPOSE) restart auth

parser-restart:
	$(COMPOSE) restart parser

frontend-restart:
	$(COMPOSE) restart frontend

backend-rebuild:
	$(COMPOSE) up -d --build --wait backend

auth-rebuild:
	$(COMPOSE) up -d --build --wait auth

parser-rebuild:
	$(COMPOSE) up -d --build --wait parser

frontend-rebuild:
	$(COMPOSE) stop frontend && $(COMPOSE) rm -f frontend
	-docker volume rm anak-tournaments_frontend-node-modules 2>/dev/null
	-docker volume rm anak-tournaments_frontend-next 2>/dev/null
	$(COMPOSE) up -d --build --wait frontend

# ==============================================================================
# Monitoring stack (separate Compose project: overwatch-monitoring)
# Attaches to the production stack's network, so the prod stack must be up
# first (`make prod-up`) — it creates the shared `overwatch-tournaments_app-network`.
# ==============================================================================
monitoring-up:
	$(MONITORING_COMPOSE) up -d

monitoring-down:
	$(MONITORING_COMPOSE) down

monitoring-logs:
	$(MONITORING_COMPOSE) logs -f

monitoring-ps:
	$(MONITORING_COMPOSE) ps
