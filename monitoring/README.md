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
- OpenTelemetry Collector — trace ingestion (OTLP), fanned out to **both** Tempo
  and Sentry (Sentry Exporter, see "Sentry tracing" below)
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

### Sentry tracing

The collector forwards the same OTLP trace stream to Sentry, so a distributed
trace (gateway -> RabbitMQ -> service -> SQL) shows up in Sentry Tracing next to
the Issues it caused, not only in Tempo. Sentry routes by resource attribute; the
collector stamps a constant `sentry.project` so a newly added service cannot
silently lose its spans:

```bash
export SENTRY_ORG_SLUG='craazzzyyfoxx'          # default
export SENTRY_OTEL_PROJECT='owt-tournaments'    # default; same project as the SDK DSN
export SENTRY_OTEL_AUTH_TOKEN='sntrys_...'      # REQUIRED, no usable default
```

The token is a Sentry **Internal Integration** token (Settings -> Developer
Settings -> Custom Integrations -> Internal Integration) with `org:read` and
`project:read`. Put it in the repository-root `.env` so `make monitoring-up`
picks it up.

Without it the collector still starts and Tempo keeps working — the compose
fallback (`unset`) is non-empty on purpose, because the exporter rejects an empty
token at config validation and would crash-loop the whole collector. Only the
Sentry branch degrades, with `Failed to pre-populate project cache` in the logs.

The application SDKs deliberately send **no** transactions of their own
(`SENTRY_TRACES_SAMPLE_RATE=0` in `backend/env/*.env`); they only link errors and
logs to the OTel trace. Turning SDK tracing back on bills a second, disconnected
copy of every request.

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

### Tiers: metrics always, logs and traces on demand

Metrics (prometheus, alertmanager, grafana, every exporter) always start. Log
storage (`loki` + `promtail`) and traces (`tempo` + `otel-collector`) sit behind
the compose profiles `logs` and `traces`, because together they cost ~470M of
RSS plus page cache — on a 4 CPU / 8G box that memory belongs to PostgreSQL,
whose working set is several GB:

```bash
make monitoring-up                                   # metrics only (default)
make monitoring-up MONITORING_PROFILES="logs traces" # everything
```

Grafana keeps its Loki and Tempo datasources either way — they resolve lazily,
so with the profiles off those datasources simply return errors and the
`Application Logs` / tracing dashboards stay empty. Prometheus does not scrape
`promtail`, `tempo` or `otel-collector`, so a metrics-only host raises no
`TargetDown` alert for them.

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
is `Infrastructure` (`Application Logs` needs the `logs` profile).

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

### Traces reach Tempo but not Sentry

Cause: missing/expired `SENTRY_OTEL_AUTH_TOKEN`, or the project slug in
`SENTRY_OTEL_PROJECT` does not exist in the org (`auto_create_projects` is off on
purpose).

Fix: check the collector logs for `Failed to pre-populate project cache` or
`project not found`, then confirm the counters diverge:

```bash
docker exec owt-monitoring-prometheus-1 \
  wget -qO- http://otel-collector:8888/metrics | grep -E 'sent_spans|send_failed_spans'
```

`otelcol_exporter_sent_spans{exporter="sentry"}` climbing means ingestion works;
`otelcol_exporter_send_failed_spans{exporter="sentry"}` climbing is an auth or
routing problem. Sentry-side lag is under a minute, and app sampling is 10%, so a
quiet environment needs a few requests before anything shows up.

### Alertmanager restarts in a loop / Discord alerts are not delivered

Cause: `monitoring/secrets/discord_webhook_url` is missing, empty, or invalid. The file
is gitignored, so a fresh checkout never has it and `alertmanager` crash-loops with
`Loading configuration file failed ... no discord webhook URL provided`.

Fix: create it from the `.example` file, put in the real webhook, recreate the container:

```bash
printf '%s' 'https://discord.com/api/webhooks/<id>/<token>' \
  > monitoring/secrets/discord_webhook_url
# The image runs as nobody; a root-owned 600 file yields "permission denied"
# at notify time even though the config loads fine.
chown 65534:65534 monitoring/secrets/discord_webhook_url
chmod 400 monitoring/secrets/discord_webhook_url
docker compose -f docker-compose.monitoring.yml up -d alertmanager
```

The same log line on an image older than `v0.28.0` is a different bug: those versions
read `webhook_url_file` but still require `webhook_url`, so the secret file alone never
satisfies them. Keep the pinned `prom/alertmanager:v0.28.1` or newer.

Verify delivery end to end by posting a synthetic alert:

```bash
docker exec owt-monitoring-alertmanager-1 wget -qO- \
  --header='Content-Type: application/json' \
  --post-data='[{"labels":{"alertname":"WebhookSmokeTest","severity":"warning"},"annotations":{"summary":"manual test","description":"verifying Discord delivery"}}]' \
  http://localhost:9093/api/v2/alerts
```

### Loki is healthy but no logs appear in Grafana

Cause: Promtail does not see files in `logs/`.

Fix: confirm fresh `.log` files exist under `logs/`, that `promtail` is running, and check
`make monitoring-logs`.

## Updating a running deployment

After pulling monitoring/gateway changes on the production host
(`/root/overwatch-tournaments`):

```bash
git pull
# 1) .env sanity: RABBITMQ_DEFAULT_USER/PASS set (non-guest), POSTGRES_EXPORTER_DSN
#    added, and SENTRY_OTEL_AUTH_TOKEN added (else traces stop at Tempo).
# 2) Gateway (tracing needs a rebuild):
docker compose -f docker-compose.production.yml build gateway
docker compose -f docker-compose.production.yml up -d gateway
docker compose -f docker-compose.production.yml restart nginx   # REQUIRED, else 502
# 3) Monitoring stack:
make monitoring-down && make monitoring-up
```

Then verify: Grafana shows exactly 5 dashboards in `OWT` (stale ones are
auto-removed), Prometheus targets are UP (incl. app-svc/identity-svc/analytics-svc/
analytics-worker/node/cadvisor/postgres), the RabbitMQ panels on Workers & Queues
have data, and `otelcol_exporter_sent_spans{exporter="sentry"}` is climbing (see
"Traces reach Tempo but not Sentry").

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
