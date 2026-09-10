# Реестр зеркал кода — anak-tournaments

**Дата инвентаризации:** 2026-08-04
**Метод:** три read-only скаута (backend↔frontend, Python↔Rust, внутри Python) + проверка
кодоген-пайплайна запуском + AST-сравнение тел функций.
**Назначение:** справочник. Программа работ — в
[2026-08-04-mirror-removal-design.md](./2026-08-04-mirror-removal-design.md).

---

## Определение

**Зеркало** — две или более независимые реализации одного правила, структуры или
контракта, где расхождение = баг, и ничто в коде не заставляет их совпадать: нет
кодогена, нет общего модуля, нет контракт-теста.

**Не зеркало:** обычная слоистость (Pydantic-схема сериализует SQLAlchemy-модель),
представления с намеренно разным набором полей, тесты, фикстуры, compat-слои
одностороннего переименования.

---

## Итог

| Срез | Зеркал | Уже разошлись |
|---|---|---|
| Python-бэкенд ↔ TypeScript-фронтенд | 36 | 8 |
| Внутри Python-бэкенда (сервис↔сервис) | 18 | ~6 |
| Python ↔ Rust `tournament_balancer`, балансер ↔ драфт | 8 | 3 |
| **Всего** | **62** | **~17** |

**Ни одно из 62 не защищено контракт-тестом, кодогеном или общим модулем.**

---

## Пять классов

| Класс | Что это | Объём | Лекарство |
|---|---|---|---|
| **A. Формы данных** | Pydantic DTO ↔ TS-интерфейсы | ~36 зеркал | Кодоген TS из `/api/openapi.json` |
| **B. Инфраструктурная копипаста** | Одинаковая обвязка воркера, размноженная при выделении каждого сервиса | ~737 строк | Перенос в `shared/` |
| **C. Раздвоенный домен** | Целые подсистемы в двух сервисах | ~2500 строк | Разбирать по одной: удалить / доделать миграцию / точечная экстракция |
| **D. Раздвоенное правило** | Одна бизнес-инварианта, выраженная дважды разным кодом | ~25 правил | Server-driven где возможно, контракт-тест где нет |
| **E. Живые баги** | Расхождение уже произошло | 14 | Починить |

---

## Кодоген: существует и останавливается за шаг до фронтенда

```
Pydantic-модели 6 сервисов
  → backend/scripts/export_openapi_schemas.sh
  → gateway/internal/openapi/schemas.json      (939 706 байт)
  → //go:embed (gateway/internal/openapi/openapi.go:27)
  → OpenAPI 3.1 на /api/openapi.json + /api/openapi.admin.json
  → Scalar UI на /api/docs
                                                ✗ фронтенд не подключён
```

**Проверено запуском 2026-08-04:** пайплайн работает, `schemas.json` **в синхроне**
(md5 `aeaf7a5b…` совпал), полная регенерация — **9.5 секунды**.

**Но:**
- **CI его не проверяет.** Предыдущее ревью зафиксировало дрейф `+724/-175`:
  «`schemas.json` was already stale on `develop`… no CI job diffs it, so the drift
  would ship silently» (`docs/superpowers/plans/2026-08-04-workspace-discord-guild.md:1050,1205`).
- **Фронтенд не потребляет ничего.** В `frontend/package.json` нет ни
  `openapi-typescript`, ни `orval`, ни `@hey-api/openapi-ts`, ни
  `swagger-typescript-api`. Все ~24 файла `frontend/src/types/**`, все перечисления,
  все правила валидации и все дефолты написаны руками.
- **Манифест сам признаёт неполноту:** `openapi_schemas.py` — «Models below mirror the
  return annotations of the flow functions», «ad-hoc dicts / None (204) are
  intentionally omitted». Отсутствующая запись деградирует до generic `object`
  молча.

---

## Класс E: живые баги

