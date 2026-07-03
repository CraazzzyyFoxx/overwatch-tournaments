# RPC-контур: защита от снежной лавины (TTL + deadline + prefetch + bulkhead)

**Дата:** 2026-07-04
**Статус:** approved (design)
**Ветка реализации:** `feature/rpc-backpressure`

## Проблема

Весь трафик `/api/*` идёт через Go-gateway → RabbitMQ RPC (`rpc.<svc>.<endpoint>`-очереди)
→ FastStream-воркеры. Под пиковой нагрузкой контур сваливается в лавину:

1. Gateway публикует запрос **без TTL** (`gateway/internal/rpc/rpc.go` — `amqp.Publishing`
   без `Expiration`) и ждёт ответ до 120s (`edge/dispatch.go: rpcTimeout`).
2. По истечении таймаута клиент получает 504, **но сообщение остаётся в очереди навсегда**.
3. Воркеры потребляют без QoS-лимита (`make_rabbit_broker` не задаёт `prefetch_count`
   → aio-pika qos=0, безлимит): под пиком воркер набирает неограниченно много сообщений,
   конкурентная обработка исчерпывает пул БД, латентность каждого запроса растёт.
4. Воркеры тратят БД/CPU на «мёртвые» запросы, чьи клиенты уже получили 504; клиенты
   ретраят → очередь растёт быстрее, чем разгребается → положительная обратная связь
   («снежная лавина»). Ответ на протухший запрос gateway молча выбрасывает (нет waiter'а
   по correlation_id), т.е. вся работа воркера — впустую.

## Цель

Разорвать петлю обратной связи тремя независимыми слоями:

1. протухшие запросы удаляются самим брокером (TTL);
2. воркер не платит за мёртвые запросы (deadline-drop) и не захлёбывается (prefetch);
3. при перегрузке gateway отвечает мгновенным 503 вместо 120-секундного зависания (bulkhead).

### Вне области (Non-goals)

- `x-max-length` + publisher confirms: требует redeclare очередей и confirm-режима в
  Go-клиенте; gateway — единственный паблишер `rpc.*`, его bulkhead даёт тот же
  эффект дешевле.
- Circuit breaker: YAGNI — bulkhead + TTL уже рвут петлю.
- Снижение `rpcTimeout` 120s: осознанно оставлен для легитимных медленных reads
  (hero stats на холодном кэше и т.п.).
- Фоновые job-очереди (balancer jobs, bracket/standings, match-log, analytics train):
  у них нет ждущего клиента — TTL/deadline к ним не применяются. Их касается только
  изоляция каналов (см. §4).

## Решение

### 1. Gateway: per-message TTL + заголовок дедлайна

В `rpc.Client.Call` (`gateway/internal/rpc/rpc.go`) из `ctx.Deadline()` вычисляется
остаток бюджета и проставляется на публикуемое сообщение:

- `Publishing.Expiration` = остаток в миллисекундах (per-message TTL). RabbitMQ
  удаляет истёкшие сообщения из головы очереди; так как TTL всех RPC-сообщений
  задаётся одной формулой (остаток дедлайна), FIFO-порядок совпадает с порядком
  истечения и head-of-queue-семантика per-message TTL корректна.
- Заголовок `x-deadline-ms` = абсолютное unix-время дедлайна в мс (int64) — для
  проверки на стороне воркера (покрывает сообщения, уже prefetch-нутые консьюмером,
  на которые TTL не действует).

Если у ctx нет дедлайна — ничего не проставляется (сегодня дедлайн есть у всех
вызовов: edge 120s, binary, identity validate). Аргументы очередей не меняются,
redeclare не нужен; DLQ у `rpc.*` нет, истёкшие сообщения просто удаляются.

### 2. Gateway: bulkhead (fail-fast 503)

В `rpc.Client` — пер-queue счётчик in-flight вызовов:

- лимит из env `GATEWAY_RPC_MAX_INFLIGHT` (дефолт **64**, `0` = отключено);
- при превышении `Call` немедленно возвращает новый sentinel-error `ErrOverloaded`
  (без публикации в очередь);
- `edge/dispatch.go` и binary/identity-хендлеры мапят `ErrOverloaded` →
  `503 Service Unavailable` + `Retry-After: 1` (рядом с существующим мапингом
  `ErrNotConnected`/`ErrDisconnected` → 503);
