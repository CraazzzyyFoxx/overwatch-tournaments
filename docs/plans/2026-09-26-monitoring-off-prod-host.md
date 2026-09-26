# Мониторинг прода: с Moscow на home (Grafana Alloy)

**Status:** design approved (2026-09-26); план реализации пишется отдельным документом.

**Goal:** хранилища телеметрии, UI и алерты уезжают с продового хоста Moscow на home. На Moscow остаётся один
агент — Alloy. Алерты продолжают приходить, когда Moscow висит, а падение самого home тоже замечает внешний сервис.

**Architecture:** на Moscow один контейнер Grafana Alloy в `docker-compose.production.yml` под профилем `telemetry`.
Он скрейпит сервисы по docker-DNS и встроенными экспортёрами, тейлит `./logs`, принимает OTLP и сам **пушит** всё на
home по HTTPS: `remote_write`, Loki push, OTLP в Tempo; копия трейсов уходит прямо в Sentry по OTLP. На home отдельный
compose-проект `owt-monitoring`: Prometheus (сервер, приём remote-write, правила), Alertmanager, Grafana, Loki, Tempo,
blackbox-exporter. Blackbox проверяет прод снаружи. Приём на home закрыт Traefik: TLS + basic auth + allowlist по IP
Moscow.

**Tech Stack:** Grafana Alloy (встроенные `unix`, `cadvisor`, `redis`, `postgres`; `loki.*`; `otelcol.*`),
Prometheus 3.13 LTS, Alertmanager 0.34, Grafana, Loki 3.7, Tempo 2.10, blackbox_exporter,
nginx-prometheus-exporter, плагин `rabbitmq_prometheus` (RabbitMQ 3.13), Traefik 3.7 на home, healthchecks.io,
Sentry OTLP ingest (open beta).

**Связанные документы:** [`monitoring/README.md`](../../monitoring/README.md) (текущий стек, будет переписан),
[`disk-cleanup.md`](../disk-cleanup.md), [`dev-site.md`](../dev-site.md) (dev-сайт на home работает тем же
`docker-compose.production.yml`).

---

## 0. Область

**Делаем:** Alloy на Moscow вместо Prometheus/Grafana/Alertmanager и пяти экспортёров; стек хранения и UI на home;
логи (Loki) и трейсы (Tempo + Sentry), которые на проде сейчас выключены; внешние проверки прода и алерт
«с Moscow пропали метрики»; dead man's switch для home; перенос 14 дней истории Prometheus и данных Grafana.

**Не делаем** — §9.

**Сценарии приёмки:**

1. Moscow виснет так же, как 26.09: TCP принимается, userspace стоит на I/O. В Discord приходит critical не позже
   чем через 4 минуты (`ProdTelemetryAbsent` / `ProdSshUnresponsive` / `ProdHttpDown`).
2. home выключается. Не позже чем через 6 минут healthchecks.io сам пишет в Discord.
3. При лежащем Moscow `grafana.owt.craazzzyyfoxx.me` открывается и показывает метрики до момента зависания.
4. На Moscow нет Prometheus, Grafana, Alertmanager; `alloy` + `nginx-exporter` занимают меньше 300 MB RSS.
5. В Grafana ищутся логи каждого сервиса (Loki) и трейсы gateway → service (Tempo); спаны видны в Sentry.

---

## 1. Почему

- 26.09 Moscow дважды завис: 14:40–15:15 и 18:40–19:10 UTC. Виртуальный диск `sda` перестал завершать I/O
  (await 87 с; 0 tps при 88% util), `jbd2` и все пишущие процессы висели в D-state. Мониторинг на том же хосте
  замолчал вместе с ним: ни одного алерта, о падении сообщил пользователь.
- Мониторинг на Moscow занимает ~1 GB RSS (Grafana 464 MiB упирается в лимит 512 MiB, Prometheus 324 MiB),
  1.06 GB TSDB и 346 MB volume Grafana на том самом диске, который деградирует.
- Promtail с 2026-03-02 в EOL, rabbitmq-exporter (kbudde) заброшен с 2024. На проде оба не нужны.
- Сервисы шлют трейсы в `otel-collector:4317`, который на проде не запущен (identity-svc — 33 ошибки OTLP за
  5 минут).