| # | Где | Что | Класс-источник |
|---|---|---|---|
| 1 | `tournament-service/src/rpc/_helpers.py:122` | `_read` не ловит `MissingIdentityError` → неаутентифицированный read отдаёт **500 вместо 401** | B |
| 2 | `tournament-service/src/rpc/_helpers.py:103,122` | `str(exc.detail)` вместо `_detail_message` → **утечка Python-repr клиенту** при `detail=list` | B |
| 3 | `tournament-service/src/rpc/_helpers.py:48` | `_payload` без `isinstance(dict)`-проверки | B |
| 4 | `parser-service/src/services/admin/team.py` | Нет null-guard на `workspace_member` → AttributeError. **Код недостижим** (см. класс C) | C |
| 5 | `tournament-service/.../serializers.py:87` | Порог флекса `>=1` роль против `>=2` в модели → админка показывает флекс, экспорт шлёт `isFullFlex=false` | D |
| 6 | `balancer-service/.../balance_analytics.py:132-137` | Потерян guard на `is_flex` → `off_role_count` аналитики ≠ `statistics.off_role_count` того же баланса | D |
| ~~7~~ | `tournament_balancer/src/lib.rs:151` | **НЕ БАГ (снят при проверке).** `team_crossover_share` действительно не отправляется из `moo_backend.py`, но имеет `#[serde(default)]`, а его Rust-докстринг прямо говорит «Принимается по wire опционально; в Python UI пока не выставляется» — намеренное неэкспонирование. Аналогично `rating_scale_ceiling`: он вне `PUBLIC_CONFIG_KEYS` потому, что применяется Python-side в `RatingNormalizer` и не является ручкой солвера. Оба зафиксированы как документированные исключения в `tests/test_config_consistency.py` | D |
| 8 | `frontend/src/types/balancer.types.ts:5-43` | Нет `team_max_pain_weight`, `time_limit_ms`; мёртвые `intra_team_variance_weight`, `role_spread_weight`; UI крутит `algorithm`, который бэкенд безусловно выбрасывает (`public_contract.py:78-82`) | D |
| 9 | `draft/selection.py:438`, `rpc/draft.py:441` | `FitConfig()` без аргументов → **override `tank_impact_weight` игнорируется драфтом** | D |
| 10 | `draft/feasibility.py:139` vs `selection.py:286` | Два источника playable-роли внутри драфта → драфт предлагает пик, который сам же отклоняет (**тупик на часах**) | D |
| 11 | `frontend/src/lib/roles.ts:47` | Лишний `dps: "dps"` против Python `_CANONICAL_TO_REGISTRATION` | A |
| 12 | `frontend/src/hooks/usePermissions.ts:37` | Нет `account.avatar`, `account.social`, `registration.self_register` из `PERMISSION_CATALOG:100-102` | A |
| 13 | `frontend/src/lib/tiebreakers.ts:8` | Нет `map_differential`, `wins_as_higher_stage_specific_metric`, которые бэкенд принимает (`standings/service.py:290,292`) | A |
| 14 | `frontend/src/types/registration.types.ts` | `RegistrationForm:145` без `auto_approve`; `StatusMeta` объявлен **дважды** (`:161`, `:263`) | A |
| 15 | `frontend/src/lib/subscription-requirement.ts:41,54` | Нет `deferred`, нет дедупликации провайдеров — при заявленной в комментарии `:21-23` страховке параллельными тестами | D |
| 16 | `frontend/src/lib/balancer-statuses.ts:65,105,119,133` | 4 описания статусов ≠ бэкенду, **хотя бэкенд уже отдаёт каталог** по `rpc.tournament.regstatus_catalog` | D |

---

## Класс B: инфраструктурная копипаста

Числа проверены AST-сравнением тел функций и `difflib` по строкам.

| Зеркало | Копий | Избыточных строк | Доказательство |
|---|---|---|---|
| `src/core/auth.py` | 5 | **379** | analytics ≡ parser **100%, 218 строк**; tournament 76% (161 общих). app (30 стр) и balancer (316 стр) — реально разные |
| `src/rpc/_common.py` + `_helpers.py` | 5 | **159** | AST-идентичны в 4 из 4: `dump`, `payload`, `q`, `q1`, `require_id`. В 3 из 4: `actor`, `identity_user_id`, `qbool`, `require_active`, `require_query_int`. `envelope` совпадает только в одной паре — там и живут баги 1-3 |
| `src/core/db.py` | 7 | **170** | app ≡ tournament 100%; analytics ≡ parser 100%; все пары ≥94.7%. Файлы 24-36 строк |
| `src/rpc/_clients.py` | 2 | **17** | 72%, S3Client-синглтон |
| `src/core/workspace.py::workspace_filter` | 4 | **12** | Модули разошлись (30-71%); истинное зеркало — только сама 4-строчная функция. Её докстринг: «Mirrors parser-service/src/core/workspace.py» |
| **Итого** | | **~737** | из них **549** в байт-идентичных парах — нулевой риск |

