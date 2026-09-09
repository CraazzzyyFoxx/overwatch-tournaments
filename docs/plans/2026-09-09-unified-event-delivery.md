# Единый маршрут доставки событий: инвалидация отдельно от данных

Статус: design, ожидает решения по D5 (стратегия выката).
Предшественники: `2026-08-24-realtime-shared-library.md` (эта волна пересматривает его D1/D2/D4/D10), `2026-06-09-gateway-architecture-design.md`.

## 1. Проблема

Один и тот же факт — «эти данные устарели» — сегодня кодируется тремя независимыми способами, и публикуется шестью разными механизмами.

**Три кодировки одного факта.** Публикатор сообщает `reason` (*почему*), и каждый потребитель самостоятельно догадывается, *что* именно устарело:

| Слой | Таблица | Файл |
|---|---|---|
| Gateway respcache | `reason → URL-подстроки` | `gateway/internal/respcache/respcache.go:435-464` |
| Backend cashews (tournament) | `reason → cashews-глобы` | `backend/tournament-service/src/services/tournament/cache_invalidation.py:29-79` |
| Backend cashews (app) | `reason → cashews-глобы` | `backend/app-service/src/services/tournament_events.py:28-66` |
| Frontend React Query | `reason → query-ключи` | `frontend/src/hooks/tournamentRealtime.helpers.ts:79-148` |

Расхождение этих таблиц — не гипотетический риск, а два уже случившихся бага (оба исправлены в `eaf50f0a`, но исправлены точечно):

- драфтовый пик не нёс `reason` → попадал в default-ветку `reasonPatterns` (`nil` = «снести всё по турниру») и на пиковый день стоил **250+ полных вытеснений кеша турнира** при том, что пик не меняет ни одной публичной читалки;
- экспорт баланса, который перезаписывает `tournament.team` / `player` / `standing` через `TeamMaterializationService` (`backend/shared/services/team_export/service.py:87-187`), публиковал только на `tournament:{id}:balancer` — топик, который respcache игнорирует по конструкции (`respcache.go:486-489`), — и не инвалидировал **ничего**.

**Шесть форм публикации, ~135 точек вызова** (census, `grep` по `backend/`, без тестов):

| Точка | Call sites | Форма |
|---|---|---|
| `register_tournament_realtime_update` | 28 | session-hook + merge причин, только bracket |
| `emit_pickup_mix_updated` | 21 | non-durable redis напрямую |
| `enqueue_tournament_changed` | 13 | outbox → RabbitMQ |
| `enqueue_outbox_event` | 13 | сырой outbox |
| `register_realtime_update` | 11 | общая фабрика (`shared/services/realtime_transaction.py:50-63`) |
| `register_map_veto_realtime_update` | 10 | обёртка над фабрикой |
| `publish_envelope_to_redis` | 8 | non-durable напрямую |
| `publish_notification_created` / `publish_logs_updated` / `publish_subscriptions_updated` | 12 | non-durable, по домену |
| `publish_event` / `publish_patch` | 10 | durable напрямую |
| `emit_balancer_data_event` / `emit_balancer_job_event` / `emit_balancer_job_progress` | 10 | своя сессия + fire-and-forget task |

Каждая форма несёт свои гарантии (durable/non-durable, до/после коммита, с ретраями/без), и выбор формы делается на глазок в точке вызова.

## 2. Grounded facts (проверено в коде этой сессией)

**Транспорт WS.** Python persist'ит строку `realtime.workspace_event` и делает `PUBLISH realtime:<topic>`; Go-гейтвей `PSUBSCRIBE realtime:*`, снимает префикс и раздаёт в `Fanout(hub, respCache)` — один и тот же байт-в-байт фрейм идёт и в WebSocket, и в инвалидатор HTTP-кеша (`gateway/internal/events/events.go:18-95`, `gateway/cmd/gateway/main.go:444-448`).

**Топики и ACL.** 8 правил, first-match-wins, unknown → deny (`gateway/internal/acl/acl.go:80-106`). `Pattern` — сегментный матчер, `*` = ровно один сегмент (`acl.go:33-61`). Видимость различается по scope: `tournament:*:{bracket,draft,streams}` публичны, если турнир не скрыт; `tournament:*:balancer` — членам воркспейса; `workspace:*:*` — членам; `user:*:notifications` — только самому пользователю, без обхода для суперюзера.