## 2. Что где работает

### Moscow (прод, проект `owt`)

`alloy` — один контейнер в `docker-compose.production.yml`, сеть `app-network`, конфиг `monitoring/alloy/moscow.alloy`,
данные (WAL, позиции логов) в named volume `alloy-data`. Порты не публикуются.

- **Метрики.** Те же 16 джобов, что сейчас в `monitoring/prometheus/prometheus.yml`: 10 сервисных по
  docker-DNS (`gateway:9110`, `tournament-svc:9103`, …), `nginx-exporter:9113`, `rabbitmq:15692/metrics/per-object`
  (плагин вместо kbudde). Встроенные экспортёры с прежними `job`-лейблами: `unix` → `node` (с textfile-коллектором
  `/var/lib/node_exporter/textfile` для `owt_backup.prom`), `cadvisor` → `cadvisor` (только cpu/memory, как сейчас),
  `redis` → `redis`, `postgres` → `postgres` (DSN напрямую на Postgres :5432, не на pgBouncer). Интервал 30 с.
  Всё уходит `prometheus.remote_write` → `https://ingest.owt.craazzzyyfoxx.me/api/v1/write`.
- **Логи.** `./logs:/var/log/app:ro`, `local.file_match` + `loki.source.file` по `**/*.log`. Три пайплайна —
  `app_services`, `gateway`, `nginx` — переносятся из `monitoring/promtail/promtail.yml` через
  `alloy convert --source-format=promtail`. На первом старте `tail_from_end = true`: 1.1 GB старых логов в Loki не
  грузим. `loki.write` → `https://ingest.owt…/loki/api/v1/push`.
- **Трейсы.** `otelcol.receiver.otlp` на `:4317` (gRPC) и `:4318` (HTTP) → `otelcol.processor.batch` → два
  `otelcol.exporter.otlphttp`:
  - Tempo на home (`https://ingest.owt…`, путь `/v1/traces`);
  - Sentry: `https://o4504128802652160.ingest.us.sentry.io/api/4511564408946688/integration/otlp` (экспортёр сам
    дописывает `/v1/traces`), заголовок `x-sentry-auth: sentry sentry_key=<публичный ключ DSN>`.

`nginx-exporter` (16 MB) переезжает из `docker-compose.monitoring.yml` в `docker-compose.production.yml`: nginx-экспортёра
в Alloy нет.

Оба сервиса — под compose-профилем **`telemetry`**. Прод включает его строкой `COMPOSE_PROFILES=telemetry` в корневом
`.env`. Dev-сайт на home (`~/owt-dev`, тот же `docker-compose.production.yml`) профиль не включает и в прод-мониторинг
ничего не шлёт.

Сервисы: `OTLP_ENDPOINT=http://alloy:4317` в `backend/env/common.env`; `TRACING_ENABLED=true` для backend-сервисов
(сэмплинг 10%, как задано в `shared/core/config.py`).

С Moscow уходит весь проект `owt-monitoring`: prometheus, grafana, alertmanager, node-exporter, cadvisor,
redis-exporter, rabbitmq-exporter, postgres-exporter.

### home (проект `owt-monitoring`)

Отдельный чекаут `master` в `~/owt-monitoring`. `~/owt-dev` — single-branch `develop`, для прод-конфига не подходит.
Всё публикуется только на `127.0.0.1` (свободные порты; 3001, 3100, 9090, 9091 на home заняты).

- **prometheus** — сервер с `--web.enable-remote-write-receiver`, правила из `monitoring/prometheus/rules/`,
  retention как сейчас (14d / 2GB). Скрейпит только то, что живёт на home: blackbox-пробы и собственные метрики стека.
- **alertmanager** — Discord (тот же `webhook_url_file`) + receiver healthchecks.io для `Watchdog`.
- **grafana** — провижининг из `monitoring/grafana/`, данные из volume Moscow.
- **loki**, **tempo** — текущие конфиги; `metrics_generator` Tempo пишет в локальный Prometheus.
- **blackbox-exporter** — `monitoring/blackbox/blackbox.yml`, модули `http_2xx` и `ssh_banner` (TCP,
  `query_response: expect ^SSH-2.0-`).

