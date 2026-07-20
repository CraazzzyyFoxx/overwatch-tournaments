# Monitoring Deployment

This document explains how the system monitoring stack is deployed for OWT.

Monitoring runs as its **own** Docker Compose project (`owt-monitoring`) defined in
the repository-root file `docker-compose.monitoring.yml`, using configs stored in `monitoring/`.
It is intentionally separate from the application stack (`docker-compose.production.yml`,
project `owt`) so telemetry can be started, updated, and restarted
independently of the app.

Services:

- Prometheus — metrics collection and alerting rules (remote-write receiver enabled
  for Tempo's span-metrics / service-graph series)
- Alertmanager — alert routing to Discord
- Grafana — dashboards for metrics, logs, and traces
- Loki — log storage
- Promtail — log shipping
- Tempo — distributed tracing backend (metrics_generator pushes span-metrics into Prometheus)
- OpenTelemetry Collector — trace ingestion (OTLP)
- Redis Exporter — Redis metrics
- RabbitMQ Exporter — RabbitMQ metrics (management API)
- Node Exporter — host CPU / memory / disk / network
- cAdvisor — per-container CPU / memory / restarts
- Postgres Exporter — PostgreSQL metrics

## Dashboards

Provisioned into the `OWT` folder (deleting a JSON file under
`monitoring/grafana/dashboards/` removes the dashboard — `disableDeletion: false`):

| Dashboard | uid | What it shows |
|---|---|---|
| Application Logs (home) | `app-logs` | Log rates by level/service, errors-only stream, full-text `$search`, live stream |
| Workers & Queues | `workers-queues` | Worker throughput/latency/errors, RabbitMQ queue depth + DLQ + consumers + publish/deliver rates, balancer job timings |
| Gateway | `gateway-usage` | Edge RPS / 4xx-5xx / latency (total + per route), WS connections, DAU/WAU/MAU, Go runtime |
| Tracing | `tracing-overview` | RED per service from Tempo span-metrics, service graph, TraceQL slow/error traces, logs-with-trace links |
| Infrastructure | `infrastructure` | Host CPU/RAM/disk (+7d disk forecast), per-container resources, PostgreSQL, Redis |

All monitoring services have CPU/memory limits set via `deploy.resources` so they cannot
starve the host.

## How networking works

The monitoring stack attaches to the application stack's network as an **external** network:

```yaml
networks:
  app-network:
    external: true
    name: owt_app-network
```

This means scrape targets such as `gateway:9110`, `redis:6379`, and `rabbitmq:15672` resolve
by service name across the shared network — but it also means the **application stack must be
running first**, because it is what creates `owt_app-network`.

## Prerequisites

1. Docker and Docker Compose are installed on the host.
2. The application stack is already running (`make prod-up`) so the shared network exists.
3. The host log directories exist under `logs/`, because Promtail reads logs from there.

Application logs are mounted from `./logs` into Promtail as `/var/log/app`.

> **Note on data:** the monitoring project uses its own fresh named volumes
> (`prometheus_data`, `loki_data`, `tempo_data`, `grafana_data`, `alertmanager_data`).
> Historical metrics/logs/traces start empty on first run. Grafana datasources and
> dashboards are provisioned from files in `monitoring/grafana/provisioning/`, so they
> are restored automatically.

## What the stack exposes

Only Grafana is published to the host. Prometheus, Loki, Tempo, Alertmanager, and the
exporters are reachable internally over the shared Docker network and are browsed through
Grafana (Explore / datasources):

- Grafana: `http://localhost:3001`

## 1. Prepare environment variables

The monitoring stack can start with defaults, but production deployment should set explicit
credentials.

```bash
export GRAFANA_ADMIN_USER=admin
export GRAFANA_ADMIN_PASSWORD='change-me'
export GRAFANA_PORT=3001
export GRAFANA_ROOT_URL='http://localhost:3001'
export TEMPO_URL='http://tempo:3200'
```

The RabbitMQ exporter reads `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` — the **same
variables the broker itself uses** — so with a repository-root `.env` no extra export is
needed. Note that RabbitMQ restricts the default `guest` user to loopback connections:
production must run the broker with non-guest credentials or the exporter (a separate
container) will get 401s. (Dev compose mounts `monitoring/rabbitmq/dev-loopback.conf` to
lift the restriction locally.)

The Postgres exporter needs a DSN pointing **directly at PostgreSQL (port 5432), NOT at
pgBouncer (:6432)** — transaction pooling breaks the exporter's session-level queries:

```bash
export POSTGRES_EXPORTER_DSN='postgresql://user:pass@host.docker.internal:5432/anak_dev?sslmode=disable'
```

(Put it in the repository-root `.env` so `make monitoring-up` picks it up.)

For Discord alert delivery, create a local secret file that is not committed to git:

```bash
cp monitoring/secrets/discord_webhook_url.example monitoring/secrets/discord_webhook_url
```

Then replace the example value with the real Discord webhook URL.

## 2. Start monitoring

Make sure the application stack is up first:

```bash
make prod-up
```

Validate and start monitoring (from the repository root):

```bash
docker compose -f docker-compose.monitoring.yml config   # validate
make monitoring-up                                        # start
make monitoring-ps                                        # status
```

`make monitoring-up` is equivalent to `docker compose -f docker-compose.monitoring.yml up -d`.

## 3. Verify the deployment

Follow logs if any service is restarting or unhealthy:

```bash
make monitoring-logs
```

### Grafana

Open `http://localhost:3001` and log in with `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`.

Provisioned datasources:

- Prometheus -> `http://prometheus:9090`
- Loki -> `http://loki:3100`
- Tempo -> `${TEMPO_URL}` (default `http://tempo:3200`)

Dashboards are provisioned into the `OWT` folder; the default home dashboard
is `Application Logs`.

### Prometheus targets

Browse Prometheus through Grafana, or temporarily publish port `9090` if you need the raw
targets UI. At minimum `redis-exporter:9121` and `rabbitmq-exporter:9419` should be `UP`.
Application targets become healthy only if the scrape hostnames match the real service names
on the shared network.

### Loki and Promtail

Use Grafana Explore to query Loki. Promtail reads log files from `logs/**/*.log`. If no logs
appear, confirm the application is writing JSON logs into the repository `logs/` directory.

## 4. Stop or restart monitoring

```bash
make monitoring-down                                          # stop + remove monitoring containers
docker compose -f docker-compose.monitoring.yml restart prometheus   # restart one service after a config change
```

Stopping monitoring does **not** affect the application stack — they are separate projects,
and the shared network is external (Compose will not remove it).

## Verify resource limits

```bash
docker stats            # MEM USAGE / LIMIT and CPU % columns
docker inspect <container> --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
```

Both application and monitoring containers now report non-zero memory/CPU limits.

## Alerting setup note

Alertmanager reads the Discord webhook from `monitoring/secrets/discord_webhook_url` through
the mounted path `/run/secrets/discord_webhook_url`, keeping the real webhook out of git.

## Troubleshooting

### `make monitoring-up` fails with a network error

Cause: the external network `owt_app-network` does not exist yet.

Fix: start the application stack first with `make prod-up`, then retry.

### Prometheus shows app targets as DOWN

Cause: target hostnames in `monitoring/prometheus/prometheus.yml` do not match the real Docker
service names, or the app services are not on the shared network.

Fix: compare the targets with service names in `docker-compose.production.yml`, update
`monitoring/prometheus/prometheus.yml`, and restart Prometheus.

### RabbitMQ exporter is UP but returns no useful data (`rabbitmq_up 0`)

Cause: wrong RabbitMQ credentials, or the broker runs as `guest`/`guest` (RabbitMQ rejects
`guest` on non-loopback connections, and the exporter is a separate container).

Fix: make sure `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` in the root `.env` match the
broker's real (non-guest) credentials and restart `rabbitmq-exporter`.

### Postgres exporter shows `pg_up 0`

Cause: `POSTGRES_EXPORTER_DSN` is missing, points at pgBouncer (:6432), or the host address
is wrong from inside the container.

Fix: set a DSN that reaches PostgreSQL directly on 5432 (use `host.docker.internal` for a
DB on the Docker host) and restart `postgres-exporter`.

### Tracing dashboard is empty / service graph shows nothing

Cause: Tempo's metrics_generator series are not reaching Prometheus.

Fix: confirm Prometheus runs with `--web.enable-remote-write-receiver` and Tempo's
`metrics_generator.storage.remote_write` targets `http://prometheus:9090/api/v1/write`;
check `traces_spanmetrics_calls_total` in Prometheus after some sampled traffic
(sampling is 10%, so quiet environments need a few requests).

### Alertmanager starts but Discord alerts are not delivered

Cause: `monitoring/secrets/discord_webhook_url` is missing, empty, or invalid.

Fix: create it from the `.example` file, put in the real webhook, restart `alertmanager`.

### Loki is healthy but no logs appear in Grafana

Cause: Promtail does not see files in `logs/`.

Fix: confirm fresh `.log` files exist under `logs/`, that `promtail` is running, and check
`make monitoring-logs`.

## Updating a running deployment

After pulling monitoring/gateway changes on the production host
(`/root/overwatch-tournaments`):

```bash
git pull
# 1) .env sanity: RABBITMQ_DEFAULT_USER/PASS set (non-guest) + POSTGRES_EXPORTER_DSN added.
# 2) Gateway (tracing needs a rebuild):
docker compose -f docker-compose.production.yml build gateway
docker compose -f docker-compose.production.yml up -d gateway
docker compose -f docker-compose.production.yml restart nginx   # REQUIRED, else 502
# 3) Monitoring stack:
make monitoring-down && make monitoring-up
```

Then verify: Grafana shows exactly 5 dashboards in `OWT` (stale ones are
auto-removed), Prometheus targets are UP (incl. app-svc/identity-svc/analytics-svc/
analytics-worker/node/cadvisor/postgres), and the RabbitMQ panels on Workers & Queues
have data.

## Files involved in deployment

- `docker-compose.monitoring.yml` - monitoring stack (project `owt-monitoring`)
- `docker-compose.production.yml` - application stack (project `owt`)
- `monitoring/prometheus/prometheus.yml` - Prometheus scrape jobs and alertmanager target
- `monitoring/prometheus/rules/` - alert rules
- `monitoring/alertmanager/alertmanager.yml` - alert routing
- `monitoring/secrets/discord_webhook_url.example` - example Discord webhook secret file
- `monitoring/loki/loki.yml`, `monitoring/tempo/tempo.yml`, `monitoring/otel/otel-collector.yml` - backends
- `monitoring/promtail/promtail.yml` - log collection
- `monitoring/grafana/provisioning/` - Grafana datasources and dashboards