**Реплей.** `realtime.workspace_event`, курсор = `MAX(id)` по топику, добор `(after, upTo]` c `LIMIT WS_REPLAY_LIMIT+1` (дефолт 500), гэп → `ErrGapTooLarge` (`gateway/internal/replay/replay.go:22-99`). Первый подписчик без курсора реплея **не получает**. Курсор живёт в памяти zustand без `persist` (`frontend/src/stores/realtime.store.ts:18-29`) — то есть не переживает перезагрузку страницы.

**Порядок инвалидации сегодня осознан.** `tournament/realtime_commit.py` чистит cashews в `after_commit` **до** публикации, и это закреплено тестом `test_realtime_update_invalidates_cache_before_publishing`. Порядок «сначала бэкенд-кеш, потом клиенты» — существующая гарантия, её нельзя потерять.

**Гейтвейный кеш.** LRU 4096 записей / 32 MiB / ≤3 MiB на запись, TTL `GATEWAY_RESPONSE_CACHE_TTL` (сейчас 120 с на проде), singleflight на промахах, ключ = path + отсортированный query (`respcache.go:60-79,349-395,500-533`). Записи с `TTLOnly()` живут под sentinel-скоупом `id=0`, которого реальный запрос дать не может, — **никакое событие их не инвалидирует** (`respcache.go:139-146`).

**Фронтовый примитив.** `useRealtimeCoalescedRefetch(topic, {onEvent, onFlush, onCatchUp, minDelayMs, jitterMs, catchUpMs})` (`frontend/src/hooks/useRealtimeCoalescedRefetch.ts:14-58`) уже owns реконнект-страховку и джиттер 250 + rand(2500) мс. Патч-примитив `registerRealtimeResource` / `applyResourcePatch` с контрактом идемпотентности по `event_id` — `frontend/src/services/realtime-patch.ts:7-64`.

**Объём на проде (2026-09-09).** `realtime.workspace_event`: 11 939 строк / 4.3 МБ за 4 месяца, средний payload 60 Б, максимум 310 Б. Durable-семейства: `tournament.updated` 5601, `balancer.registrations_changed` 2244, `pick_ban.updated` 1304, `map_veto.updated` 1028, draft.* 1301, `analytics_job.*` 247. Пиковый драфтовый день — 275 событий. Ретеншен: только bracket, 7 дней (`tournament-service/serve.py:137-158`).

## 3. Целевая архитектура

### 3.1 Разделение двух вещей

| | Инвалидация | Доставка данных |
|---|---|---|
| Топик | `<scope>:invalidation` | `<scope>:<domain>` (`:draft`, `:balancer`, `:map-veto`, `:streams`, `:notifications`, `:logs`, `:analytics_jobs`, `:pickup_mix`) |
| Payload | `{"resources": [...], "entity_ids": {...}?}` | предметный: патч, presence, прогресс |
| Семантика | множество (коммутативно, идемпотентно) | последовательность (порядок значим) |
| Порядок | не требуется | по `event_id` |
| Потребители | gateway respcache, cashews каждого сервиса, `useInvalidation` | конкретный домен-хук |

Из этого разделения следует ключевое свойство: **инвалидация не требует упорядоченной доставки**, потому что объединение множеств коммутативно. Это снимает с неё все требования, из-за которых сегодня приходится думать про порядок публикации патчей.

### 3.2 Единственный примитив публикации

`backend/shared/services/realtime/emit.py` (новый пакет, старый `realtime_publisher`/`realtime_transaction` схлопываются в него):

```python
async def emit(
    session: AsyncSession,
    *,
    scope: Scope,                        # Scope.tournament(42) | .workspace(7) | .user(3) | .encounter(9)
    invalidates: Sequence[Resource] = (),
    entity_ids: Mapping[str, Sequence[int]] | None = None,
    data: DomainEvent | None = None,     # event_type + payload + resource(для патча)
    actor_user_id: int | None = None,
) -> None
```

Правила примитива, все — инварианты, а не соглашения:

1. **Только через session-hook.** `before_flush` персистит строки, `after_commit` публикует. Ни одного пути «своя сессия + fire-and-forget» (сегодня так делает `emit_balancer_data_event`) и ни одного пути «публикуем до коммита» (сегодня так делает прямой `publish_event`).
2. **Дедуп и объединение в транзакции.** Ключ `(scope, "invalidation")`: `invalidates` со всех вызовов внутри транзакции объединяются в **одно** событие с union-множеством ресурсов. Это обобщение существующего `_merge_updates`, но точнее: там сворачивалось в «сильнейшую причину», здесь складываются ровно затронутые ресурсы.
3. **Порядок после коммита фиксирован:** (a) локальные кеши этого сервиса чистятся синхронно по таблице `RESOURCE_CACHE_PATTERNS`; (b) `PUBLISH` в Redis; (c) outbox-строка для остальных сервисов. Пункт (a) перед (b) — сохранение существующей гарантии (см. §2).
4. **Durability.** Инвалидационные события всегда durable (строка `workspace_event`) — реплей закрывает разрыв для переподключившегося клиента. Домен-события durable по решению домена (`DomainEvent.durable`), как сегодня.
5. **Никаких «reason».** Поле удаляется из вокабуляра целиком.

`Scope` — value object, а не строка: он же строит топики (`scope.invalidation_topic()`, `scope.domain_topic(domain)`), и он же — единственное место, где формат топика зашит. Сегодня формат размазан по `realtime_topics.py` и продублирован в `LIKE 'tournament:%:bracket'` ретеншен-джобы и в `strings.CutPrefix(topic, "tournament:")` гейтвея.

### 3.3 Вокабуляр ресурсов как единственный источник истины

`backend/shared/realtime/resources.json` — манифест, из которого генерируются/валидируются все три потребительские таблицы:

```json
{
  "version": 1,
  "resources": {
    "tournament.detail":            {"scope": "tournament", "route_refresh": false},
    "tournament.teams":             {"scope": "tournament"},
    "tournament.standings":         {"scope": "tournament"},
    "tournament.encounters":        {"scope": "tournament"},
    "tournament.stages":            {"scope": "tournament"},
    "tournament.structure":         {"scope": "tournament", "route_refresh": true},
    "tournament.registrations":     {"scope": "tournament"},
    "tournament.registration_form": {"scope": "tournament"},
    "tournament.streams":           {"scope": "tournament"},
    "workspace.logs":               {"scope": "workspace"},
    "workspace.pickup_mix":         {"scope": "workspace"},
    "workspace.subscriptions":      {"scope": "workspace"},
    "workspace.analytics_jobs":     {"scope": "workspace"},
    "user.notifications":           {"scope": "user"}
  }
}
```

- Python: `Resource` StrEnum, сгенерированный (или провалидированный) из манифеста.
- TypeScript: union-тип + `RESOURCE_QUERY_KEYS` — сгенерированный union, рукописная таблица ключей.
- Go: `resourcePatterns` — рукописная таблица, провалидированная тестом против манифеста.

**CI-гейт (это и есть то, что делает решение неправкой-потом):** три теста, по одному на слой, падают, если в манифесте есть ресурс, которого нет в таблице слоя, или наоборот. Публикатор не может объявить ресурс, который никто не умеет инвалидировать; потребитель не может завести правило для ресурса, которого никто не публикует. Размещение: `test-backend.yml`, `ci-frontend.yml`, `ci-gateway.yml` — каждый видит свою часть, манифест лежит в `backend/shared` и читается всеми тремя (для фронта и гейтвея — через путь в репозитории, не через пакет).

`route_refresh` в манифесте — замена нынешнему `shouldRefreshRoute` у `structure_changed`: свойство ресурса, а не причины.

### 3.4 Gateway

- `events.Subscriber` не меняется (`PSUBSCRIBE realtime:*`).
- `respcache.Broadcast` переписывается: реагирует **только** на топики `*:invalidation`, парсит `data.resources`, объединяет URL-подстроки по таблице `resourcePatterns`. Уходят: `eventFrameReason`, `reasonPatterns`, спецкейс `sub != "bracket" && sub != "draft"`.
- `Invalidate(scopeID, patterns)`: семантика «пустой не-nil срез = не сносить ничего» остаётся; `nil` (неизвестный ресурс/непарсящийся payload) остаётся fail-safe «снести всё по scope».
- ACL: три новых правила с наследованием видимости домена того же scope:
  ```go
  r.register("tournament:*:invalidation", r.allowSpectateTournament)
  r.register("workspace:*:invalidation",  r.allowWorkspaceMember)   // уже покрыт workspace:*:*
  r.register("user:*:invalidation",       r.allowOwnNotifications)
  ```
  `encounter:*:invalidation` не заводим: pick-ban/map-veto — чистая доставка данных, инвалидация энкаунтера выражается через `tournament.encounters` в scope турнира.