Со стеком `prometheus`, который уже есть на home (он мониторит сам home, образы `:latest`), не смешиваем.

**Память:** на Moscow ~1 GB → Alloy ~150–250 MB + nginx-exporter ~20 MB. На home (12 CPU / 23 GB) полный стек
укладывается в ~2 GB.

## 3. Сеть и безопасность

**Направление одно: Moscow → home.** На Moscow не открывается ни одного входящего порта. Blackbox с home ходит на
прод как обычный посетитель. Проверено 26.09: Moscow → home:443 отвечает (`dev.owt`, 200, 84 мс), Moscow → Sentry
OTLP напрямую отвечает (401 без авторизации), прокси не нужен.

**DNS** (зона Timeweb): A-записи на `91.135.214.75`, по образцу `dev.owt`. Конкретная запись перебивает wildcard
`*.owt`, который смотрит на Moscow.

- `ingest.owt.craazzzyyfoxx.me` — приём телеметрии;
- `grafana.owt.craazzzyyfoxx.me` — переезжает с Moscow на шаге переключения (§5).

**Traefik на home** (`/etc/traefik/dynamic.yml`, сертификаты HTTP-01):

- `ingest.owt…`, маршруты по пути на `127.0.0.1`-порты `owt-monitoring`:
  - `/api/v1/write` → prometheus;
  - `/loki/api/v1/push` → loki;
  - `/v1/traces` → tempo (OTLP/HTTP);
  - остальное — 404: API запросов Prometheus и Loki наружу не торчат.
- Middleware на `ingest`: `ipAllowList: 217.149.19.31/32` **и** `basicAuth` (один пользователь для Alloy,
  bcrypt-хеш). Пароль — в корневом `.env` на Moscow (он не в git), Alloy получает его через env.
- `grafana.owt…` → grafana, без allowlist, вход по логину Grafana.

**TLS:** Alloy проверяет сертификат home штатно, без `insecure_skip_verify`.

**На Moscow после переключения:** из `/etc/traefik/dynamic/main.yml` удаляются роутер `grafana-owt` и сервис
`grafana-svc`.

**Буферизация, пока home недоступен:** метрики копятся в WAL Alloy (порядка 2 часов); логи дочитываются из файлов с
сохранённой позиции без потерь; трейсы держатся в памяти и при долгом простое теряются.

## 4. Алерты

**Переезжают без изменений:** `backup`, `gateway`, `infrastructure`, `nginx`, `overwatch_rank`, `redis`, `services`
(кроме RabbitMQ-выражений). Встроенные экспортёры Alloy — те же апстримные экспортёры, имена метрик совпадают;
`job`-лейблы сохранены. Маршрутизация Alertmanager прежняя: Discord, `critical` повторяется каждый час.

**Переписываются под плагин RabbitMQ:** `rules/rabbitmq.yml`, RabbitMQ-записи в `rules/services.yml`
(`rabbitmq:queue_depth` и др.), панели дашборда «Workers & Queues». `rabbitmq_up` → `up{job="rabbitmq"}`. Имена
очередных метрик сверяются с живым `/metrics/per-object` (у kbudde и плагина часть имён совпадает, часть нет).

**Новые** (`rules/prod_reachability.yml`, `HostIOPressureHigh` — в `rules/infrastructure.yml`):

| Алерт | Severity | Условие |
|---|---|---|
| `ProdTelemetryAbsent` | critical | `absent_over_time(up{job="node"}[3m])` — с Moscow 3 минуты не приходит ни одной метрики |
| `ProdHttpDown` | critical | `probe_success{job="blackbox-http"} == 0` 2 минуты, цель `https://owt.craazzzyyfoxx.me/health` |
| `ProdSshUnresponsive` | critical | `probe_success{job="blackbox-ssh"} == 0` 2 минуты, `217.149.19.31:22`, ждёт баннер `^SSH-2.0-` |
| `HostIOPressureHigh` | warning | `rate(node_pressure_io_stalled_seconds_total[2m]) > 0.3` 2 минуты |
| `Watchdog` | none | `vector(1)`, горит всегда |