**Улика копипасты:** `backend/analytics-service/src/core/auth.py:1` начинается словами
«Authentication dependencies for **parser-service**».

**Дом уже существует:** `backend/shared/rpc/` содержит `identity.py`, `crud.py`,
`query.py`, `deadline.py`, `openapi.py` — и **шестую копию** `_detail_message` в
`crud.py:64`.

---

## Класс C: раздвоенный домен

| Подсистема | Копии | Вердикт | Действие |
|---|---|---|---|
| `services/admin/team.py` | parser 274 стр / tournament 294 стр, 273 общих | **parser-копия МЁРТВАЯ** | Удалить |
| `services/challonge/sync.py` | parser 1687 / tournament 1757 code-lines, 1677 общих | Обе живые, tournament — строгое надмножество | Не дедуп, а **доделать миграцию** — уже есть владелец |
| `services/team/{service,flows}.py` | parser 359 / tournament 191 code-lines | Обе живые, делают **разное** | Вынести 7 идентичных функций, модули не сливать |

### `admin/team.py` — доказательство мёртвости parser-копии

Пройдены все проверки, ни одна не дала пути вызова:

| Искал | Результат |
|---|---|
| Статические импортёры | только `tests/test_admin_team_service.py:28`, `tests/test_admin_team_workspace_member.py:34` (оба через `importlib`) |
| CRUD-реестр | `services/admin/registry.py` в parser **отсутствует** (единственный потребитель в tournament — `registry.py:34,196-199,212-214`) |
| RPC-субъект | ни одного `rpc.parser.*team*` в `parser-service/src/rpc/**` |
| Роут в гейтвее | `/api/v1/admin/teams` и `/api/v1/admin/players` объявлены только в `gateway/internal/tournament/admin_routes.go:17-24` с очередью `rpc.tournament.admin.*` |
| Планировщик | в `parser-service/serve.py:192-193` только `rank_scheduler` и `logs_reaper` |
| Подписчики очередей | 8 штук (`serve.py:201,254,313,351,362,395,406,417`) — ни один не ведёт к `admin.team` |
| `event_outbox` / sweeper | в parser отсутствует (`drain_outbox` только в `tournament-service/serve.py:146`) |
| Динамический импорт | `importlib`/`pkgutil`/`import_module` в `parser-service/src` — **нет совпадений**, значит статический обход исчерпывающ |
| Кросс-сервисный RPC-клиент | единственное совпадение `shared/rpc/crud.py:12` — `rpc.tournament.admin.update`, то есть tournament |

Живой `AttributeError` (баг №4) находится **в мёртвой копии**. Правильное действие —
удалить файл, а не чинить guard.

### `challonge/sync.py` — почему это не наша задача

| Side-effect | parser | tournament |
|---|---|---|
| `enqueue_encounter_completed` | `:1606-1607`, из `shared.services.encounter.events`, с `source_service='parser-service'` | `:1637`, из `src.services.tournament.events` |
| standings recalculation | `:1667` через `src.services.standings.recalculation` | через `src.services.tournament.events` |
| veto-session sync | нет | `:1206` |
| инвалидация read-кэша | нет | `:1421` + `:1703` |
| periodic pull | нет | `:2063` + `:2084` (нужны джобе `challonge_active_sync`) |
| `close_redis` | `:140` — **мёртв**, утечка Redis-клиента при shutdown | нет |

Точки входа: parser — один роут (`gateway/internal/parser/routes.go:69` →
`rpc.parser.encounter.create_challonge`, фронт `admin.service.ts:538`). tournament —
четыре роута (`integrations_routes.go:24-27`) + apscheduler-джоба
`challonge_active_sync` (`serve.py:153-158`) + доменный путь `auto_push_on_confirm`
(`captain.py:511,625`).

**Уже задокументировано как незавершённая миграция:**
- `backend/docs/tournament-service-write-path-inventory.md` — таблица Target ownership
  называет `parser-service/src/services/challonge/sync.py` текущим писателем
  `tournament.group/stage/encounter/encounter_link/team`, Target owner =
  tournament-service, Action = «Move Challonge writers». Та же строка называет
  `parser-service/src/services/{admin/team.py,team/service.py,team/flows.py}`.
