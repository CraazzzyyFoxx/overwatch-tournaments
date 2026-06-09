# Новая архитектура: Gateway + Domain Services

## Context

Текущая архитектура (6 FastAPI сервисов + 7 воркеров) имеет системную проблему: при WS-событии каждый клиент независимо делает N HTTP-запросов к разным сервисам. Во время check-in (100 клиентов × 10 запросов × N событий) это создаёт лавину запросов. Также: дублирование auth/middleware во всех сервисах, межсервисные HTTP-вызовы с overhead, сложная инвалидация кэша.

Решение: полный реврайт на тонкий Gateway (REST+WS) + domain headless сервисы на FastStream + RabbitMQ.

---

## Принятые решения

| Вопрос | Решение |
|--------|---------|
| Тип миграции | Полный реврайт |
| База данных | Shared PostgreSQL — без изменений |
| Gateway | Тонкий FastAPI (REST + WS), никакой бизнес-логики |
| Межсервисная коммуникация | FastStream + RabbitMQ (не gRPC) |
| Realtime push | Full payload с гранулярными WS-топиками |
| Инвалидация кэша | Нативная через события RabbitMQ |
| gRPC | Не используется — лишняя сложность при shared DB |

---

## Раздел 1: Топология и сервисные границы

### Финальная топология (9 контейнеров vs ~15 сейчас)

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                   │
└────────────────────────┬────────────────────────────────┘
                         │ HTTPS / WSS