**Dead man's switch:** маршрут `alertname = Watchdog` → webhook receiver на ping-URL healthchecks.io (`url_file` из
`monitoring/secrets/`), `group_interval` и `repeat_interval` 1m. Чек в healthchecks.io с периодом 1 мин и grace 5 мин
и Discord-интеграцией: если home или его Alertmanager умер, healthchecks.io пишет в Discord сам.

## 5. Переезд

Старый стек на Moscow работает до последнего шага, дыры в алертах нет.

0. **Вне репо (владелец):** A-запись `ingest.owt` → `91.135.214.75`; чек + Discord-интеграция в healthchecks.io,
   ping-URL. Запись `grafana.owt` на этом шаге не трогаем.
1. **home:** чекаут `master` в `~/owt-monitoring`, пустой стек, роуты `ingest` в Traefik. Копируется volume Grafana с
   Moscow (пользователи, аннотации, настройки).
2. **Релиз** с Alloy в прод-compose. На Moscow до деплоя: `COMPOSE_PROFILES=telemetry`, креды ingest и ключ Sentry в
   `.env`, `OTLP_ENDPOINT=http://alloy:4317` и `TRACING_ENABLED=true` в `backend/env/common.env`. После деплоя Alloy
   пушит на home, старый стек работает параллельно. Двойной скрейп безвреден; в этом окне возможны дубли алертов в
   Discord — это меньшее зло, чем дыра.
3. **Проверка** по §6.
4. **Переключение:**
   - снапшот TSDB Prometheus на Moscow (`/api/v1/admin/tsdb/snapshot`, admin API включён) → блоки копируются в
     Prometheus на home; пересекающиеся блоки Prometheus мерджит сам, история без разрыва;
   - A-запись `grafana.owt` → home, Traefik на home получает сертификат;
   - на Moscow `make monitoring-down`, удаление роутера `grafana-owt`.
5. Volume старого стека на Moscow (~1.5 GB) хранятся 7 дней как откат, затем удаляются по отдельному подтверждению.

**Откат:** до шага 4 — ничего не делать. После — `make monitoring-up` на Moscow и вернуть `grafana.owt`; работает,
пока volume не удалены.

## 6. Проверка

Каждый пункт — команда с ожидаемым результатом; без него шаг не закрыт.

**Шаг 1 (home):**
- `docker compose -p owt-monitoring ps` — все сервисы `healthy`.
- `ingest.owt`: с Moscow с кредами `POST /api/v1/write` → не 401/403; с другого IP → 403; с Moscow без кредов → 401;
  `GET /api/v1/query` → 404.

**Шаг 2 (Alloy):**
- Alloy `/-/ready`; все компоненты `healthy`; failed samples = 0.
- `count by (job)(up)` на home совпадает со старым Prometheus на Moscow. `rate(gateway_http_requests_total[5m])`
  расходится меньше чем на 5%.
- Все группы правил на home загружены, `lastError` пустой; RabbitMQ-правила считаются по непустым данным.
- Loki: за 5 минут есть строки каждого сервиса из `./logs`, `gateway` и `nginx`, JSON-поля разобраны.
- Tempo: ищутся трейсы gateway → service; в Sentry (проект `owt-tournaments`, Performance) появились спаны.
- `docker stats` на Moscow: `alloy` + `nginx-exporter` < 300 MB.

**Учебные тревоги** (каждая приходит в Discord и резолвится):

| Алерт | Как вызываем |
|---|---|
| `ProdTelemetryAbsent` | `docker stop` Alloy на Moscow на 4 минуты |
| `ProdHttpDown` | временная blackbox-цель с несуществующим хостом |
| `ProdSshUnresponsive` | модуль `ssh_banner` временно на `217.149.19.31:443` (TCP есть, баннера нет), затем обратно на `:22` |
| Watchdog → healthchecks.io | Alertmanager на home остановлен на 6 минут |
| `HostIOPressureHigh` | не вызываем (нельзя грузить диск прода); проверяем, что PSI-метрика приходит и выражение считается |

**Шаг 4:** в Grafana на `grafana.owt` (уже home) графики за прошлые 14 дней без дыры на склейке; на Moscow нет
контейнеров `owt-monitoring-*` и роута `grafana-owt`.