- `docs/plans/2026-08-03-admin-match-surfaces-design.md:35,503` — «Full de-duplication
  of the two Challonge sync implementations» = **explicit non-goal**. Решение D13
  (`:163`) называет техническую причину: tournament-копия тянет сервис-локальную
  realtime-регистрацию через `veto_session.py`.
- `docs/plans/2026-08-03-admin-match-surfaces-plan.md:228-241` — задача T4 предписывает
  вносить **одни и те же** три изменения в **оба** файла. Прямое доказательство, что
  обе копии живые и сознательно поддерживаются параллельно.
- **Документ расходится с кодом:** `docs/architecture.md:127` отдаёт Challonge
  исключительно tournament-service, `:128` описывает parser без Challonge. Документ
  описывает целевое состояние миграции, а не текущее.

**Прецедент правильного решения для соседнего дубля:** D12
(`design.md:162`) — parser-копия `finalize.py` **удаляется**, а не обобщается.

### `team/{service,flows}.py` — что мешает слить

1. tournament-flows держит `@cache(ttl=config.settings.teams_cache_ttl, prefix='fastapi:')`
   на `:172-173` и `:311-312` — сервис-локальный Redis read-кэш, которого в parser нет.
2. parser держит синхронные писатели `create_player_sync:402` и
   `_resolve_workspace_member_id_sync:361` для матч-лог-парсера на синхронной `Session`.
3. **Дрейф сигнатур уже произошёл:** `get_by_tournament` принимает `tournament_id: int`
   в parser (`service.py:151`) и `tournament: models.Tournament` в tournament
   (`service.py:135`). Одно имя, разный тип — ловушка при наивном слиянии.

Дословно совпадают только: `team_entities`, `player_entities`,
`resolve_team_placement`, `to_pydantic`, `to_pydantic_player`, `get`,
`get_by_name_and_tournament`, `get_by_tournament_challonge_id`,
`get_player_by_user_and_tournament`.

---

## Класс D: раздвоенное правило