- WS-хаб, протокол, реплей — без изменений (payload-агностичны).

### 3.5 Frontend

- Новый `useInvalidation(scope)`: один хук, поверх существующего `useRealtimeCoalescedRefetch` (джиттер и реконнект-страховка переиспользуются как есть). `onEvent` копит union ресурсов, `onFlush` инвалидирует по `RESOURCE_QUERY_KEYS`, `onCatchUp` инвалидирует все ресурсы scope (эквивалент нынешнего catch-up-плана).
- `route_refresh`-ресурс дергает `router.refresh()` — ровно там, где сейчас `shouldRefreshRoute`.
- Домен-хуки худеют до патчей и presence: из `useDraftData` уходит `draftInvalidationTargets`, из `useBalancerRealtime` — инлайновая мапа трёх event_type → ключи, из `useNotifications` — безусловный `invalidateQueries`, из `useTournamentStreamRealtime` — весь thin-signal-контур, из `tournamentRealtime.helpers.ts` — все reason-планы (файл удаляется).
- `applyResourcePatch` получает предохранитель версий: `schema_version` события ≠ версии reducer'а → `"unregistered"` → вызывающий падает в инвалидацию (то, что было отдельной задачей CountsPatch-фазы).

### 3.6 Backend-консьюмеры

- Новый `shared/messaging/invalidation.py`: exchange `cache.invalidation` (topic), routing key `<scope_kind>.<scope_id>`, по одной durable-очереди на сервис-владелец кеша + DLQ. Регистрируется только там, где кеш есть: tournament-svc и app-service.
- Контракт консьюмера: `resources → RESOURCE_CACHE_PATTERNS[service] → cache.delete_match`. Таблица локальна для сервиса; один ресурс может иметь паттерны в двух сервисах (например `tournament.standings` чистит `*standings*:{id}:*` в tournament-svc и `*tournaments/{id}*` + user-кеши в app-service).
- `TOURNAMENT_CHANGED_EXCHANGE`, обе очереди, обе DLQ, `TournamentChangedEvent`, `enqueue_tournament_changed`, `handle_tournament_changed_event` — **удаляются**. `hero_stats_refresh.request_refresh`, который сейчас висит на том консьюмере (`app-service/src/services/tournament_events.py:92`), переезжает на ресурс `tournament.standings`.

### 3.7 Ретеншен и реплей

- Инвалидационные строки: ретеншен 7 дней, все scope'ы (они по определению не нужны старше окна жизни вкладки; курсор в памяти).
- Домен-строки: политика D10 предшественника сохраняется (bracket 7 дней; pregame/draft не чистим — у сессий нет верхней границы).
- Один DELETE на семейство, без батчинга (D2 предшественника).

## 4. Breaking changes (принимаем осознанно)

