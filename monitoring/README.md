# Monitoring Deployment

This document explains how the system monitoring stack is deployed for Anak Tournaments.

Monitoring runs as its **own** Docker Compose project (`owt-monitoring`) defined in
the repository-root file `docker-compose.monitoring.yml`, using configs stored in `monitoring/`.
It is intentionally separate from the application stack (`docker-compose.production.yml`,
project `owt`) so telemetry can be started, updated, and restarted
independently of the app.

Services:

- Prometheus — metrics collection and alerting rules
- Alertmanager — alert routing to Discord
- Grafana — dashboards for metrics, logs, and traces
- Loki — log storage
- Promtail — log shipping
- Tempo — distributed tracing backend
- OpenTelemetry Collector — trace ingestion (OTLP)
- Redis Exporter — Redis metrics
- RabbitMQ Exporter — RabbitMQ metrics

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

export RABBITMQ_USER='your-rabbitmq-user'
export RABBITMQ_PASSWORD='your-rabbitmq-password'
```

If RabbitMQ in the application stack uses `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS`,
set `RABBITMQ_USER` / `RABBITMQ_PASSWORD` to the same credentials before starting monitoring.

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

Dashboards are provisioned into the `Anak Tournaments` folder; the default home dashboard
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

### RabbitMQ exporter is UP but returns no useful data

Cause: wrong RabbitMQ credentials.

Fix: set `RABBITMQ_USER` / `RABBITMQ_PASSWORD` to the application's values and restart
`rabbitmq-exporter`.

### Alertmanager starts but Discord alerts are not delivered

Cause: `monitoring/secrets/discord_webhook_url` is missing, empty, or invalid.

Fix: create it from the `.example` file, put in the real webhook, restart `alertmanager`.

### Loki is healthy but no logs appear in Grafana

Cause: Promtail does not see files in `logs/`.

Fix: confirm fresh `.log` files exist under `logs/`, that `promtail` is running, and check
`make monitoring-logs`.

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