┌────────────────────────▼────────────────────────────────┐
│                 GATEWAY (FastAPI)                       │
│                                                         │
│  REST routes          WS Manager         RPC Client     │
│  /api/v1/*            topic subscriptions FastStream    │
│  JWT validate (local) data push           publisher     │
│  Response assembly    cache warming       /subscriber   │
└──────────┬──────────────────────────────────────────────┘
           │
           │  RabbitMQ (FastStream)
           │  ┌─── RPC queues (request-reply)
           │  ├─── Event queues (fire-and-forget)
           │  └─── Compute queues (workers)
           │
     ┌─────┼──────────────┐
     ▼     ▼              ▼
identity  tournament    stats
  -svc      -svc         -svc
(headless)(headless)   (headless)
           │
     ┌─────┼────────────────┐
     ▼     ▼                ▼
  parser  balancer    analytics-svc
   -svc     -svc      (headless, queries)
(headless)(headless)
                            ▼
                    analytics-worker
                    (GPU, отдельный)
                    discord-service
                    (discord.py, без изменений)
```

### Границы доменов

**`identity-svc`** (headless FastStream)
- Users, profiles, avatar uploads
- Workspace membership и роли
- RBAC permissions
- OAuth / Discord интеграция (auth часть)

**`tournament-svc`** (headless FastStream)
- Tournaments, stages, seeding
- Brackets, encounters, match results
- Standings, rankings
- Registrations, check-in, sub-roles
- Computation: bracket generation + standings recalculation (поглощает bracket-worker и standings-worker)

**`stats-svc`** (headless FastStream)
- Hero playtime per player/tournament
- Achievements (templates + evaluate — поглощает achievement eval)
- Player statistics, aggregations
- Analytics queries (ML results consumption)

**`parser-svc`** (headless FastStream)
- Match log processing (поглощает parser-worker)
- Rank fetching (поглощает rank_fetch worker)
- Challonge/tournament log parsing

**`balancer-svc`** (headless FastStream)
- Team balancing algorithm (поглощает balancer-worker)
- Balancing job management

**`analytics-svc`** (headless FastStream — queries only)
- Чтение ML-результатов, запросы к analytics данным

**`analytics-worker`** (остаётся отдельным)
- GPU training/inference — отдельная resource policy, docker-compose.gpu.yml

**`discord-service`** (остаётся отдельным)
- discord.py, long-running bot, другой фреймворк

### RabbitMQ очереди

```
RPC (request-reply, gateway ↔ services):
  rpc.identity.{method}       — get_user, get_workspace_members, ...
  rpc.tournament.{method}     — get_tournament, get_bracket, get_standings, ...
  rpc.stats.{method}          — get_hero_playtime, get_achievements, ...
  rpc.parser.{method}         — trigger_parse, get_parse_status, ...
  rpc.balancer.{method}       — create_balance_job, get_result, ...

Events (fire-and-forget, services → gateway):
  events.tournament.updated           — { tournament_id, reason, actor_user_id }
  events.tournament.encounter.completed
  events.registration.approved

Compute (внутри сервисов, бывшие отдельные воркеры):
  compute.bracket             — внутри tournament-svc
  compute.standings           — внутри tournament-svc
  compute.parser.match_log    — внутри parser-svc
  compute.rank_fetch          — внутри parser-svc
  compute.balancer.job        — внутри balancer-svc
  compute.analytics.*         — analytics-worker (GPU, отдельный)
```

---

## Раздел 2: Gateway и Realtime flow

### Структура Gateway

```
gateway/
├── main.py
├── core/
│   ├── auth.py          — JWT decode (local, shared secret)
│   ├── rpc.py           — FastStream RPC client (publish + await reply)
│   └── cache.py         — Cashews setup + invalidation helpers
├── realtime/
│   ├── manager.py       — WS connection registry + topic subscriptions
│   ├── push.py          — data push по топикам
│   └── consumers.py     — FastStream subscribers на events.*
├── routes/
│   ├── tournament.py    — /api/v1/tournaments/*
│   ├── identity.py      — /api/v1/users/*, /api/v1/workspaces/*
│   ├── stats.py         — /api/v1/standings/*, /api/v1/heroes/*
│   └── ws.py            — /ws endpoint
└── schemas/             — Pydantic response schemas (только для gateway)
```

Gateway не имеет `models/` и `repositories/` — только routes, RPC-вызовы и сборка ответов.

### RPC паттерн (gateway → service)

```python
# core/rpc.py
async def call(queue: str, payload: BaseModel, timeout: float = 5.0) -> dict:
    return await broker.publish(
        payload,
        queue=queue,
        rpc=True,
        rpc_timeout=timeout,
    )

# routes/tournament.py
@router.get("/tournaments/{id}")
@cache(ttl=timedelta(seconds=30), key="tournament:{id}")
async def get_tournament(id: int, user=Depends(jwt_user)):
    return await rpc.call("rpc.tournament.get_tournament", GetTournamentRequest(id=id))
```

### Realtime flow (полная цепочка)

```
1. tournament-svc делает запись в DB
         ↓
2. publishes → events.tournament.updated
   { tournament_id: 42, reason: "structure_changed" }
         ↓
3. Gateway consumer получает событие
         ↓
4. Gateway инвалидирует кэш:
   await cache.invalidate("tournament:42:*")
         ↓
5. Gateway делает ONE RPC-вызов:
   snapshot = await rpc.call(
       "rpc.tournament.get_snapshot",
       GetSnapshotRequest(id=42, reason="structure_changed")
   )
         ↓
6. Gateway кладёт snapshot в кэш (cache warming)
         ↓
7. Gateway пушит snapshot ВСЕМ WS-подписчикам топика:
   await ws_manager.push("tournament:42:registrations", snapshot.registrations)
   await ws_manager.push("tournament:42:standings", snapshot.standings)
         ↓
8. Клиент получает готовые данные → обновляет React Query cache напрямую
   queryClient.setQueryData(["tournament", 42, "registrations"], data)
   — ZERO дополнительных HTTP-запросов
```

### Гранулярные WS-топики

Клиент подписывается только на нужный для текущей страницы:

| Страница | Топик | Payload |
|---|---|---|
| `/participants` | `tournament:42:registrations` | список регистраций + статусы check-in |
| `/bracket` | `tournament:42:bracket` | encounters + seeds |
| `/standings` | `tournament:42:standings` | таблица standings |
| `/teams` | `tournament:42:teams` | список команд |

---

## Раздел 3: Cache Strategy

### Два уровня кэша

**Уровень 1 — Gateway response cache (Cashews + Redis)**

Кэширует собранные REST-ответы. Инвалидация через RabbitMQ события:

```python
# realtime/consumers.py
@broker.subscriber("events.tournament.updated")
async def on_tournament_updated(event: TournamentUpdatedEvent):
    await cache.invalidate(f"tournament:{event.tournament_id}:*")
    snapshot = await rpc.call("rpc.tournament.get_snapshot", ...)
    await cache.set(f"tournament:{event.tournament_id}:snapshot", snapshot)
    await ws_manager.push_snapshot(event.tournament_id, snapshot)
```

**Уровень 2 — Service query cache (Cashews внутри каждого сервиса)**

Кэширует тяжёлые DB-запросы внутри domain сервисов. Инвалидируется сервисом самостоятельно при записи:

```python
# tournament-svc/handlers/tournament.py
@broker.subscriber("rpc.tournament.get_standings")
@cache(ttl=timedelta(seconds=60), key="standings:{msg.tournament_id}")
async def get_standings(msg: GetStandingsRequest) -> StandingsResponse:
    return await standings_repo.fetch(msg.tournament_id)

# При записи — сервис сам инвалидирует свой кэш
async def update_standings(...):
    await repo.save(...)
    await cache.invalidate(f"standings:{tournament_id}:*")
    await broker.publish(TournamentUpdatedEvent(...), "events.tournament.updated")
```

### TTL по типу данных

| Данные | Gateway TTL | Service TTL |
|---|---|---|
| Tournament metadata | 60s | 120s |
| Registrations / check-in | 15s | 30s |
| Bracket / encounters | 30s | 60s |
| Standings | 30s | 60s |
| Hero playtime | 120s | 300s |
| User profiles | 300s | 600s |

TTL — только fallback. Основная инвалидация — через события.

---

## Раздел 4: Migration Path

Полный реврайт, но поэтапный — в каждый момент система рабочая.

### Фаза 0 — Подготовка (не ломает ничего)
- Создать `gateway` сервис поверх текущих сервисов (просто проксирует через Kong)
- Перенести JWT валидацию из каждого сервиса в gateway middleware
- Добавить гранулярные WS-топики в текущий `realtime-service`
- Добавить full payload push в `realtime-service` (текущая архитектура, но уже решает fan-out)

### Фаза 1 — identity-svc (наименее связанный домен)
- Создать `identity-svc` (headless FastStream)
- Перенести: users, profiles, workspace membership, RBAC
- Gateway переключается с HTTP на RPC для `/api/v1/users/*`
- Старый `app-service` (users часть) — деактивировать

### Фаза 2 — tournament-svc (ядро системы)
- Создать `tournament-svc` (headless FastStream)
- Поглотить: `tournament-service` + `bracket-worker` + `standings-worker`
- Gateway переключается на RPC для `/api/v1/tournaments/*`
- Realtime consumer переезжает в gateway (вместо отдельного `realtime-service`)

### Фаза 3 — stats-svc + parser-svc + balancer-svc
- Параллельно или последовательно
- Каждый поглощает свои воркеры
- `analytics-worker` и `discord-service` — без изменений

### Фаза 4 — Cleanup
- Удалить `realtime-service` (поглощён gateway)
- Удалить старые FastAPI сервисы
- Удалить Kong (gateway теперь единственная точка входа)
- Обновить `docker-compose.yml`

---

## Verification

После каждой фазы:

1. **RPC latency** — `rtk curl /api/v1/tournaments/{id}` должен отвечать < 100ms
2. **WS push** — открыть две вкладки турнира, сделать check-in → обе получают обновление без HTTP-запросов (проверить Network tab: 0 XHR после WS события)
3. **Cache** — повторный запрос к gateway должен возвращать из кэша (проверить Redis: `KEYS tournament:*`)
4. **Workers** — запустить парсинг матча → standings пересчитываются → WS push клиентам
5. **Load test** — 100 WS-клиентов на одном турнире, сделать 10 check-in подряд → бэкенд делает 10 RPC-вызовов, не 1000 HTTP-запросов
