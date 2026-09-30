# Monitoring

Production monitoring is split across two hosts on purpose. The production host runs only a
telemetry agent; storage, dashboards and alerting run on a separate **monitoring host**. A
monitoring stack on the production host goes silent together with it; with the stack
elsewhere, "production is hung" is itself an alert.

## Where things run

| Host | What | Where it is defined |
|---|---|---|
| production | `alloy` — scrapes the stack, tails `./logs`, receives OTLP, pushes everything to the monitoring host | `docker-compose.production.yml`, profile `telemetry`; config `monitoring/alloy/moscow.alloy` |
| production | `nginx-exporter` — nginx `stub_status` (Alloy has no embedded nginx exporter) | `docker-compose.production.yml`, profile `telemetry` |
| monitoring | `owt-monitoring`: Prometheus, Alertmanager, Grafana, Loki, Tempo, blackbox-exporter, `proxy` (xray, Alertmanager's egress to Discord) | `docker-compose.monitoring.yml` |

The profile keeps the agent production-only: production sets `COMPOSE_PROFILES=telemetry` in
the root `.env`; a second deployment runs the same `docker-compose.production.yml` without
it (`docs/dev-site.md`), so its telemetry never reaches production monitoring.

`make monitoring-*` belongs on the monitoring host. On the production host it would start the
monitoring stack next to the app.

**Local development** is separate: `docker-compose.yml` runs its own small stack from
`monitoring/prometheus/prometheus.yml`, `monitoring/promtail/promtail.yml` and
`monitoring/otel/otel-collector.yml`. Those three files are dev-only; production uses
`moscow.alloy` and `prometheus.home.yml`. When a log pipeline changes, change it in both
`promtail.yml` and `moscow.alloy`.

## Data flow

```
production (app-network)                     monitoring host
  services ──OTLP──► alloy:4317 ─┐
  scrape targets ───► alloy ─────┼─HTTPS + basic auth──► ingest endpoint
  ./logs ───────────► alloy ─────┘                         ├─ /api/v1/write      → prometheus 127.0.0.1:19090
                         └──OTLP──► Sentry                 ├─ /loki/api/v1/push  → loki       127.0.0.1:13101
                                                           └─ /v1/traces         → tempo      127.0.0.1:14318
                                                          grafana 127.0.0.1:13002
                                                          blackbox-exporter ──probes──► https://owt…/health, production :22
```

- **Metrics.** Alloy scrapes the same targets the old Prometheus did (docker-DNS names,
  `job` = `instance` = service name), RabbitMQ's built-in `rabbitmq_prometheus` plugin
  (`rabbitmq:15692/metrics/per-object`, filtered to the four metrics rules and dashboards use,
  plus `up`), and embedded exporters with the old `job` labels: `node` (with the textfile
  collector for `owt_backup.prom`), `cadvisor`, `redis`, `postgres`. It also scrapes itself
  (`job="alloy"`): that is where the `nginx_limit_*` counters derived from the nginx access
  log live. Everything goes out through `remote_write`.
- **Logs.** `./logs/**/*.log`, three pipelines (`app_services`, `gateway`, `nginx`). The first
  start reads from the end of each file; positions persist in the `alloy-data` volume.
- **Traces.** Services export OTLP to `alloy:4317` (`OTLP_ENDPOINT` in
  `docker-compose.production.yml`, sampling 10%). Alloy sends one copy to Tempo and one to
  Sentry's native OTLP ingest. The SDKs send no transactions of their own
  (`SENTRY_TRACES_SAMPLE_RATE=0`), so Sentry sees one trace per request, not one per process.

Nothing on the production host listens outside `app-network`. Alloy's UI stays on
`127.0.0.1:12345` inside its container. Every port of the monitoring stack binds `127.0.0.1`;
exposing the ingest endpoints and Grafana (TLS, basic auth) is outside the stack. The ingest
URLs are set in `moscow.alloy`.

## Secrets and configuration

| Where | Key | Purpose |
|---|---|---|
| production root `.env` | `COMPOSE_PROFILES=telemetry` | starts `alloy` and `nginx-exporter` |
| production root `.env` | `TELEMETRY_INGEST_USER`, `TELEMETRY_INGEST_PASSWORD` | basic auth on the ingest endpoints |
| production root `.env` | `SENTRY_OTLP_PUBLIC_KEY` | public key of `SENTRY_DSN`, header `x-sentry-auth` |
| production root `.env` | `POSTGRES_EXPORTER_DSN` | Postgres **:5432**, not pgBouncer :6432 (transaction pooling breaks the exporter) |
| monitoring root `.env` | `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_ROOT_URL` | Grafana |
| monitoring `monitoring/secrets/` | `discord_webhook_url` | Alertmanager → Discord |
| monitoring `proxy/xray.json` | xray client config (SOCKS5 on `proxy:1080`) | Alertmanager's route to Discord |

The secret files are gitignored. Alertmanager runs as `nobody`: make them readable by it
(`chmod 644`, or `chown 65534:65534` + `chmod 400`), or notifications fail with
"permission denied" even though the config loads.

## Running it

On the monitoring host, from a checkout:

```bash
git pull
make monitoring-up                               # docker compose -f docker-compose.monitoring.yml up -d
curl -s -XPOST 127.0.0.1:19090/-/reload          # after changing rules or prometheus.home.yml
```

On the production host the agent ships with every release: `ops/deploy/remote-deploy.sh`
checks out the tag and `make prod-up` recreates `alloy` when its image or definition changes.
A change to `moscow.alloy` alone does not recreate it:

```bash
docker compose -f docker-compose.production.yml restart alloy
```

Retention: Prometheus 14 days / 2 GB, Loki 7 days (`loki/loki.yml`), Tempo 48 hours
(`tempo/tempo.yml`). While the monitoring host is unreachable, Alloy keeps metrics in its WAL
(about two hours), resumes logs from the saved file positions, and holds traces only in memory.

## Alerts

Rules live in `monitoring/prometheus/rules/` and are evaluated on the monitoring host.
Routing (`alertmanager/alertmanager.yml`): everything to Discord, `critical` repeats hourly.

`prod_reachability.yml` holds the rules that must work while the production host itself is
down:

| Alert | Fires when |
|---|---|
| `ProdTelemetryAbsent` | no sample from production for 3 minutes (`absent_over_time(up{job="node"}[3m])`) — host hung or the path to the monitoring host broken |
| `ProdHttpDown` | the blackbox probe of `https://owt.craazzzyyfoxx.me/health` fails for 2 minutes |
| `ProdSshUnresponsive` | the production host's `:22` sends no `SSH-2.0-` banner for 2 minutes — TCP accepting while userspace is stalled |

There is no dead man's switch for the monitoring host itself: if it (or its Alertmanager) is
down, nothing alerts.

`HostIOPressureHigh` (`infrastructure.yml`) is the early warning: tasks fully stalled on I/O
more than 30% of the time.

## Dashboards

Provisioned into the `OWT` folder (deleting a JSON file under
`monitoring/grafana/dashboards/` removes the dashboard — `disableDeletion: false`):

| Dashboard | uid | What it shows |
|---|---|---|
| Application Logs | `app-logs` | Log rates by level/service, errors-only stream, full-text `$search`, live stream |
| Workers & Queues | `workers-queues` | Worker throughput/latency/errors, RabbitMQ queue depth + DLQ + consumers + publish/deliver rates, balancer job timings |
| Gateway | `gateway-usage` | Edge RPS / 4xx-5xx / latency (total + per route), WS connections, DAU/WAU/MAU, Go runtime |
| Tracing | `tracing-overview` | RED per service from Tempo span-metrics, service graph, TraceQL slow/error traces, logs-with-trace links |
| Infrastructure | `infrastructure` | Host CPU/RAM/disk (+7d disk forecast), per-container resources, PostgreSQL, Redis |

## Troubleshooting

**Is Alloy healthy?** Its image has no shell tools; ask from a container in its network
namespace:

```bash
docker run --rm --network container:owt-alloy-1 curlimages/curl:8.16.0 \
  -s http://127.0.0.1:12345/-/ready
docker run --rm --network container:owt-alloy-1 curlimages/curl:8.16.0 \
  -s http://127.0.0.1:12345/api/v0/web/components   # every component: health.state
docker logs owt-alloy-1 --since 10m | grep -i error
```

**Ingest returns 401.** `TELEMETRY_INGEST_PASSWORD` in the production `.env` does not match
what the ingest endpoint expects.

**No per-container metrics (`container_*` missing).** The Docker host uses the containerd
snapshotter; cAdvisor's docker factory needs `/run/containerd/containerd.sock`, which the
`alloy` service mounts. Without it Alloy logs "Registration of the docker container factory
failed".

**`pg_up 0`.** `POSTGRES_EXPORTER_DSN` is missing, points at pgBouncer (:6432), or cannot
resolve `host.docker.internal` (the `alloy` service maps it to the host gateway).

**RabbitMQ panels or rules empty.** The plugin's per-object endpoint is filtered in
`moscow.alloy` (`prometheus.relabel "rabbitmq"`); a new rule or panel on another RabbitMQ
metric needs that metric added to the keep regex.

**`nginx_limit_*` rejection counters missing.** They come from `loki.process "nginx"`
(`stage.metrics` with `prefix = ""`) and reach Prometheus only through Alloy scraping itself
(`job="alloy"`). No rejections yet also means no series.

**Traces reach Tempo but not Sentry.** Sentry's OTLP ingest is in open beta and drops span
events. Check `docker logs owt-alloy-1 | grep -i sentry` and `SENTRY_OTLP_PUBLIC_KEY`. To stop
sending to Sentry (quota), remove `otelcol.exporter.otlphttp.sentry.input` from
`otelcol.processor.batch "traces"` and restart Alloy; Tempo keeps working.

**Alertmanager restarts in a loop / nothing reaches Discord.** `monitoring/secrets/` is
missing a file, `nobody` cannot read it (see "Secrets"), or the `proxy` container is down or
its `proxy/xray.json` stopped working — `alertmanager_notifications_failed_total{integration="discord"}`
climbing with "Notify attempt failed" in the logs. Alertmanager does not reload its config on
its own: after editing `alertmanager.yml`, `docker exec owt-monitoring-alertmanager-1 wget -qO- --post-data= http://localhost:9093/-/reload`.
Post a synthetic alert to test delivery end to end:

```bash
docker exec owt-monitoring-alertmanager-1 wget -qO- \
  --header='Content-Type: application/json' \
  --post-data='[{"labels":{"alertname":"WebhookSmokeTest","severity":"warning"},"annotations":{"summary":"manual test","description":"verifying Discord delivery"}}]' \
  http://localhost:9093/api/v2/alerts
```

## Files

- `monitoring/alloy/moscow.alloy` — the production agent
- `docker-compose.monitoring.yml` — the monitoring stack (project `owt-monitoring`)
- `monitoring/prometheus/prometheus.home.yml` — Prometheus on the monitoring host: blackbox probes and self-monitoring
- `monitoring/prometheus/rules/` — alert and recording rules (shared with the dev stack)
- `monitoring/blackbox/blackbox.yml` — probe modules `http_2xx`, `ssh_banner`
- `monitoring/alertmanager/alertmanager.yml` — routing, Discord receiver
- `monitoring/loki/loki.yml`, `monitoring/tempo/tempo.yml` — backends (shared with the dev stack)
- `monitoring/grafana/provisioning/`, `monitoring/grafana/dashboards/` — Grafana
- `monitoring/prometheus/prometheus.yml`, `monitoring/promtail/promtail.yml`, `monitoring/otel/otel-collector.yml` — local dev stack only