1. Формат payload любого события: `reason` удалён, появляются `resources`/`entity_ids`.
2. Новое семейство топиков; домен-топики теряют инвалидационную функцию.
3. `tournament.changed` exchange + 2 очереди + 2 DLQ + схема события удалены. Требует ручного удаления очередей в RabbitMQ после выката (иначе они останутся с растущим backlog'ом).
4. Удаляются 6 форм публикации и ~135 точек переписываются на одну.
5. `tournamentRealtime.helpers.ts` удаляется вместе с тестами; `reasonPatterns` в гейтвее удаляется.
6. Реплей событий, записанных до выката (в таблице сейчас 11 939 строк): новый клиент получает старую форму. Обрабатывается fail-safe-правилом «нет `resources` → инвалидировать scope целиком», а не миграцией строк.

## 5. Волны выката

| Волна | Содержание | Приёмка |
|---|---|---|
| 0. Фундамент | манифест + `Scope`/`Resource`/`emit`; три потребителя (`resourcePatterns` + ACL в гейтвее, `useInvalidation` + `RESOURCE_QUERY_KEYS`, `InvalidationConsumer` + `RESOURCE_CACHE_PATTERNS`); три CI-гейта. Старые пути живы и не тронуты | новые тесты зелёные; ни один старый не изменён |
| 1. Tournament | 28 `register_tournament_realtime_update` + 13 `enqueue_tournament_changed` → `emit`; `cache_invalidation.py` → таблица ресурсов; фронт: bracket-план → `useInvalidation` | форма/регистрации/результаты/структура проверены на dev; `reasonPatterns` больше не вызывается для tournament-scope |
| 2. Encounter + draft/balancer | 10 map-veto + 11 фабрики + 10 balancer/draft; патчи остаются на домен-топиках | пик драфта не инвалидирует ничего; экспорт инвалидирует `tournament.teams/standings/structure` |
| 3. Workspace-scope | 21 pickup_mix + 3 logs + 2 subscriptions + 7 notifications + analytics_jobs | каждый домен-хук ужат до патчей/presence |
| 4. Зачистка | удаление старых примитивов, `tournament.changed`, reason-таблиц, `tournamentRealtime.helpers.ts`; ручное удаление очередей RabbitMQ; ретеншен под новую таксономию | `grep` по старым именам — 0 совпадений; минус ~600 строк |

Каждая волна — отдельный релизный тег: деплой атомарный (все 10 образов одним тегом, `deploy-production.yml:118-174`), поэтому внутри волны бэкенд/гейтвей/фронт согласованы по определению, а откат = редеплой предыдущего тега.

## 6. Решения

| # | Решение | Альтернатива | Почему |
|---|---|---|---|
| D1 | Инвалидация — отдельное семейство топиков `<scope>:invalidation`, домен-топики только для данных | оставить reason в домен-топиках | три расходящиеся таблицы `reason→ключи` и два бага из §1 — прямое следствие смешения |
| D2 | Не один глобальный топик, а один **на scope** | буквально один `invalidation` | ACL: видимость различается (скрытые турниры, приватные воркспейсы, персональные уведомления). Глобальный топик = утечка метаданных активности |
| D3 | Вокабуляр — «что устарело» (ресурсы), не «почему» | сохранить reason-семантику | у ресурса один смысл на все слои; у reason — три перевода, каждый со своим дрейфом |
| D4 | Манифест + CI-гейт на все три таблицы | конвенция и ревью | единственная механическая защита от «объявил ресурс, который никто не инвалидирует» |
| D5 | Cutover по волнам без dual-write | dual-write с периодом двойной публикации | деплой атомарный, курсоры реплея в памяти, откат = предыдущий тег. Dual-write удваивает объём событий и оставляет обе кодировки одновременно живыми — то есть ровно ту проблему, которую волна устраняет. **Требует подтверждения** |
| D6 | Два транспорта под одним примитивом: Redis (клиенты) + outbox (бэкенды) | только Redis; только RabbitMQ | у клиентов пропуск закрыт TTL + реплеем, у cashews — нечем; outbox даёт ретраи и DLQ. Гейтвею брокерная зависимость на пути WS-фанаута не нужна |
| D7 | Порядок после коммита: локальный кеш → Redis → outbox | публиковать и чистить параллельно | сохраняет существующую гарантию (`test_realtime_update_invalidates_cache_before_publishing`) |
| D8 | Агрегаты между турнирами (`/api/v1/tournaments`, `facets`, `statistics/*`) остаются TTL-only | ввести `platform`-scope с глобальным публичным топиком | глобальный топик = фан-аут на все соединения; при нынешних сотнях спектаторов приемлемо, но это единственное место, которое плохо масштабируется. Имя scope зарезервировано, ввод — отдельное решение |
| D9 | `encounter:*:invalidation` не заводим | завести для симметрии | инвалидация энкаунтера выражается как `tournament.encounters` в scope турнира; лишний ACL-путь с резолвом турнира по энкаунтеру не нужен |
| D10 | `entity_ids` в payload с самого начала, потребители вправе игнорировать | добавить, когда понадобится | добавление поля позже = смена формата события у 135 публикаторов и трёх потребителей. Резерв под точечную инвалидацию (строка регистрации, один энкаунтер) стоит ноль сейчас |

## 7. Анализ (Skeptic pass)

| # | Возражение | Severity | Резолюция |
|---|---|---|---|
| O1 | Кросс-сервисная инвалидация асинхронна: клиент получит Redis-сигнал раньше, чем app-service почистит cashews, и его же рефетч может **переположить** в гейтвейный кеш ответ, собранный из ещё не почищенного cashews | Blocker | Принято. Три меры: (1) D7 фиксирует порядок для локального кеша; (2) для кросс-сервисных ресурсов окно = drain outbox (1 с) + `delete_match`, а фронтовый коалесер по конструкции ждёт 250 + rand(2500) мс — то есть буфер уже существует и измерим; (3) правило вокабуляра: если ресурс чистится в другом сервисе, `emit` обязан положить outbox-строку **до** Redis-публикации (порядок внутри `after_commit`), чтобы drain успел начаться. Остаточный риск: ~1 с окно при полностью холодном кеше — сегодня он такой же |
| O2 | Fail-safe «нет resources → снести всё по scope» превращает любой баг публикатора в тихую потерю кеша вместо громкой ошибки | Significant | Принято к сведению. Fail-safe остаётся (стейл хуже промаха), но добавляется метрика `respcache_invalidation_unscoped_total` и лог с топиком/event_type; CI-гейт D4 закрывает основную причину |
| O3 | `structure_changed` несёт `shouldRefreshRoute` — поведение, которого у «ресурса» нет | Significant | Принято. Введён ресурс `tournament.structure` с флагом `route_refresh` в манифесте; свойство переезжает из кода в манифест |
| O4 | Ресурс `tournament.detail` инвалидируется почти всем (счётчики регистраций, результаты, структура) — не станет ли он де-факто «снести всё»? | Minor | Принято к сведению. Так и есть, и это честнее нынешнего `bareTournamentDetailPattern`: сейчас та же запись сносится по трём разным reason'ам, просто неявно |
| O5 | Объём: каждая мутация пишет строку `workspace_event` + outbox-строку | Minor | Замерено: сейчас 100 событий/сутки, 4.3 МБ за 4 месяца, payload 60 Б. Даже при 1000 мутаций/сутки это ~2000 строк по ≤300 Б. Незначимо |
| O6 | 135 точек в четырёх сервисах — волна, которую невозможно проверить целиком | Blocker | Принято. Отсюда деление на волны по доменам (§5) и требование: каждая волна — свой релизный тег со своей приёмкой. Волна 1 (tournament, 41 точка) — самая крупная; если она пройдёт, остальные механические |
| O7 | Удаление `tournament.changed` оставит в RabbitMQ две очереди с накапливающимся backlog'ом | Significant | Принято. Пункт в волне 4: ручное удаление очередей + DLQ после выката, до этого они просто перестают наполняться. В плане это единственный ручной шаг на проде |
| O8 | Реплей старых событий (11 939 строк) новому клиенту | Significant | Принято, покрыто fail-safe (O2) + тем, что курсор не переживает перезагрузку страницы, так что окно — время жизни одной вкладки |
| O9 | Потеря `_merge_updates` (свёртка в сильнейшую причину) может изменить наблюдаемое поведение | Minor | Снято: union множеств строго точнее свёртки. Там, где раньше `structure_changed` поглощал `registration_changed`, теперь оба набора ресурсов складываются — то же покрытие, без «поглощения не тем» |
| O10 | Один `emit` с четырьмя необязательными аргументами — God-функция, которая обрастёт флагами | Minor-to-Significant | Принято к сведению. Граница: `emit` знает только про scope, ресурсы и один опциональный домен-payload; он **не** знает про домены (нет `if scope.kind == ...`), таблицы паттернов живут у потребителей. Если понадобится пятый аргумент — это сигнал, что новая сущность просится в вокабуляр, а не в подпись |
| O11 | Гейтвей теперь игнорирует домен-топики для кеша: если завтра домен-патч изменит публичные данные, кеш не узнает | Significant | Принято и это **намеренно**: именно смешение и дало баг с экспортом. Правило: любая мутация публичных данных обязана перечислить ресурсы; патч — только про UI. Закрепляется тестом на респкеш («домен-топик не инвалидирует ничего») |
| O12 | Что всё-таки может заставить переделывать | — | (а) переход к точечной инвалидации — закрыт D10 (`entity_ids` заранее); (б) exactly-once для клиентов — закрыт durable-строками + курсором; (в) масштабирование фан-аута агрегатов — закрыт D8 (зарезервированный scope, TTL сейчас); (г) эволюция формата — `schema_version` на событии + `version` в манифесте; (д) несколько инстансов гейтвея — Redis pub/sub уже это умеет, respcache у каждого свой и инвалидируется одним и тем же сообщением |

## 8. Non-goals

- WS-транспорт (хаб, протокол, реплей, лимиты) — не трогаем.
- Модель ACL — только три новых правила, механика та же.
- Патч-примитив и `resource`-теги патчей — остаются как есть (плюс предохранитель версий).
- Партиционирование `workspace_event` — избыточно при 4.3 МБ.
- Перевод bracket на snapshot/delta-патчи (D4 предшественника) — отдельное решение, эта волна его не затрагивает.
