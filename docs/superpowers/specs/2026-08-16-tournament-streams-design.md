# Tournament Streams (stream-service) — Design

**Status:** implemented (2026-08-16)
**Plan:** `docs/superpowers/plans/2026-08-16-tournament-streams.md`
**Закрывает:** issue #104 «Live stream embeds (Twitch / YouTube)», issue #99 «Tournament links block» (частично — таблица `tournament_link` вводится здесь)
**Опирается на:** `2026-08-05-workspace-subscription-requirement-design.md` (тот же приём: чужую логику не переписываем, добавляем шов), `2026-08-12-platform-audit-log-design.md` (§1 — доменные журналы живут отдельно от `audit_log`)

---

## 1. Understanding Summary

- **Что.** Новый headless RPC-воркер `stream-service` (compose `stream-svc`), который раз в интервал опрашивает Twitch Helix `GET /streams` под app access token и отдаёт публичный ответ «кто сейчас в эфире» для турнира: официальная трансляция организатора + стримы зарегистрированных участников. Плюс типизированная таблица `tournament.tournament_link`, где ссылка на трансляцию — один из типов.
- **Зачем.** Удержать зрителя на платформе во время ивента (формулировка #104). Сейчас у турнира нет ни одного поля со ссылкой на стрим — организатор кладёт её в описание текстом.
- **Для кого.** Анонимные зрители публичной страницы турнира (основной потребитель), организаторы (CRUD ссылок), участники (opt-in своего канала).
- **Ограничения.** Воркеры headless — только RPC поверх RabbitMQ; внешние API — через `proxy`-сайдкар; multitenancy по `workspace_id`; realtime — только через Redis-топики, реле делает gateway; типизированные строки вместо JSON-помоек (конвенция #99).
- **Не-цели.** Запись/хранение VOD, релей чата, аналитика просмотров, монетизация, live-детект YouTube, EventSub-подписки, история «кто стримил» как отчёт.

Зафиксированные пользователем решения (ask, 2026-08-16): объём = официальная трансляция **+** автоподхват стримов участников; детект = **polling** Helix `GET /streams` app token; платформы = **Twitch — live-статус, YouTube/прочие — только ссылка+эмбед**; граница = **новый `stream-service`**; ссылки = **через `tournament_link` из #99**.

## 2. Current State (verified)

### 2.1 Что уже есть и переиспользуется целиком

| Возможность | Где | Следствие |
| --- | --- | --- |
| `SocialProvider.TWITCH` / `YOUTUBE`, `is_verified` через OAuth, стабильный `provider_user_id` | `backend/shared/core/social.py:27,30,45`; `backend/shared/models/identity/social.py:62-69` | реестр каналов участников заводить не надо |
| Twitch OAuth (client id/secret, Helix base) | `backend/identity-service/src/core/config.py:68-74`; `.../services/oauth_service.py:180-260` | приложение Twitch уже зарегистрировано, креды в `backend/env/auth.env` |
| Таксономия ошибок Helix (`HelixNotFound/MissingScope/NotConfigured/Forbidden/Unavailable`) | `backend/shared/subscriptions/providers/twitch_helix.py:50-76` | форму ошибок копируем; сам клиент нет — он под **user** token и `GET /subscriptions/user` |
| **`registration.twitch_nick` + `registration.stream_pov`** | `backend/shared/models/registration/registration.py:172,174`; миграция `initial_v6.py:1888,1890`; публичность — `tournament-service/tests/test_reg_to_read_privacy.py:43` | **самозаявленный per-tournament канал с явным opt-in уже существует.** Это основной источник каналов участников |
| APScheduler + Redis leader-lock + settings-гейт | `backend/parser-service/src/services/subscription_collection/scheduler.py:6-12,41-92,113-128`; `backend/shared/services/distributed_lock.py:36-62` | шаблон тика 1:1 |
| Resilient httpx + circuit breaker + egress через `proxy` | `backend/shared/clients/http_client.py`; `backend/shared/core/config.py:134` (`proxy_url` → `socks5://proxy:1080`) | Helix-клиент — тонкая обёртка |
| Публикация realtime (durable / non-durable) | `backend/shared/services/realtime_publisher.py:40-50,77-112`; non-durable образец `backend/shared/services/subscription_realtime.py:66-79` (`event_id=0`, минуя БД) | сигнал о смене эфира — non-durable |
| Live-индикатор, Twitch как провайдер, бейдж, контракт состояний публичной страницы | `frontend/src/app/globals.css:2071-2109` (`.status-pill.live` + `.dot`); `frontend/src/lib/social/providers.ts` (twitch: #9146FF, иконка, `profileUrl`); `frontend/src/components/social/SocialAccountBadge.tsx`; `_views/publicPageQueryPresentation.ts` | нового UI-примитива не пишем |
| Generic админ-CRUD дочерней сущности турнира + бесплатный аудит | `backend/tournament-service/src/services/admin/registry.py:304-321` (`player_sub_role`); `backend/shared/rpc/crud.py:193-232` | `tournament_link` не требует ни одной новой RPC-очереди |

### 2.2 Чего нет (проверено)

- **`tournament_link` не существует** — grep по `backend/shared` даёт ноль. Схемы `streams` тоже нет.
- **App access token (`grant_type=client_credentials`) в репозитории не реализован** — весь Twitch-код работает под пользовательским токеном.
- **CSP/X-Frame-Options/Permissions-Policy отсутствуют полностью**: ни `async headers()` в `frontend/next.config.mjs`, ни одной `add_header` в `nginx/nginx.conf` (356 строк), ни `traefik.*`-лейблов в `docker-compose.production.yml`. Twitch-iframe **не блокируется — блокировать нечему**. iframe в проекте вообще нет ни одного (grep по `frontend/` → 0) — плеер будет первым.
- **`respcache` жёстко турнирный**: `gateway/internal/respcache/respcache.go:425-432` принимает только топики `tournament:{id}:bracket|draft`, индекс инвалидации ключуется `tournament_id`, а `TTLOnly()` кладёт записи под `id=0`, недостижимые для `Invalidate` (`respcache.go:118-128`).
- **ACL WS-топиков — allowlist с deny-by-default**: `gateway/internal/acl/acl.go:80-103`. `workspace:*:*` покрыт правилом :87, `tournament:{id}:streams` — **нет**.
- **Мёртвые ссылки на несуществующий `twitch-service`** — ровно два места: `backend/pyrightconfig.json:13` и `backend/analytics-worker.gpu.Dockerfile:51` (файл вообще сломан — там же `auth-service:45` и `realtime-service:47`, которых тоже нет). В compose, Makefile, CI, gateway, monitoring — чисто.
- Свободный `WORKER_METRICS_PORT`: занято 9100/9103/9106/9107/9108/9109, gateway на 9110 → берём **9111**.

### 2.3 Фактический масштаб

Фикстур с реальными числами в репо нет. Зафиксированный потолок публичных страниц — `docs/superpowers/specs/2026-07-15-tournament-public-pages-ux-performance-design.md:32`: «supported up to 500 registrations, 64 teams, and 8 stages». Реальный пример там же (:24): турнир 72 — 128 регистраций, 20 команд. Сколько игроков имеют Twitch-аккаунт — данных нет.

## 3. Assumptions

| # | Допущение | Статус |
| --- | --- | --- |
| A1 | Задержка live-бейджа до `interval + TTL кэша` (по умолчанию 60 + 30 = 90 с) на **холодной** загрузке приемлема; на открытой странице WS-сигнал даёт обновление в пределах интервала | подтверждено ask (polling выбран сознательно) |
| A2 | 500 логинов на турнир → ≤5 запросов Helix за тик. Бюджет app-бакета — 800 points/min, 1 point за запрос (`https://dev.twitch.tv/docs/api/guide/`) → лимит не является ограничением до ~150 одновременных турниров | выведено из документации Twitch + потолка 2.3 |
| A3 | Канал участника публикуется **только** при явном согласии: `stream_pov = true` (per-tournament opt-in) либо verified Twitch-аккаунт с глобальной строкой видимости | вытекает из `visible_only` (см. 4.5) |
| A4 | YouTube нужен как ссылка/эмбед; live-детект YouTube не нужен (`search.list` = 100 quota units из 10k/сутки) | подтверждено ask |
| A5 | Live-статус — эфемерные данные: устаревший статус хуже отсутствующего | принято в этом дизайне, см. Decision D2 |

## 4. Design

### 4.1 Данные: `tournament_link` — единственная новая таблица

Владелец записи — **tournament-service** (`backend/docs/tournament-service-write-path-inventory.md`: все `tournament.*` за ним). Шаблон — `PlayerSubRole` (`backend/shared/models/tournament/team.py:125-151`), а не `TournamentPhaseSchedule` (тот full-replace, без `sort_order`, без аудита).

```python
# backend/shared/models/tournament/link.py
class TournamentLink(db.TimeStampIntegerMixin):
    __tablename__ = "tournament_link"
    __table_args__ = (
        UniqueConstraint("tournament_id", "kind", "url", name="uq_tournament_link_tournament_kind_url"),
        Index("ix_tournament_link_tournament_active", "tournament_id", "is_active"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)   # discord|stream|vod|bracket|rules|other
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)
```

`kind` — `String(32)` с валидацией в Pydantic-схеме, не PG enum: расширение набора типов не должно требовать миграции (тот же выбор, что `Tournament.team_formation`, `tournament.py:51`).

Админ-контур целиком декларативный, **новых RPC-очередей нет**:

| Шаг | Файл | Образец |
| --- | --- | --- |
| схемы Read/Create/Update | `backend/tournament-service/src/schemas/admin/tournament_link.py` | `schemas/admin/player_sub_role.py:1-38` |
| сервис (list с `sort_order`, конфликт → 409, soft-delete `is_active=False`) | `backend/tournament-service/src/services/admin/tournament_link.py` | `services/admin/player_sub_role.py:31-145` |
| транзитивный резолвер воркспейса | `backend/tournament-service/src/core/auth.py` | `get_tournament_workspace_id:36-39` |
| `EntityConfig` в реестре | `backend/tournament-service/src/services/admin/registry.py` | блок `player_sub_role`:304-321, `resolve_ws_for_create=_ws_via_tournament_body` |
| 4 роута | `gateway/internal/tournament/admin_routes.go` | :39-43 (GET list / POST 201 / PATCH / DELETE 204) |

В `parser-service` **не** дублировать — это зеркало, реестр в `2026-08-04-code-mirrors-registry.md`. Аудит `tournament_link.{create,update,delete}` приезжает бесплатно через `CrudDispatcher._audit` (`shared/rpc/crud.py:216-232`) с тем же `workspace_id`, что проверял `ensure_workspace_permission`, и `ip_address`/`user_agent` из конверта gateway.

Публичное чтение ссылок — расширением существующего overview через `entities`, а не новым эндпоинтом (конвенция `frontend/src/services/tournament.service.ts:93-105`): `entities: ["links"]`.

### 4.2 Состояние live — Redis, без своей схемы Postgres

`streams` как Postgres-схема **не заводится**. Обоснование — Decision D2; следствие: не нужны миграция, `CREATE SCHEMA`, запись в кортеж `SCHEMAS` (`initial_v6.py:27-40`), регистрация в `shared/models/__init__.py`, репозиторий, правка `SCAN_ROOTS` в `backend/tests/test_repository_boundaries.py` и новый тест «сервис пишет только в свои схемы».

Ключи (владелец — `stream-service`, все с TTL):

```
stream:live:{tournament_id}   HASH  field=<platform>:<channel>  value=<json snapshot>   TTL = 3 × interval
stream:token                  STR   app access token                                   TTL = expires_in − 60
stream:poll:last_run          STR   unix ts последнего успешного тика                   TTL = 24h
```

Снапшот канала — ровно то, что рисует UI: `{platform, channel, url, live, title, game_name, viewer_count, thumbnail_url, started_at}` плюс `player_id` для участников. Пропавший из ответа Helix канал = offline: `GET /streams` возвращает **только** живые каналы.

### 4.3 Поллер

Форма — 1:1 `subscription_collection/scheduler.py`: APScheduler UTC, `max_instances=1, coalesce=True`, фиксированный heartbeat **30 с**, а «пора ли» решается **внутри** тика по `stream:poll:last_run + interval_seconds`. Причина ровно та, что в докстринге образца (:6-12): интервал admin-editable, и шедулер, прибитый к стартовому значению, сделал бы отображаемое число ложью. Между репликами — Redis leader-lock (`shared/services/distributed_lock.py:36-62`, TTL = 2 × heartbeat). Обёртка `observe_scheduled_job`.

Настройка — три точки в `backend/shared/schemas/settings.py` (ключ-константа, модель, `SETTINGS_SCHEMAS`) + аксессор в `settings_provider.py:92-99`:

```python
SETTINGS_KEY_STREAM_COLLECTION = "stream.collection"

class StreamCollectionConfig(BaseModel):
    enabled: bool = False                                            # безопасный дефолт, как RankCollectionConfig:41-46
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    batch_size: int = Field(default=100, ge=1, le=100)               # 100 = потолок Helix GET /streams
```

Гейт первой строкой тика: `if not cfg.enabled: return 0`. Запись настройки уже работает — `parser-service/src/services/admin/settings.py:49-62` подхватит новый ключ сам.

**Шаг 1 — какие турниры.** `status IN ('check_in', 'draft', 'live', 'playoffs')`. `check_in`/`draft` включены сознательно: официальная трансляция стартует до первой карты. `completed`/`archived` — никогда (`_FINISHED_STATUSES`, `shared/core/tournament_state.py`). Опираемся на `status`, а не на `Tournament.is_finished` — второй не синхронизируется автоматически.

**Шаг 2 — какие каналы.** Три независимых источника, объединяются по `(platform, channel)`:

```sql
-- (1) официальная трансляция
SELECT url FROM tournament.tournament_link
WHERE tournament_id = :tid AND kind = 'stream' AND is_active;

-- (2) самозаявленный канал участника с явным opt-in
SELECT r.twitch_nick, wm.player_id
FROM balancer.registration r
JOIN workspace_member wm ON wm.id = r.workspace_member_id
WHERE r.tournament_id = :tid AND r.deleted_at IS NULL
  AND r.status = 'approved' AND r.stream_pov IS TRUE
  AND r.twitch_nick IS NOT NULL;

-- (3) verified Twitch-аккаунт, публичный на профиле
SELECT sa.username_normalized, sa.provider_user_id, u.id AS player_id
FROM balancer.registration r
JOIN workspace_member wm       ON wm.id = r.workspace_member_id
JOIN players."user" u          ON u.id = wm.player_id
JOIN players.social_account sa ON sa.user_id = u.id
JOIN players.social_account_visibility v
       ON v.account_id = sa.id AND v.workspace_id IS NULL          -- глобально видим
WHERE r.tournament_id = :tid AND r.deleted_at IS NULL AND r.status = 'approved'
  AND sa.provider = 'twitch' AND sa.is_verified IS TRUE;
```

Образец пути «турнир → участники» — `parser-service/src/services/subscription_collection/service.py:114-135`, дословно тот же набор JOIN.

**Шаг 3 — опрос.** Батчи ≤ `batch_size`, параметры **повторяются**, не через запятую: `?user_login=a&user_login=b` (`https://dev.twitch.tv/docs/api/guide/`, «Specifying multiple query parameter values»). Для источника (3) предпочтителен `user_id=<provider_user_id>` — он стабилен при переименовании канала, чего `user_login` не гарантирует (см. Risks). Токен — `POST https://id.twitch.tv/oauth2/token`, `grant_type=client_credentials`; кэш в Redis, инвалидация на 401. Rate-limit: читаем `Ratelimit-Remaining`, при < 100 пропускаем остаток тика; на 429 спим до `Ratelimit-Reset`. Egress — `settings.proxy_url`, как OverFast.

**Шаг 4 — диff и публикация.** Сравниваем новый набор live-каналов со `stream:live:{tid}`. Если множество изменилось — перезаписываем хеш и публикуем **один** сигнал на турнир (не на канал):

```python
# non-durable: без строки в realtime.workspace_event, образец subscription_realtime.py:66-79
envelope = WorkspaceEventEnvelope(
    event_id=0, event_type="stream.updated", schema_version=1,
    occurred_at=datetime.now(UTC), actor_user_id=None,
    data={"tournament_id": tid, "live_count": len(live)},
)
await publish_envelope_to_redis(redis, topic=realtime_topics.streams(tid), envelope=envelope)
```

Non-durable потому же, почему `logs.updated` и `subscription.updated`: переподключившийся клиент всё равно рефетчит, а `replay` при первом subscribe вырождается в live-only (`gateway/internal/replay/replay.go:59-61`). Скрытый турнир (`is_hidden`) опрашиваем, но **в публичный топик не публикуем** и публично не отдаём.

### 4.4 Чтение: RPC + gateway

```go
// gateway/internal/stream/routes.go — образец internal/analytics/routes.go:20-57
var PublicRoutes = []edge.RouteSpec{
    {Method: "GET", Pattern: "/api/streams/tournament/{tournament_id}", Queue: "rpc.stream.tournament_streams",
     Path: []string{"tournament_id"}, AllQuery: true, Auth: edge.AuthNone},
}
var AdminRoutes = []edge.RouteSpec{
    {Method: "POST", Pattern: "/api/streams/tournament/{tournament_id}/repoll", Queue: "rpc.stream.repoll",
     Path: []string{"tournament_id"}, Query: []string{"workspace_id"}, Auth: edge.AuthRequired, Success: 202},
}
```

Ответ `tournament_streams`: `{official: StreamEntry[], participants: StreamEntry[]}`. Публичный хендлер обязан вызвать `assert_tournament_viewable` **до** чтения (`shared/services/tournament_visibility.py` — правило модуля: кэшируемые публичные сериализаторы читают без зрителя, поэтому проверка стоит раньше).

Обязательные правки gateway (иначе домен молча уедет в катч-олл `/` и получится петля gateway↔frontend):

1. `gateway/cmd/gateway/main.go` — импорт + три строки регистрации рядом с :293-295; guard-блок `/api/streams/` по образцу :360-368.
2. `frontend/next.config.mjs` — rewrite `/api/streams/*` → gateway.
3. `gateway/internal/edge/apiv1_guard_test.go` — третий `buildStreamsGuardedMux` по образцу :40-95 + тест «роуты зарегистрированы» (:130-160). Без него новый префикс — мёртвый код без ошибки компиляции.
4. `gateway/internal/apidocs/groups.go` — группы public/admin (:60-61, :86-87).
5. `gateway/internal/acl/acl.go:82-87` — **одна строка**: `r.register("tournament:*:streams", r.allowSpectateTournament)`. Без неё анонимный зритель не подпишется (deny-by-default, :97-103). Резолвер выбран не случайно: `allowSpectateTournament` — это ровно «public unless hidden» (комментарии :82-83), то есть гейтинг скрытых турниров на подписке приезжает бесплатно.
6. `backend/scripts/export_openapi_schemas.sh:39` — `stream-service` в массив `services`.

В `gateway/internal/rpc/*` — **ничего**: имена очередей нигде не регистрируются, `GATEWAY_RPC_MAX_INFLIGHT` применяется к любой новой очереди автоматически (`limiter.go:7-32`).

**Кэш.** Правило `{Extract: respcache.TTLOnly()}` — записи под `id=0`, живут строго по `GATEWAY_RESPONSE_CACHE_TTL` (30 с), инвалидации нет. Осознанный потолок: смена эфира видна на холодной загрузке через ≤30 с. Альтернатива (`FromQuery("tournament_id")` + публикация на `tournament:{id}:bracket` + новый `case "stream_changed"` в `respcache.go:376` + `_normalize_reason`) стоит трёх файлов в двух языках и покупает секунды на пути, где WS-сигнал уже даёт мгновенность открытым страницам. Не берём.

### 4.5 Приватность — жёсткое требование, не удобство

Публичный ответ содержит канал участника **только** если выполняется одно из:
- `registration.stream_pov = true` и `registration.twitch_nick` заполнен — явный per-tournament opt-in;
- у `social_account` (`provider='twitch'`, `is_verified=true`) **есть** строка `social_account_visibility` с `workspace_id IS NULL`.

Публикация скрытого аккаунта — это обход `visible_only` (`backend/app-service/src/services/user/flows.py:116-143`, все публичные чтения передают `visible_only=True`). Опрашивать Helix для скрытых можно (внутренние данные), отдавать наружу — нет. Проверка живёт в SQL (JOIN на `social_account_visibility`), а не в сериализаторе: фильтр, который легко забыть в новом код-пути, должен быть частью выборки.

### 4.6 RBAC и аудит

`backend/shared/rbac/catalog.py` после `*_crud("asset")` (:65):

```python
*_crud("tournament_link"),
_permission("stream", "read", "Read stream live-status and polling health"),
_permission("stream", "update", "Trigger a stream live-status re-poll"),
```

Миграция не нужна — `ensure_permission_catalog` (`bootstrap.py:13-36`) идемпотентно апсертит по `name`, `owner` получает через `admin.*`, `admin` — через enumerated `_admin_permission_names()`. `"tournament_link"` добавить в `_MEMBER_READ_RESOURCES` (:81-104); `"stream"` — **не** добавлять (health поллера рядовому участнику не нужен, аналогия с `rank`/`subscription`/`audit`). Тест — `backend/shared/tests/test_rbac_catalog_stream_permission.py` по образцу `test_rbac_catalog_audit_permission.py:1-19` (три теста: есть в каталоге / admin получает + owner == `("admin.*",)` / member и player не получают).

В `audit_log` пишем только ручной re-poll (`record_audit(source="admin", action="stream.repoll", ...)` **до** своего `session.commit()`) и CRUD ссылок (бесплатно). Тики поллера — не пишем: бюджет журнала ~300 строк/день (`2026-08-12-platform-audit-log-design.md` §4 NFR 4), а §1 прямо фиксирует, что доменные журналы живут отдельно. Здоровье поллера — Prometheus на `:9111`: `stream_poll_ticks_total`, `stream_channels_polled`, `stream_live_channels`, `stream_helix_errors_total{kind}`, `stream_helix_ratelimit_remaining`.

### 4.7 Фронтенд

| Что | Где | Как |
| --- | --- | --- |
| Официальная трансляция (persistent, виден на всех табах) | новый компонент в `_components/TournamentClientLayout.tsx` между `PageHero` (:106-166) и `TournamentSectionNav` (:168-175) | там уже есть `tournament`, `workspace_id`, realtime-подписка и скоуп-класс `aqt-tn` (:92), дающий `.status-pill.live` бесплатно |
| Стримы участников | новый таб `stream`: `[id]/stream/page.tsx` (11 строк по образцу `maps/page.tsx`) + `_views/TournamentStreamPage.tsx` | регистрация таба = 3 правки: union в `tournament-section-nav.ts:3-4`, массив :55-64, иконка в `TournamentSectionNav.tsx:35-45` |
| Состояния | `_views/publicPageQueryPresentation.ts` | обязательно, покрыто контракт-тестом; свои ternary запрещены |
| Данные | `_queries/tournamentStreams.ts` + `_hooks/useTournamentStreams.ts` + `services/stream.service.ts` | `skipWorkspace: true`, гвард `enabled: Number.isFinite(id) && id > 0`, ключ `tournamentQueryKeys.streams(id)` |
| Realtime | `useRealtimeTopic("tournament:{id}:streams", …)` | **обязателен** trailing-coalescer с per-client джиттером `250 + random()*2500` мс (`useTournamentRealtime.ts:30-45,87-118`): одно событие турнира летит всем зрителям, без джиттера это синхронный рефетч-герд. Плюс catch-up на 4-м аргументе `onSubscribed` |
| Плеер | `components/stream/TwitchEmbed.tsx` | `<iframe src="https://player.twitch.tv/?channel=X&parent=HOST&muted=true">`, min 400×300 (`https://dev.twitch.tv/docs/embed/video-and-clips/`) |

**`parent=` — критично.** Twitch требует, чтобы `parent` совпадал с фактическим доменом страницы, по одному ключу на домен. Платформа white-label: апекс + сабдомены + произвольные кастомные домены. Значит `parent` берётся из `window.location.hostname` после маунта (прецеденты: `WorkspaceBootstrap.tsx:43`, `realtime.service.ts:41-42`), нормализованный как в `resolveHost` (`lib/site/host.ts:17` — `trim().toLowerCase().split(":")[0]`, Twitch не принимает порт). Брать из `NEXT_PUBLIC_SITE_URL` (`config/site.ts:5`, дефолт — платформенный апекс) **нельзя**: на кастомном домене не совпадёт и плеер откажет. До маунта плеер не рендерим.

Превью — обычный `<img>`: в `next.config.mjs` стоит `unoptimized: true`, так что новый `images.remotePatterns` для `static-cdn.jtvnw.net` не нужен.

**CSP.** Сегодня её нет — менять нечего. Но её отсутствие это дыра, и её закроют (`docs/reviews/2026-07-03-backend-security-performance-review.md:143` уже указывает). Чтобы плеер не отвалился в момент харденинга, вводимая CSP обязана сразу содержать: `frame-src https://player.twitch.tv https://www.youtube-nocookie.com` (+ `child-src` тем же), `img-src … https://static-cdn.jtvnw.net`, `Permissions-Policy: autoplay=(self "https://player.twitch.tv"), fullscreen=(self "https://player.twitch.tv")`. `script-src` трогать не надо — берём чистый iframe, а не JS-SDK Twitch.

### 4.8 Каркас сервиса

Эталон точки входа — `backend/analytics-service/serve_rpc.py` (72 строки, без job-очередей): `setup_logging` → `make_rabbit_broker(prefetch)` → `FastStream(broker)` → `register(broker, logger)` → `@app.on_startup` {`broker.connect`, `setup_sentry`, `setup_tracing`, `start_worker_metrics_server`}, плюс старт/стоп шедулера по образцу `parser-service/serve.py:184-196`. `DeadlineDropMiddleware` ставится фабрикой брокера автоматически. Конверт ответа — `shared/schemas/rpc.py` (`rpc_ok`/`rpc_error`), per-service хелперы копируются с `analytics-service/src/rpc/_common.py`.

Регистрация в инфраструктуре — точный чек-лист:

| Файл | Что |
| --- | --- |
| `backend/stream-service/{pyproject.toml,serve.py,src/**}` | новый пакет; pyproject по образцу `tournament-service/pyproject.toml` |
| `backend/pyproject.toml:13` | `stream-service` в `[tool.uv.workspace] members` (+ `[tool.ty.environment]`) |
| `backend/Dockerfile:26-33` | `COPY stream-service/pyproject.toml …` |
| `docker-compose.yml`, `docker-compose.production.yml` | блок воркера по образцу `analytics-svc` (dev :318-355, prod :425-471); `WORKER_METRICS_PORT=9111` |
| `backend/env/stream.env{,.example}` | `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET` (тот же app id, что у identity-service — прецедент `tournament.env.example:26`) |
| `monitoring/prometheus/prometheus.yml:52-117` | scrape job `stream-svc:9111` |
| `.github/workflows/test-backend.yml:46` | `stream-service` в `for svc in …`, иначе его тесты не запускаются |
| `backend/scripts/export_openapi_schemas.sh:39` | + `stream-service` (нужен `src/openapi_schemas.py`) |
| `Makefile` | цели, перечисляющие сервисы |
| `backend/pyrightconfig.json:13`, `backend/analytics-worker.gpu.Dockerfile:51` | **починить мёртвые ссылки** на `twitch-service`/`auth-service`/`realtime-service` заодно |
| `docs/architecture.md`, `backend/README.md` | таблицы компонентов |

## 5. Осознанные потолки

Все идут `ponytail:`-комментариями в коде рядом с решением.

1. **Live-статус только в Redis.** Флаш Redis → бейджи гаснут до следующего тика (≤ interval). Апгрейд: таблица в схеме `streams` — если понадобится отчёт «кто стримил турнир».
2. **`TTLOnly()` вместо инвалидируемого кэша.** Холодная загрузка видит статус с задержкой до 30 с. Апгрейд: `FromQuery("tournament_id")` + `case "stream_changed"` в `respcache.go:376`.
3. **Polling вместо EventSub.** Задержка до `interval`. Апгрейд: EventSub `stream.online/offline` — но это публичный HTTPS-роут в gateway (сейчас webhook-роутов нет ни одного), HMAC-верификация и lifecycle подписок.
4. **`user_login` для самозаявленных ников.** Переименованный канал молча станет offline навсегда. Verified-аккаунты этим не страдают — для них берётся `provider_user_id`.
5. **YouTube без live-детекта.** Ссылка и эмбед работают, бейджа «в эфире» нет.
6. **Настройка `stream.collection` глобальная**, не per-workspace (`get_setting_value` фильтрует только по `key`). Апгрейд: колонка на `Workspace`, не запись в `Settings`.

## 6. Risks

- **`parent=` на кастомном домене.** Несовпадение → плеер отказывается грузиться, и это самый вероятный баг фичи. *Mitigation:* значение только из `window.location.hostname`, рендер после маунта, e2e-проверка на tenant-хосте.
- **Гердовый рефетч.** Один турнир = сотни одновременных зрителей на одном WS-топике. *Mitigation:* джиттер `250 + random()*2500` мс — не опция, а требование (`useTournamentRealtime.ts:30-45`); плюс один сигнал на турнир, а не на канал.
- **Раскрытие скрытого канала.** *Mitigation:* фильтр видимости в SQL-выборке (4.5), тест «скрытый аккаунт не попадает в публичный ответ».
- **Скрытый турнир.** Поллер видит `is_hidden`, публичный топик — нет. *Mitigation:* `assert_tournament_viewable` до чтения; на подписке — `allowSpectateTournament` («public unless hidden», `acl.go:82`); публикация в топик только для не-скрытых.
- **Квота Helix.** 800 points/min на client id — общая с identity-service (тот же app). *Mitigation:* `Ratelimit-Remaining` как гейт внутри тика, `batch_size le=100`, `enabled=False` по умолчанию.
- **Мёртвый домен gateway.** Новый префикс без guard-блока уходит в катч-олл `/` → петля gateway↔frontend. *Mitigation:* guard + `buildStreamsGuardedMux` в `apiv1_guard_test.go` (ровно та ловушка, от которой этот тест и написан).
- **Стейл `schemas.json`.** CI-гейт `export_openapi_schemas.sh --check` падает с «schemas.json is STALE». *Mitigation:* регенерация — обязательный шаг плана.

## 7. Decision Log

| Решение | Альтернативы | Почему |
| --- | --- | --- |
| **D1.** Отдельный `stream-service` | модуль в `parser-service` (там уже есть leader-lock, circuit breaker, egress) | выбор пользователя (ask). Отмечено честно: модуль был бы ~150 строк против нового деплой-юнита с Dockerfile-таргетом, env, метрик-портом, scrape-job и CI-записью. Оправдано, если в сервис лягут EventSub/clips/VOD |
| **D2.** Live-статус в Redis, схемы `streams` нет | таблица `streams.channel_state` + append-only лог | статус эфемерен (A5): устаревший хуже отсутствующего. Redis снимает миграцию, `CREATE SCHEMA`, кортеж `SCHEMAS`, регистрацию моделей, репозиторий, правку `SCAN_ROOTS` и новый тест границ схем — шесть точек интеграции за данные, которые живут 60 секунд. **Расходится с формулировкой «схема streams» в ответе ask — вынесено на решение** |
| **D3.** Каналы участников выводятся из существующих таблиц | своя таблица `stream_channel` | `registration.twitch_nick` + `stream_pov` **уже есть** и уже публичны; `social_account` даёт verified-путь. Новый реестр дублировал бы согласие, которое уже собрано |
| **D4.** `tournament_link` в `tournament.*`, generic `EntityConfig` | bespoke RPC-хендлеры; колонка `stream_url` на `tournament` | реестр даёт CRUD, RBAC и аудит без новых очередей; колонка упирается в один стрим и противоречит #99 |
| **D5.** Non-durable realtime, один сигнал на турнир | durable `publish_event` с дельтой; сигнал на канал | переподключившийся клиент рефетчит (`replay.go:59-61`), персист строки на каждое включение стрима ничего не покупает. Прецеденты: `logs.updated`, `subscription.updated` |
| **D6.** `TTLOnly()` для кэша gateway | инвалидация через `tournament:{id}:bracket` + новый reason | 1 строка против 3 файлов в 2 языках; WS уже даёт мгновенность там, где это видно |
| **D7.** `tournament:{id}:streams` (публичный спектаторский) | `workspace:{id}:streams` (уже покрыт ACL `workspace:*:*`) | воркспейс-топик требует членства → анонимный зритель, главный потребитель фичи, не подпишется. Цена — одна строка `register` в `acl.go` |
| **D8.** Поллинг только `status IN (check_in, draft, live, playoffs)` | все незавершённые; только `live` | официальная трансляция стартует до первой карты; `registration` может тянуться неделями и жёг бы квоту зря |

## 8. Exit Criteria

Understanding Lock подтверждён (ask 2026-08-16: объём, детект, платформы, граница, модель ссылок). Дизайн изложен по всем слоям: данные, поллер, RPC/gateway, приватность, RBAC/аудит, фронтенд, каркас сервиса. Осознанные потолки перечислены с путями апгрейда. Риски зафиксированы с mitigation. Decision Log полон.

**D2 решён в пользу Redis-only** — схема Postgres `streams` не создана. Реализовано; смоук пройден: плеер Twitch грузится с `parent`, взятым из `window.location.hostname`, `live: null` доезжает до клиента отдельно от `false`, скрытый турнир отдаёт 404 и на HTTP, и на WS-подписке.