| Правило | Копий | Где | Разошлось? |
|---|---|---|---|
| **Флекс-регистрация** | 4 | `shared/models/registration/registration.py:200` (`>1 роль && all primary` — канон); `tournament-service/.../serializers.py:87` (`>=1`); `tournament-service/.../sheet_parsing.py:460` (по строке `'flex'`, роли не смотрит); `frontend/.../registration/types.ts:44`; `frontend/.../workspace-helpers.ts:428` (`length>0`) | **ДА** (баг 5) |
| **Discomfort** | 3+1 | `balancer/algorithm/entities.py:44-51`; `tournament_balancer/src/context.rs:100-119`; `draft/suggestions.py:58-63`; `tournament_balancer/src/quality_harness.rs:98-99` (bench) | **ДА**, двумя способами. (1) Для flex без ранга балансер даёт 5000, драфт — 0. (2) Для игрока с одной приоритетной ролью и двумя играбельными балансер даёт 0/100/200, драфт — 0/1000/1000: `preference_order` в драфте несёт **только** primary (`rpc/draft.py:424`, `selection.py:420`), а балансер строит полный порядок из `priority` (`player_loader.py:44`). `forced` это скрывал (везде нули), режим `all_roles` делает видимым у каждого регистранта. Закреплено `TestDiscomfortDivergesFromTheBalancer` |
| **Кто оценивается по макс-ранку** | 3 | `tournament-service/.../_common.py` (`all_roles_required`); `balancer-service/.../draft/lifecycle.py` (`_all_roles_required`); `frontend/.../workspace-helpers.ts` (`ratesByMaxRank`) | Нет: закреплено `test_forced_flex_parity.py` ↔ `forced-flex-parity.test.ts` на общих фикстурах `docs/superpowers/fixtures/forced-flex-eff-rank.json`. Само сплющивание — ещё одна пара: `_map_registration` ↔ `flattenRolesToMaxRank` |
| **Off-role** | 4 | `result_serializer.py:72` (канон); `feasibility_analyzer.py:130-136`; `admin/balance_analytics.py:132-137`; `quality_harness.rs:98-99` | **ДА** (баг 6) |
| **`can_play` / playable роли** | 7 | `entities.py:60`; `context.rs:100`; `feasibility_analyzer.py:79,133`; `draft/selection.py:279-289` (два варианта); `draft/feasibility.py:137-140`; `rpc/draft.py:419-422` (инлайн-дубль) | **ДА**, двумя независимыми способами (баг 10) |
| **Ключи конфига балансера** | 10 | `defaults.py:15-149`; `public_contract.py:10-46`; `provider.py:16-52`, `:55-89`, `:97+`; `schemas/balancer.py:6-105`; `presets.py`; `moo_backend.py:49-84`; `tournament_balancer/src/lib.rs:88-160`; `frontend/.../balancer.types.ts:5-43,107-149`; `balancer-config-helpers.ts:20-29` | **ДА** (баги 7, 8) |
| **Веса влияния роли** | 4 | `draft/suggestions.py:19-22`; `tournament_balancer/src/lib.rs:16-24`; `config/defaults.py:93-95`; bench/test-фикстуры | Числа совпадают (1.4/1.0/1.1), но драфт игнорирует override (баг 9) |
| **Division grid** | 2 | `shared/division_grid.py:120` (`_build_default_grid`); `frontend/src/lib/division-grid.ts:12` (построчный порт: тот же `bases`, та же формула `offset=(5-tier)*100`, тот же URL иконок, та же сортировка) | Нет |
| **OW2 rank mapping** | 2 | `parser-service/.../overwatch_rank/mapping.py:24,50`; `frontend/src/lib/ow-rank-mapping.ts:20,30` | Нет |
| **Регекс BattleTag** | 4 | `app-service/src/core/config.py:9`; `parser-service/src/core/config.py:10`; `frontend/.../registration/validation.ts:39`; `frontend/.../form/_components/formConfig.ts:28` | Нет, но `buildRegex:63` использует `^(?:p)$` против Python `fullmatch` |
| **Правило подписок** | 2 | `shared/subscriptions/requirement.py`; `frontend/src/lib/subscription-requirement.ts` («TypeScript port of…») | **ДА** (баг 15) |
| **Статусы регистрации** | 2 | `shared/balancer_registration_statuses.py:31`; `frontend/src/lib/balancer-statuses.ts:4` | **ДА** (баг 16) |
| **Каталог прав RBAC** | 2 | `shared/rbac/catalog.py:33`; `frontend/src/hooks/usePermissions.ts:8,37` | **ДА** (баг 12) |
| **Метрики тайбрейкеров** | 2 | `standings/service.py:34,283`; `frontend/src/lib/tiebreakers.ts:8,20,30` | **ДА** (баг 13) |
| **Окна регистрации/чек-ина** | 2 | `registration/windows.py:17,32`; `frontend/src/lib/tournament-status.ts:139,157` | Есть риск: TS использует `Date.now()` вместо UTC и жёстко хардкодит `completed`/`archived` |
| **Роли и их коды** | 2 | `shared/domain/player_sub_roles.py:22-32`; `frontend/src/lib/roles.ts:38-47` | **ДА** (баг 11) |
| **`MAX_AVATAR_SIZE`** | 2 | `shared/clients/s3/upload.py:12` («keep in sync with frontend MAX_AVATAR_BYTES»); `frontend/src/lib/avatar.ts:8` | Нет |
| **`DEFAULT_MAX_TOP_HEROES`** | 2 | `shared/hero_catalog.py:20`; `frontend/.../UnifiedRegistrationForm.tsx:179` (литерал `5`) | Нет |
| **`VetoUnavailableReason`** | 2 | `encounter/veto_session.py:41-42` — бэкенд объявляет зеркалом **себя**: «mirrors the frontend's VetoUnavailableReason union»; `frontend/src/types/tournament.types.ts:167` | Нет |
| **Предикат пула балансера** | 3 | `draft/lifecycle.py:501-527` (`load_pool`); `registration/export.py:63-81` («Mirror the panel's in balancer rule»); `frontend/.../workspace-helpers.ts:432` | Условия дословно совпадают; расходятся только `nullslast` и eager-load |
| **Командные агрегаты** | 3 | `entities.py:126-197`; `tournament_balancer/src/objectives.rs:47-137`; `result_serializer.py:75-86` (третий независимый пересчёт `sub_role_collision_count`) | Формулы совпадают; `low_rank_pairs` есть только в Rust |
| **Перечисления** | ~15 | `shared/core/enums.py:206-286` ↔ `frontend/src/types/draft.types.ts:3-10` (файл признаётся: «mirror the balancer-service DTOs»), `tournament.types.ts`, `tournament-status.ts:20,116` | `DraftRoundRule` вообще без TS-аналога |

---

## Что в репозитории уже есть как образец

| Жанр | Пример | Применимо к |
|---|---|---|
| **Кодоген** | `backend/scripts/export_openapi_schemas.sh` — 6 сервисов → merge → 939 КБ манифеста, 9.5с | Класс A |
| **Контракт-тест канона против рукописного артефакта** | `shared/tests/test_gateway_raw_sql_matches_models.py`, `test_subscription_migration_matches_models.py`, `test_mtchlog001_migration_matches_models.py`, `test_encres0001_migration_matches_models.py` | Класс D там, где дедуп невозможен (Python↔Rust) |
| **Server-driven конфиг** | `tournament-service/src/schemas/encounter_report_form.py:32,64` — `REPORT_BUILT_IN_FIELDS` и `DEFAULT_BUILT_IN_FIELDS` живут только на бэке и приходят на фронт готовым конфигом | Класс D. Прямая противоположность `formConfig.ts:35` |
| **Config-driven дедупликация** | `shared/rpc/crud.py` — `CrudDispatcher`/`EntityConfig`: уникальный CRUD сворачивается в конфиг вместо рукописных хендлеров | Класс B |
| **Удаление, а не обобщение** | Решение D12 (`docs/plans/2026-08-03-admin-match-surfaces-design.md:162`): parser-копия `finalize.py` удаляется | Класс C |

## Направление зеркал: `shared/` → сервисы здоровое

Поиск `^class \w+\((db\.)?(TimeStamp\w*|Base)` по `src/` всех семи сервисов дал
**0 совпадений**. `parser-service/src/models/` и `tournament-service/src/models/` —
единственный `__init__.py` с реэкспортом. `identity-service/src/schemas/rpc.py` —
трёхстрочный shim над `shared.schemas.rpc`. **Ни один сервис не держит собственной
копии shared-модели или shared-хелпера.** Все 62 зеркала лежат в направлении
сервис↔сервис, модуль↔модуль или бэкенд↔фронтенд.

## Попутно найденный мёртвый код

| Что | Доказательство |
|---|---|
| `parser-service/src/services/admin/team.py` | 274 строки, см. таблицу выше |
| `parser-service/src/worker/` целиком | `__init__.py:1` импортирует свои tasks, но сам пакет не импортирует никто. Внутри: `tasks/encounter.py:6 bulk_create()` — второй, мёртвый путь к challonge-импорту; `tasks/team.py:10 create_from_folder()`; `tasks/team.py:33 bulk_create_from_challonge()` — сразу `raise RuntimeError` |
| `parser-service/.../challonge/sync.py:140 close_redis` | Не вызывается: `serve.py:197` зовёт одноимённую функцию из `overwatch_rank/tasks.py:49`. **Утечка Redis-клиента при shutdown** |
| `parser-service/.../team/service.py:309 construct_player` | Само-документирован: «unreferenced anywhere in the codebase» |
| `frontend/src/types/registration.types.ts:263` | Второе объявление `StatusMeta` |
| 7 из 9 модулей `parser-service/src/services/admin/` | Живы только `settings` (`src/rpc/misc.py:22`) и `stage` (`services/admin/tournament.py:20`) — требует проверки тем же методом |

## Инфраструктура тестов (проверено запуском)

Во фронтенде **два раннера**:

| Раннер | Команда | Кто |
|---|---|---|
| bun | `cd frontend && bun test <файл>` | файлы с `import ... from "bun:test"` и самописными харнессами (`workspace-helpers.test.ts`, `RoleStep.behavior.test.tsx`) |
| vitest | `cd frontend && bunx vitest run <файл>` | только файлы из allowlist `vitest.config.ts:19-63` |

`include` в `vitest.config.ts` — **allowlist**: файл вне него не запустится, а suite
отрапортует зелёным (`:30-32` предупреждает об этом). Пакетный менеджер — bun
(`bun.lock`, pnpm-lock отсутствует).

Бэкенд: `cd backend/<service> && uv run pytest <файл>`.

## Замечание об инструментах

Shell `diff` в этой сборке **ненадёжен**: вернул «0 различающихся строк» для файлов с
разными md5 и разной длиной (`analytics-service/src/rpc/_common.py` 147 строк vs
`parser-service/src/rpc/_common.py` 143 строки). Все структурные сравнения в этом
реестре сделаны через Python `difflib`/`ast`.