## 7. Изменения в репо

| Файл | Изменение |
|---|---|
| `docker-compose.production.yml` | `+ alloy`, `+ nginx-exporter` (профиль `telemetry`), volume `alloy-data` |
| `monitoring/alloy/moscow.alloy` | новый: метрики, логи, трейсы |
| `docker-compose.monitoring.yml` | стек home: без экспортёров и внешней сети `owt_app-network`, `+ blackbox-exporter`, порты на `127.0.0.1`, без профилей `logs`/`traces` |
| `monitoring/prometheus/prometheus.yml` | конфиг home: blackbox-джобы, свои метрики, без целей Moscow |
| `monitoring/prometheus/rules/rabbitmq.yml`, `services.yml` | метрики плагина |
| `monitoring/prometheus/rules/prod_reachability.yml` | новый: `ProdTelemetryAbsent`, `ProdHttpDown`, `ProdSshUnresponsive`, `Watchdog` |
| `monitoring/prometheus/rules/infrastructure.yml` | `+ HostIOPressureHigh` |
| `monitoring/alertmanager/alertmanager.yml` | receiver healthchecks.io, маршрут `Watchdog` |
| `monitoring/blackbox/blackbox.yml` | новый: `http_2xx`, `ssh_banner` |
| `monitoring/promtail/`, `monitoring/otel/` | удаляются: их работу делает Alloy |
| `monitoring/grafana/dashboards/` | RabbitMQ-панели «Workers & Queues» |
| `backend/env/common.env.example` | `OTLP_ENDPOINT=http://alloy:4317`, `TRACING_ENABLED=true` |
| `Makefile` | `monitoring-*` запускаются на home; `MONITORING_PROFILES` уходит |
| `monitoring/README.md` | переписывается под новую топологию |
| `docs/dev-site.md` | dev-сайт не включает профиль `telemetry` |
| `ops/deploy/remote-deploy.sh` | комментарий про недоступный Docker Hub — поправить по факту pull образа Alloy |

Вне репо: A-записи в Timeweb, `/etc/traefik/dynamic.yml` на home и Moscow, корневой `.env` и `backend/env/common.env`
на Moscow, чек healthchecks.io, секреты в `monitoring/secrets/` на home.

## 8. Риски

| Риск | Что с ним делаем |
|---|---|
| Sentry OTLP ingest — open beta; span events отбрасываются; спаны расходуют квоту Sentry | Сэмплинг 10%, как задумано для otel-collector. Если квоты не хватит — ветку Sentry в Alloy отключить, Tempo остаётся |
| Имена метрик плагина RabbitMQ не совпадают с kbudde | Сверка с живым `/metrics/per-object` до переписывания правил; проверка «правила считаются по непустым данным» (§6) |
| IP home домашний, питание и интернет домашние | A-записи правятся при смене IP, как у `dev.owt`; падение home ловит healthchecks.io |
| Образ `grafana/alloy` с Docker Hub на Moscow | `docker manifest inspect` проходит; pull проверяется на шаге 2; запасной путь — `docker save`/`docker load` через home |
| Alloy на проде привилегированный (встроенному cadvisor нужен доступ к cgroups, как сейчас у cadvisor) | Те же права, что у текущего cadvisor; порты Alloy не публикуются |
| WAL Alloy пишется на тот же деградирующий диск | Объём мал; при зависании диска Alloy висит вместе со всеми — это и ловит `ProdTelemetryAbsent` с home |
| Дубли алертов во время параллельной работы (§5 шаг 2) | Окно до переключения; осознанно лучше, чем дыра |

## 9. Не делаем

- Локальный запуск мониторинга на машине разработчика: после переезда `docker-compose.monitoring.yml` описывает стек
  home. Дашборды отлаживаются в Grafana на home.
- Объединение со стеком `prometheus`, который уже работает на home.
- Mimir / VictoriaMetrics: Prometheus справляется с 16 джобами по 30 с.
- Traefik access log с Moscow в Loki.
- Изменение retention Prometheus, Loki, Tempo.
- Устранение причины зависаний диска: это тикет в Timeweb.