- слот освобождается по завершении `Call` любым путём (ответ/таймаут/дисконнект).

Гранулярность per-queue — это bulkhead: один захлебнувшийся эндпоинт не утаскивает
остальные, и лимит одновременно ограничивает вклад gateway в глубину каждой очереди.

### 3. Воркеры: deadline-drop middleware

Новый модуль `backend/shared/rpc/deadline.py` — FastStream-middleware
(`BaseMiddleware.consume_scope`):

- читает `x-deadline-ms` из заголовков сообщения;
- заголовка нет (фоновые события, discord и т.п.) → пропустить без изменений;
- дедлайн прошёл (со слабиной **500 мс** на clock skew) → **не вызывать** хендлер:
  ack, WARNING-лог (queue + величина просрочки), инкремент метрики;
- дедлайн не прошёл → обычная обработка. Сообщение, истёкшее **во время** обработки,
  не прерывается (работа уже оплачена, откат дороже).

Ответ на дропнутый запрос не публикуется в reply-очередь либо публикуется как
`null`-заглушка — клиент уже отвалился, gateway молча выбрасывает поздние ответы;
точный способ короткого замыкания (return без call_next vs `AckMessage`) выбирается
в реализации по фактическому поведению FastStream 0.6 reply-пути.

Подключение — внутри `make_rabbit_broker` (`backend/shared/observability/broker.py`),
одна точка для всех шести энтрипойнтов (app-svc, tournament-worker, parser,
balancer-worker, analytics-svc + analytics-worker, identity-svc).

### 4. Воркеры: ограничение конкурентности (QoS prefetch)

- `make_rabbit_broker` получает параметр `prefetch_count` (env `RPC_PREFETCH_COUNT`
  через настройки сервиса, дефолт **16**) →
  `RabbitBroker(default_channel=Channel(prefetch_count=N), ...)`.
- Бэклог остаётся в очереди RabbitMQ (где работает TTL), а не в буфере консьюмера;
  конкурентная обработка на процесс ограничена N — пул БД не исчерпывается.
- Долгоживущие фоновые консьюмеры, живущие в одном процессе с RPC (balancer jobs;
  tournament bracket/standings jobs; parser match-log/rank-fetch; app
  tournament_changed; analytics job/train/infer), получают **свой**
  `channel=Channel(prefetch_count=<малый, 1–4>)` на сабскрайбере — чтобы минутные
  джобы не занимали слоты RPC-канала и наоборот.

### 5. Наблюдаемость

- Gateway (существующий Prometheus на :9110): counter
  `gateway_rpc_shed_total{queue}` — отказы bulkhead.
- Воркеры (существующий worker-metrics-порт): counter
  `rpc_stale_dropped_total{queue}` + WARNING-лог на каждый дроп.

## Краевые случаи

- **Clock skew** gateway↔воркер: контейнеры на одном хосте; слабина 500 мс в
  middleware исключает ложные дропы.
- **ctx без дедлайна**: TTL/заголовок не проставляются — поведение как сегодня.
- **Сообщения без `x-deadline-ms`**: проходят без изменений (обратная совместимость,
  смешанные версии при выкатке безопасны: старый gateway + новый воркер и наоборот).
- **Reply-очередь**: не трогаем — она exclusive/auto-delete, переполнения нет.

## Тесты

- Go (`gateway/internal/rpc`, `gateway/internal/edge`):
  - `Expiration` и `x-deadline-ms` выставляются из ctx-дедлайна; отсутствие дедлайна
    → не выставляются;
  - bulkhead: отказ на лимите, освобождение слота после завершения, `0` = выключен;
  - dispatch мапит `ErrOverloaded` → 503 + Retry-After.
- Python (`backend/shared` тесты):
  - middleware: просроченный → хендлер не вызван, ack, метрика; свежий → проходит;
    без заголовка → проходит; слабина 500 мс соблюдается;
  - `make_rabbit_broker`: `prefetch_count` прокидывается в `default_channel`.

## Выкатка

Изменения не трогают аргументы очередей → без миграций/redeclare. Порядок деплоя
свободный (заголовок опционален с обеих сторон): практично — сначала воркеры
(middleware+prefetch), затем gateway (TTL+bulkhead). Тюнинг лимитов
(`GATEWAY_RPC_MAX_INFLIGHT`, `RPC_PREFETCH_COUNT`) — через env без пересборки.
