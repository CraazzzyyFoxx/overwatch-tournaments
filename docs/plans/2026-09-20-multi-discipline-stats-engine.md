# Мультидисциплинарность: роли и статистический движок

Point-in-time intention. Факты о текущей системе: [`../business-logic-inventory.md`](../business-logic-inventory.md),
[`../architecture.md`](../architecture.md), [`../../backend/ARCHITECTURE.md`](../../backend/ARCHITECTURE.md).
Не читать как описание работающей системы.

Развивает и **не отменяет** [`2026-09-13-decouple-stats-from-tournament.md`](./2026-09-13-decouple-stats-from-tournament.md):
его Phase 1 входит сюда как B1, его запрет «new database, new ORM» (`:38`) остаётся в силе.
Расходимся с ним в одном: он запрещает и отдельный namespace (`rpc.stats.*`), а здесь namespace вводится —
потому что шов, который он описывает, без имени на проводе не держится дольше одного релиза.

---

## 0. Область

**В этой итерации:**

1. Сущность **дисциплины** (игры) и per-discipline словарь ролей вместо `HeroClass`.
2. Отделение статистики от турнирного движка: один namespace `rpc.stats.*`, ядро + доменные слои по дисциплинам,
   парсер перестаёт писать состояние серии.
3. Фронтенд: словарь ролей становится данными; реестр доменных слоёв по дисциплинам с ленивой загрузкой.

**Явно не сейчас** (§11): per-discipline каталоги героев/карт/режимов, второй рейтинговый ладдер,
смена типа `matches.statistics.name`, Module Federation, перенос analytics.

---

## 1. Проблема

Overwatch зашит в платформу на четырёх уровнях:

| Уровень | Где | Цена второй игры |
| --- | --- | --- |
| Словарь ролей | `backend/shared/core/enums.py:7-64` (`HeroClass`) + нативный PG-тип `heroclass` на трёх колонках трёх схем (`backend/migrations/versions/initial_v6.py:294,385,2213`) | Enum из 4 членов не выражает чужую ролевую модель; `.parse()` отвергает всё остальное |
| Словарь статов | `enums.py:181-207` (`LogEventType`, 26 членов, среди них `mercy_rez`, `gravitic_flux`, `earthshatter`), `enums.py:211-262` (`LogStatsName`, 43 члена) | Закрытые enum'ы, никакого реестра форматов |
| Парсер | `backend/parser-service/src/services/match_logs/flows.py:46` — `_LOG_EVENT_TYPE_BY_VALUE`, закрытый lookup; `MatchLogProcessor` вызывается безусловно для любого загруженного файла | Ровно один парсер для ровно одного формата |
| Фронтенд | `frontend/src/lib/player-role.ts` + **вторая независимая таблица** `frontend/src/lib/roles.ts` + ~35 файлов с собственными inline-картами ролей | Пять копий словаря, каждая молча ломается на незнакомой роли |

И статистика размазана по **четырём** сервисам, ни один из которых её не «владеет»:

| Сервис | Что от статистики держит | Цитата |
| --- | --- | --- |
| `parser-service` | приём и парсинг логов, `matches.*`, `achievements.*`, impact/MVP | `serve.py:139-144`, `flows.py` |
| `tournament-service` | сырой SQL по `matches.statistics` для публичной страницы матча, dashboard-счётчики героев/карт/режимов | `src/services/encounter/service.py:753-814`, `src/schemas/statistics.py` |
| `app-service` | лидерборды, hero playtime, per-user hero/map статистика | `gateway/internal/app/routes.go:22-23,36-40,64-67` |
| `analytics-service` | рейтинги, ML, аномалии | `src/worker/job_runner.py` |

Плюс обе стат-стороны импортируют турнирные модели пачкой:
`backend/parser-service/src/models/__init__.py:23-30` и `backend/analytics-service/src/models/__init__.py:20-26` —
`from shared.models.tournament.{challonge,computation,encounter,encounter_link,stage,standings,team,tournament} import *`.
Это не нарушение (`backend/ARCHITECTURE.md:292-297` разрешает читать чужие таблицы), но это **неисчислимая** связность:
никто не может сказать, что именно статистике нужно от турнира.

---

## 2. Словарь

| Термин | Значение | Почему так |
| --- | --- | --- |
| **Дисциплина** (`discipline`) | Игра-тайтл: Overwatch, и то, что придёт следующим. Таблица `catalog.discipline`. | Слово `game` занято: `balancer.custom_game` — одна сыгранная миксовая катка (`docs/users-identity.md:219,297,737`), маршрут `/api/v1/balancer/.../custom-games/{game_id}`, фронтовый `/balancer/mix/[gameId]`. Переименование `custom_game` дороже свободного слова. В UI дисциплина подписывается «Игра». |
| **Роль** (`discipline_role`) | Позиция игрока в составе, определённая дисциплиной: `tank`/`damage`/`support` для OW. Хранится кодом. | |
| **`flex`** | Зарезервированный **платформенный** код слота: «слот без роли». Не строка в `discipline_role`. | Флекс — свойство состава, а не игры: любой дисциплине нужен слот без фиксированной роли. Так `discipline_role` остаётся чистым списком настоящих ролей. |
| **Стат-движок** | Код, отвечающий на «что произошло на сыгранной карте и насколько хорош был игрок». Namespace `rpc.stats.*`. | Формулировка из `2026-09-13-decouple-stats-from-tournament.md:12`. |
| **Турнирный движок** | Код, отвечающий на «кто с кем играет, в какой серии, кто проходит дальше». Namespace `rpc.tournament.*`. | Там же, `:11`. |
| **Доменный слой дисциплины** | Каталог `disciplines/<slug>/` внутри стат-движка: парсер, словарь статов, формула импакта, специфичные листья ачивок. **Не отдельный процесс и не отдельный пакет сервиса.** | Требование постановки. |

Остальная терминология — из [`../glossary.md`](../glossary.md) дословно: workspace, tournament, stage, encounter, match,
roster, roster shape, slot, division. Ничего из этого не переопределяется.

---

## 3. Принятые решения

| # | Решение | Обоснование |
| --- | --- | --- |
| 1 | Сущность игры называется `discipline` | `game` занято `balancer.custom_game` |
| 2 | Источник правды для ролей и статов — **код доменного слоя**; БД (`catalog.discipline_role`, `catalog.stat`) — идемпотентно синхронизируемая проекция | Прецедент: RBAC-каталог — данные в `backend/shared/rbac/catalog.py`, применение через `ensure_permission_catalog` (`backend/shared/rbac/bootstrap.py:13-34`). Только БД → словарь ломается из админки; только код → фронт и SQL не могут джойнить |
| 3 | `tournament.player.role`: нативный enum `heroclass` → `varchar(32)` | Тип общий с `catalog.hero.type` и `matches.stat_baselines.role`; `ALTER TYPE ADD VALUE` протащил бы чужие роли в таксономию героев OW. Таблица маленькая (одна строка на слот состава), rewrite дешёвый |
| 4 | `HeroClass` остаётся в `shared/core/enums.py`, но сужается до «класс героя Overwatch»; `slot_code`/`from_slot_code`/`parse` удаляются | Две shared-модели (`catalog.hero.type`, `matches.stat_baselines.role`) на нём висят — переносить enum некуда. Меняется смысл, не место |
| 5 | Процессы: код стат-движка консолидируется в **одном пакете**; воркеры делятся **по нагрузке**, не по домену: тяжёлый ingest (`serve.py`) и лёгкий RPC (`serve_rpc.py`) | Ровно так уже сделан analytics: `analytics-service/serve.py` (ML-воркер) vs `serve_rpc.py` (`rpc.analytics.*`). Складывать горячие публичные чтения в процесс, который парсит логи через pandas — латентность под GIL |
| 6 | Граница к турниру: `shared/services/stats_context/` — узкий read-port, одна БД, контракт через `.importlinter` | `backend/ARCHITECTURE.md:126` («awaits a session and two+ services need it → `shared/services/`»). RPC на каждое чтение — N+1 по сети в горячем цикле ачивок; `2026-09-13:38` это запрещает и прав |
| 7 | Схема `overwatch` → `catalog` (`ALTER SCHEMA`) | Python-пакет **уже** `shared/models/catalog/`, ключ ERD не меняется (`backend/scripts/export_erd.py`, `package_of_module`) |
| 8 | `matches.statistics.name` остаётся нативным enum | 27 млн строк, 425 МБ (`backend/shared/models/matches/match.py:132-145`), сырой предикат индекса `name = 'HeroTimePlayed'` (`match.py:120-128`). Вторая дисциплина — `ALTER TYPE ADD VALUE`, без rewrite. Отложенный потолок, записан в §11 |
| 9 | Фронтенд: реестр `src/games/<slug>/` + `next/dynamic`, один пакет | `docs/frontend-zones.md:3-8`: «It is **one** Next deployable… It is not a micro-frontend architecture and does not need to be». Там же `:78-102` — четыре single-instance блокера любого сплита и вывод, что дешёвая форма — Next multi-zone, **не** Module Federation. Прецедент ленивой загрузки: 17 боевых `next/dynamic` |
| 10 | HTTP-пути **не меняются** при переезде в `rpc.stats.*` — меняется только `RouteSpec.Queue` | Ноль изменений во фронте, в respcache-правилах и в закладках пользователей |
| 11 | **Без `Protocol`-интерфейса `DisciplineModule`** | `backend/ARCHITECTURE.md:314-316`: «Do not add a container, a factory registry, or a `Protocol`-based interface for a service that has exactly one implementation». Вместо него — каталог `disciplines/<slug>/` (граница упаковки) и три маленьких реестра-словаря там, где диспетч реально нужен в рантайме, по образцу уже принятого `_REGISTRY` в `engine/conditions/__init__.py` |

Решения 1 и 3 — двери в одну сторону. Остальное обратимо.

---

## 4. Целевая архитектура

### 4.1 Процессы и неймспейсы

```
                       ┌─────────────────────────────────────────┐
  HTTP/WS ── gateway ──┤ rpc.tournament.*  tournament-svc         │  кто с кем играет
   (единственный       │ rpc.app.*         app-svc                │  каталог, профили, workspace
    ingress)           │ rpc.stats.*       stats-svc + stats-worker│ что произошло на карте
                       │ rpc.analytics.*   analytics-svc/worker    │  рейтинги, ML
                       │ rpc.balancer.*    balancer-svc            │
                       │ rpc.identity.*    identity-svc            │
                       └─────────────────────────────────────────┘
```

`rpc.stats.*` — «единый шлюз общей статистики»: одно имя на проводе, один пакет кода, один набор route-таблиц
(`gateway/internal/stats/`). Два процесса за ним — по профилю нагрузки, не по домену:

| Процесс | Entrypoint | Что держит |
| --- | --- | --- |
| `stats-worker` | `serve.py` (нынешний parser-svc) | очереди `UPLOAD_MATCH_LOG_QUEUE`, `PROCESS_MATCH_LOG_QUEUE`, `PROCESS_TOURNAMENT_LOGS_QUEUE`, `ACHIEVEMENT_EVALUATE_QUEUE(_DEFERRED)`, `RANK_FETCH_QUEUE`; шедулеры (`serve.py:206-214`) |
| `stats-svc` | `serve_rpc.py` (новый) | все `rpc.stats.*` читающие подписчики |

### 4.2 Слои внутри стат-движка

```
backend/parser-service/            (переименование каталога — B8, опционально)
├── serve.py                       воркер: очереди + шедулеры
├── serve_rpc.py                   RPC-процесс: только rpc.stats.*
├── src/
│   ├── rpc/                       ТРАНСПОРТ. register(broker, logger), один @broker.subscriber на метод
│   │   ├── stats_match.py         rpc.stats.match.*
│   │   ├── stats_player.py        rpc.stats.player.*
│   │   ├── stats_leaderboard.py   rpc.stats.leaderboard.*
│   │   ├── stats_achievement.py   rpc.stats.achievement.*
│   │   ├── stats_catalog.py       rpc.stats.catalog.*
│   │   ├── logs.py rank.py misc.py subscription.py     остаются rpc.parser.*
│   ├── services/
│   │   ├── core/                  ИГРО-НЕЗАВИСИМО
│   │   │   ├── ingest/            приём файла, дедуп, LogProcessingRecord, S3, реаппер
│   │   │   ├── persistence/       запись Match/MatchStatistics/KillFeed/Event, delete-and-reinsert
│   │   │   ├── reads/             агрегации, лидерборды, покрытие логами
│   │   │   └── achievements/      обход дерева, реестр листьев, differ, runner, ~20 агностичных листьев
│   │   └── disciplines/
│   │       └── overwatch/         ДОМЕННЫЙ СЛОЙ ИГРЫ
│   │           ├── definition.py  RoleSet + StatSpec[] (источник правды для сида)
│   │           ├── parser.py      MatchLogProcessor → parse(raw, ctx) -> ParsedMatch
│   │           ├── impact.py      формула MVP/импакта
│   │           ├── baselines.py   stat_baselines
│   │           └── achievements/  10 дисциплино-зависимых листьев (§6.3)
│   └── domain/                    ЧИСТАЯ ЛОГИКА (без session, без await)
└── (registries)                   три словаря slug -> объект, §4.5
```

Правила размещения — `backend/ARCHITECTURE.md:20-58,119-132` дословно. Ничего нового не изобретается:
`rpc/` только декодирует и гейтит, `services/` оркестрирует и берёт `session` параметром,
`domain/` не знает про сессию, таблицы живут в `shared/models/`.

### 4.3 Данные

Новые таблицы, схема `catalog` (после переименования из `overwatch`), все на `db.TimeStampIntegerMixin`
(`id BigInteger PK`, `created_at`, `updated_at` — `backend/shared/core/db.py`):

```
catalog.discipline
  slug        varchar(32)  uq_discipline_slug
  name        varchar(64)
  short_name  varchar(16)
  icon_path   varchar(255)
  is_active   bool  server_default true
  sort_order  smallint server_default 0

catalog.discipline_role
  discipline_id  FK catalog.discipline.id  ON DELETE CASCADE
  code           varchar(32)      -- каноническое написание на проводе и в хранении
  label          varchar(64)      -- дефолт, если нет перевода
  icon_path      varchar(255)
  tint           varchar(32) null -- имя CSS-токена, см. §5.8
  sort_order     smallint
  is_active      bool server_default true
  uq_discipline_role_discipline_code (discipline_id, code)

catalog.stat
  discipline_id  FK catalog.discipline.id  ON DELETE CASCADE
  code           varchar(64)      -- для OW равен LogStatsName.name
  label          varchar(128)
  direction      varchar(4)       -- 'asc' | 'desc'; ck_stat_direction
  unit           varchar(16) null -- 'count' | 'seconds' | 'percent' | 'points'
  is_derived     bool             -- считается парсером, а не приходит из лога
  sort_order     smallint
  uq_stat_discipline_code (discipline_id, code)
```

Изменения существующих:

| Таблица.колонка | Было | Стало | Примечание |
| --- | --- | --- | --- |
| `tournament.tournament.discipline_id` | — | FK `catalog.discipline.id`, nullable → бэкфилл → NOT NULL | |
| `public.workspace.default_discipline_id` | — | FK `catalog.discipline.id`, nullable | по образцу `default_roster_slots_json` / `default_division_grid_version_id` |
| `tournament.player.role` | `Enum(HeroClass)` nullable | `varchar(32)` nullable | `USING role::text`. SQLAlchemy `Enum` хранит **имена** членов (`enums.py:19-20`), значит в БД уже лежит `tank`/`damage`/`support`/`flex` — это ровно код роли. Данные не меняются, меняется тип |
| `catalog.hero.type` | `Enum(HeroClass)` + CHECK `ck_hero_type_not_flex` | без изменений | смысл сужается до «класс героя OW» |
| `matches.stat_baselines.role` | `Enum(HeroClass)` + CHECK `ck_stat_baselines_role_not_flex` | без изменений | инфраструктура импакта OW, уезжает в доменный слой как код, не как схема |
| `matches.statistics.name` | `Enum(LogStatsName)` | без изменений | §3 решение 8 |
| `log_processing.record` | — | без изменений | дисциплина выводится через `tournament_id → tournament.discipline_id`, один join (`backend/shared/models/ingestion/log_processing.py:45-70`) |

Единственный индекс/констрейнт, трогающий `player.role` — составной
`Index("ix_player_tournament_role_sub_role", "tournament_id", "role", "sub_role")`
(`backend/shared/models/tournament/team.py`). CHECK'а на `player.role` нет (`flex` там легален).

Имена констрейнтов пишутся руками: `naming_convention` в `backend/shared/core/db.py` отсутствует.
Соблюдаем наблюдаемое: `uq_<table>_<cols>`, `ix_<table>_<cols>`, `fk_<table>_<col>`, `ck_<table>_<invariant>`.

### 4.4 Граница к турнирному движку

`backend/shared/services/stats_context/` — единственный разрешённый способ для стат-кода читать турнирные таблицы.
Класс + модульный синглтон (`ARCHITECTURE.md:299-316`), `session` первым параметром каждого метода:

```python
class StatsTournamentContext:
    async def discipline_of_tournament(self, session, tournament_id: int) -> DisciplineRef
    async def encounter_frame(self, session, encounter_id: int) -> EncounterFrame
        # tournament_id, workspace_id, home_team_id, away_team_id, discipline_id
    async def eligible_members(self, session, tournament_id: int) -> list[MemberRef]
        # заменяет get_all_eligible_users / get_eligible_keys
        # (parser-service/src/services/achievement/engine/conditions/__init__.py:97-171)
    async def team_members(self, session, team_id: int) -> list[MemberRef]
    async def competitive_facts(self, session, tournament_id, member_ids) -> list[CompetitiveFact]
        # placement, дошёл ли до плей-офф, ветка сетки — для листьев ачивок

stats_context = StatsTournamentContext()
```

`DisciplineRef`/`EncounterFrame`/`MemberRef`/`CompetitiveFact` — dataclass'ы в
`backend/shared/domain/stats_context.py` (чистые, §4.2). ORM-строки наружу не отдаются: иначе порт становится
тем же wildcard-импортом, только с лишним файлом.

Гейт — `backend/parser-service/.importlinter` и `backend/analytics-service/.importlinter`, контракт типа `forbidden`:

```ini
[importlinter:contract:stats-tournament-boundary]
name = Stats code reaches tournament tables only through stats_context
type = forbidden
source_modules = src
forbidden_modules =
    shared.models.tournament
    shared.repository.tournament
ignore_imports =
    src.services.tournament.service -> shared.repository.tournament
```

`ARCHITECTURE.md:342-348` предупреждает не вешать `.importlinter` на плоский сервис ради слоёв. Здесь контракт не про
слои, а про один запрет, и он нужен: без него wildcard-импорт вернётся следующим PR. Нарушения, которые переживают
фазу B, перечисляются поимённо в `ignore_imports` — так же, как `PENDING_REPOSITORY_MIGRATION`
(`ARCHITECTURE.md:330-334`), то есть как долг, который видно.

### 4.5 Три реестра

Только там, где диспетч нужен в рантайме. Форма — принятая в репозитории (`engine/conditions/__init__.py`):

```python
# src/services/disciplines/__init__.py
_PARSERS: dict[str, LogParser] = {}
_ROLE_SETS: dict[str, RoleSet] = {}
_STAT_CATALOGS: dict[str, tuple[StatSpec, ...]] = {}

def register_discipline(slug: str, *, parser, roles, stats) -> None: ...
def parser_for(slug: str) -> LogParser: ...   # KeyError -> 422 "unsupported_discipline"
```

`src/services/disciplines/overwatch/__init__.py` вызывает `register_discipline("overwatch", ...)` на импорте;
`src/services/disciplines/__init__.py` импортирует все подпакеты. Ровно один вызов, ровно один словарь на сущность,
никакого DI-контейнера.

---

## 5. Фаза A — дисциплина и роли

Полный цикл: миграция → модели → домен → сид → сервис+кэш → RPC → шлюз → OpenAPI → фронт → i18n → ассеты → тесты → доки.

### A1. Миграции

Четыре ревизии, в этом порядке. Заголовок каждой — по образцу
`backend/migrations/versions/enclogsrm1_drop_encounter_has_logs.py`
(`revision`, `down_revision`, `branch_labels`, `depends_on`).

**`catsch001_rename_overwatch_schema_to_catalog`**
```python
op.execute("ALTER SCHEMA overwatch RENAME TO catalog")
```
Блокировки берутся заранее по образцу `_take_locks()` из
`backend/migrations/versions/regteam0004_roster_admission_subscription.py`
(`RETRYABLE_SQLSTATES = {"55P03","40P01"}`, `LOCK_TIMEOUT="3s"`, `LOCK_ATTEMPTS=40`, вложенный SAVEPOINT):
`LOCK TABLE overwatch.hero, overwatch.map, overwatch.gamemode, overwatch.catalog_alias_miss IN ACCESS EXCLUSIVE MODE`.
`ALTER SCHEMA` переносит и объекты, и FK — ничего доправлять в БД не нужно.
`downgrade` — обратный `ALTER SCHEMA`.
Схему `overwatch_rank` **не трогаем**: это другой ограниченный контекст (`shared/models/ranks/overwatch_rank.py:26`),
свой Python-пакет `parser-service/src/{domain,services}/overwatch_rank/`, шесть своих миграций.
Слепой `sed s/overwatch/catalog/` его сломает.

**`disc0001_discipline_catalog`** — три новые таблицы (§4.3) + сид Overwatch литеральными `INSERT`.
Сид в миграции — неизменяемый снимок: миграции не импортируют код приложения, потому что код уезжает, а миграция нет.

**`disc0002_tournament_discipline`**
```python
op.add_column("tournament", sa.Column("discipline_id", sa.BigInteger(), nullable=True), schema="tournament")
op.add_column("workspace", sa.Column("default_discipline_id", sa.BigInteger(), nullable=True))
op.execute("UPDATE tournament.tournament SET discipline_id = (SELECT id FROM catalog.discipline WHERE slug='overwatch')")
op.alter_column("tournament", "discipline_id", nullable=False, schema="tournament")
op.create_foreign_key("fk_tournament_discipline_id", ...)
```
Бэкфилл в той же ревизии: на момент миграции в системе одна дисциплина, ветвиться не на чем.

**`plrole001_player_role_varchar`**
```python
_with_lock_retry(lambda: op.alter_column(
    "player", "role",
    existing_type=postgresql.ENUM(name="heroclass"),
    type_=sa.String(length=32),
    postgresql_using="role::text",
    existing_nullable=True,
    schema="tournament",
))
```
`_with_lock_retry` — дословно из `enclogsrm1_drop_encounter_has_logs.py` (`SET LOCAL lock_timeout`, вложенный SAVEPOINT,
backoff, ретрай только на `55P03`). Тип `heroclass` **не удаляется**: на нём остаются `catalog.hero.type` и
`matches.stat_baselines.role`. Составной индекс `ix_player_tournament_role_sub_role` Postgres перестроит сам.
`downgrade` — обратный `USING role::heroclass`; данные совпадают по написанию, поэтому обратим без потерь.

В репозитории **нет прецедента** ALTER'а enum-колонки в строку (`graft` по `ALTER TYPE|ALTER COLUMN.*TYPE` по всем 70
миграциям дал только `annstat01:57`, добавление значения). Ревизия обязана нести комментарий с обоснованием
и проверяться на копии продовой базы до мержа.

### A2. Модели

`backend/shared/models/catalog/discipline.py` — `Discipline`, `DisciplineRole`, `Stat`, `__table_args__ = ({"schema": "catalog"},)`.
`hero.py`, `map.py`, `gamemode.py`, `alias_miss.py`: `"overwatch"` → `"catalog"` в `schema=`.
FK-строки `"overwatch.<table>.id"` → `"catalog.<table>.id"` в 10 файлах
(`matches/match.py:64`, `tournament/encounter_report.py:114,150`, `balancer/custom_game.py:51`, `balancer/casual.py:19`,
`balancer/registration/registration.py:317` и далее).
`tournament/team.py`: `role: Mapped[str | None] = mapped_column(String(32), nullable=True)`.
`tournament/tournament.py`: `discipline_id` + `discipline: Mapped[Discipline] = relationship()`.

Сырой SQL со схемой в тексте: `backend/scripts/migrate_overwatch_images.py` (5 мест) и строка DDL матвью
`mv_hero_global_stats` (`initial_v6.py:88`, `JOIN overwatch.map mp` — матвью пересоздаётся отдельной ревизией
или остаётся: `ALTER SCHEMA` переименует и её зависимости, но текст определения в старой миграции менять нельзя).
Тесты с литералом схемы: `parser-service/tests/test_catalog_aliases.py:42,60,61,68`,
`test_scrim_achievement_isolation.py:90-92`, `app-service/tests/test_user_compare_performance_contract.py:221,227`
(там ассерты на подстроку `"JOIN overwatch.map"` — правятся текстуально).
`frontend/src/app/(site)/docs/diagrams.ts` — рукописная ERD-диаграмма в доках, 10 мест, `export_erd.py` её не покрывает.

### A3. Доменный слой ролей

`backend/shared/domain/roles.py` — чистый модуль (`ARCHITECTURE.md:197-217`):

```python
FLEX_SLOT_CODE: Final[str] = "flex"          # переезжает сюда из roster_shape.py

@dataclass(frozen=True)
class Role:
    code: str; label: str; icon_path: str; tint: str | None; sort_order: int

@dataclass(frozen=True)
class RoleSet:
    discipline_slug: str
    roles: tuple[Role, ...]                   # без flex

    @property
    def codes(self) -> frozenset[str]: ...
    @property
    def slot_codes(self) -> frozenset[str]: ...   # codes | {FLEX_SLOT_CODE}
    def normalize(self, value: object) -> str | None: ...   # регистронезависимо, без алиасов
    def order_of(self, code: str) -> int: ...
```

`normalize` — строгая граница, как нынешний `HeroClass.parse` (`enums.py:51-59`): без алиасов, `None` вместо исключения.
Кому нужны свободные синонимы (маппинг импорта из Google Sheets) — держит свою таблицу, как и сейчас.

Что удаляется:

| Символ | Файл | Замена |
| --- | --- | --- |
| `HeroClass.slot_code`, `.from_slot_code`, `.parse` | `shared/core/enums.py:34-64` | `RoleSet.normalize`; docstring `HeroClass` переписывается на «класс героя Overwatch» |
| `ROSTER_SLOT_CODES`, `RosterSlotCode`, `RegistrationRoleCode` | `shared/domain/roster_shape.py:41-52` | `RoleSet.slot_codes` / `.codes`; на проводе `str` |
| `REGISTRATION_ROLE_CODES`, `REGISTRATION_TO_CANONICAL`, `normalize_role` | `shared/domain/player_sub_roles.py:13-27` | `RoleSet` |
| `DEFAULT_ROSTER_SLOTS` | `roster_shape.py:54` | дефолт состава дисциплины (`definition.py`) |
| `resolve_slot_role` | `shared/services/team_export/materialization.py:63-85` | прямая запись кода слота в `player.role` после валидации по `RoleSet` |

`parse_roster_slots(slots, *, slot_codes: frozenset[str])` — словарь кодов становится параметром
(`roster_shape.py:161-192`). 50 вызовов в 22 файлах, из них большинство — тесты балансера; правка механическая.
`resolve_roster_shape` получает третью ступень фоллбэка: **турнир → workspace → дефолт дисциплины**
(было: турнир → workspace → «built-in Overwatch 5v5»).

Плата: Pydantic-контракты теряют `Literal["tank","damage","support","flex"]` и, значит, enum в OpenAPI.
Валидация переезжает в сервисный слой, где дисциплина известна. Это не деградация, а перенос в правильный слой:
`Literal` был верен ровно до второй дисциплины. Компенсация — список ролей едет в payload'е турнира (A7).

Rust-солвер не трогаем: `backend/balancer-service/native/tournament_balancer/src/context.rs:7-40` уже работает с
`Vec<String>` из ключей `role_mask`. Четыре регистронезависимых сравнения с `"Tank"/"Damage"/"Support"/"flex"`
(`context.rs:29,34,35,40`) влияют только на взвешивание импакта и остаются как есть до второй дисциплины —
для неё они молча дадут нейтральный вес, а не ошибку.

### A4. Сид

Данные — в `src/services/disciplines/overwatch/definition.py`:

```python
OVERWATCH = DisciplineSpec(
    slug="overwatch", name="Overwatch", short_name="OW", icon_path="/disciplines/overwatch.svg",
    roles=(Role("tank", "Tank", "/roles/overwatch/tank.png", "tank", 0), ...),
    default_roster_slots={"tank": 1, "damage": 2, "support": 2},
    stats=(StatSpec("Eliminations", "Eliminations", "desc", "count", False, 0), ...),
)
```

Применение — `backend/shared/services/discipline_catalog.py::ensure_discipline_catalog(session)`, идемпотентный
upsert по `(discipline.slug)` и `(discipline_id, code)`, дословно по форме `ensure_permission_catalog`
(`backend/shared/rbac/bootstrap.py:13-34`): выбрать существующие, вставить недостающие, обновить расходящиеся поля,
`flush()`.

**Когда запускается.** Не так, как RBAC. Ленивая схема RBAC («за `ensure_workspace_system_roles`») уже один раз
выстрелила: `backend/migrations/versions/mixperm01_custom_game_permission.py:8-12` описывает, как workspace'ы с
устоявшимся членством никогда не добирали новые пермишены и потребовали ручного бэкфилла. Дисциплины не привязаны к
workspace, так что копировать эту схему незачем:

1. первичные строки — в `disc0001` (нужны для бэкфилла `tournament.discipline_id` в `disc0002`);
2. дальнейшие изменения кода-декларации — `ensure_discipline_catalog()` на старте `stats-svc` и `stats-worker`,
   рядом с `configure_cache()` (`ARCHITECTURE.md:350-358` перечисляет это как легальное содержимое `serve.py`).
   Прод накатывает `alembic upgrade head` до `make prod-up`, поэтому таблицы на момент старта уже есть.

### A5. Сервисы и кэш

`backend/shared/services/discipline_access.py` + `discipline_cache.py` — по образцу пары
`shared/services/division_grid/{access,cache}.py`. Форма зафиксирована как конвенция: `shared/services/roster_shape_access.py:14-15`
прямо пишет «Modelled on `division_grid_access` / `division_grid_cache` (same `CACHE_KEY_PREFIX`, same TTL,
same best-effort cache wrappers)». Третья копия — это конвенция репозитория, а не повод строить абстракцию.

```python
CACHE_KEY_PREFIX = "backend:"
ROLE_SET_CACHE_TTL_SECONDS = 60 * 60

# ключи
f"{CACHE_KEY_PREFIX}discipline:{slug}:role_set"
f"{CACHE_KEY_PREFIX}discipline:tournament:{tournament_id}:slug"
```

`_get`/`_set` — дословно по `division_grid/cache.py:198-215`: проверка `cache.is_setup()`, `try/except` с
`logger.debug`, деградация к чтению из БД. Инвалидация — точечный `cache.delete` на записи каталога плюс
`cache.delete_match(f"{CACHE_KEY_PREFIX}discipline:tournament:*:slug")` при смене дисциплины турнира.

Резолвер (`discipline_access.py`): `tournament.discipline_id → workspace.default_discipline_id → активная дисциплина по умолчанию`.

`Resource` (`backend/shared/services/realtime/resources.py:25-37`) **не расширяем**: смена каталога дисциплин — редкое
админское действие, живой мультиклиентский рефреш ему не нужен, `invalidateQueries` на стороне админки достаточно.
Добавление члена в этот enum обязало бы синхронно править четыре файла (`shared/realtime/resources.json`,
`gateway/internal/respcache/resources.go`, `frontend/src/lib/realtime-resources.ts` + сам enum) и держать parity-тест.

### A6. RPC, шлюз, OpenAPI

Чтение каталога — публичное (`EntityConfig.public_read=True`, `backend/shared/rpc/crud.py:112-149`: этот флаг ровно для
глобальных справочников без владеющего workspace). Запись — суперпользователь: дисциплины глобальны, не тенантны.

| Метод | Субъект | Auth | Маршрут |
| --- | --- | --- | --- |
| список дисциплин | `rpc.app.read.list` `Entity: "discipline"` | None | `GET /api/v1/disciplines` |
| одна дисциплина с ролями | `rpc.app.read.get` `Entity: "discipline"` | None | `GET /api/v1/disciplines/{id}` |
| роли дисциплины | `rpc.app.disciplines.roles` | None | `GET /api/v1/disciplines/{slug}/roles` |
| CRUD ролей | `rpc.app.admin.*` `Entity: "discipline_role"` | Required | `/api/v1/admin/disciplines/{id}/roles` |

Регистрация сущностей — в `REGISTRY` app-service'а (`backend/app-service/src/services/read_registry.py:181`,
`workspace/registry.py:83`), фабрики по образцу `player_sub_role_entity()`
(`backend/shared/services/player_sub_role.py:221-241`) дословно, включая `model=None`, если все действия идут через
`service_*`-хуки.

Шлюз: маршруты в `gateway/internal/app/routes.go` рядом с `/api/v1/heroes`. Кэш — `respcache.TTLOnly()` в
`gateway/internal/app/cacheable.go`: каталог меняется раз в релиз.

OpenAPI: на каждый новый субъект — ключ `"rpc.app.disciplines.roles": {...}` **в обоих**
`backend/app-service/src/openapi_docs.py` и `src/openapi_schemas.py`
(формат ключа — `DOC_KEY_RE` в `backend/scripts/check_rpc_docs.py`: строковый литерал, начинающийся с `rpc.`,
опционально `#<entity>`, затем `:`), затем `bash scripts/export_openapi_schemas.sh`. Иначе падает CI-гейт
«Every routed RPC subject is documented».

### A7. Контракт на проводе — ломающее изменение

Сегодня роль едет как `HeroClass.value`, то есть `"Tank"`. Становится `code`, то есть `"tank"`.
Это то же значение, что уже лежит в БД, и то же, что уже используют `slot_code`-поля регистрации, драфта и балансера —
после правки на проводе остаётся **одно** написание вместо двух.

Затронуты все ответы, несущие `player.role`: составы команд, участники, драфт, балансер, сравнение игроков, профиль.
Клиентский фоллбэк не нужен и не делается: фронт и бэкенд собираются из одного тега и катятся одним
`deploy-production.yml`, внешних SDK-потребителей у `player.role` нет. Компенсация — вместе с турниром едет его
`discipline` c массивом ролей, поэтому клиенту больше не нужно знать словарь заранее:

```jsonc
{ "id": 42, "slug": "owal-7",
  "discipline": { "slug": "overwatch", "name": "Overwatch",
    "roles": [ {"code":"tank","label":"Tank","icon_path":"/roles/overwatch/tank.png","tint":"tank","sort_order":0}, … ] } }
```

Так же, как `default_division_grid_version` уже приезжает внутри workspace (`frontend/src/types/workspace.types.ts:261-262`)
и читается хуком без отдельного запроса.

### A8. Фронтенд

Удаляются целиком: `frontend/src/lib/player-role.ts` (все 17 экспортов дисциплино-зависимы) и
`frontend/src/lib/roles.ts` (вторая независимая таблица ролей, 14 входящих рёбер, обслуживает балансер и драфт).
Оставлять одну из них — значит оставить две правды.

Появляется:

```
src/lib/role-set.ts        RoleSet, normalizeRole, roleOrder, roleLabelKey, roleImageSrc(discipline, code)
src/hooks/useRoleSet.ts    useRoleSet(): RoleSet — селектор zustand + useMemo + дефолт
src/games/registry.ts      slug -> () => import("./<slug>")
src/games/overwatch/       statPanels, matchView, heroRoleVariant — то, что знает про героев OW
```

`useRoleSet` пишется дословно по `useDivisionGrid` (`frontend/src/hooks/useCurrentWorkspace.ts:12-19`):
селектор к стору, `useMemo`, статический дефолт как graceful degradation. Всё это — shared-слой по
`docs/frontend-zones.md:25-35`: `src/lib`, `src/hooks`, `src/games` импортируются любой зоной и сами не импортируют
ни одной (правило Z2, `frontend-zones.md:45-48`; гейт `bun run lint:zones`).

Реестр — идиома, уже принятая в 17 боевых местах:
```ts
const OverwatchStatPanels = dynamic(
  () => import("@/games/overwatch/StatPanels").then((m) => ({ default: m.StatPanels })),
  { loading: () => <StatPanelsSkeleton /> }
);
```
(именованный экспорт + `loading` — по образцу `components/admin/MarkdownEditor.tsx:4,21` и
`app/admin/matches/page.tsx:41-69`). Turbopack сам режет чанк: неиспользуемая дисциплина не грузится.

**Чеклист миграции** — 39 файлов с прямым импортом `@/lib/player-role` плюс ~35 с собственными inline-картами.
Приоритет — файлы, дублирующие словарь (они ломаются молча, а не на типах):

| Группа | Файлы | Что делать |
| --- | --- | --- |
| Вторая таблица ролей | `lib/roles.ts` (+14 потребителей в `app/balancer/**`, `components/draft/**`) | удалить, перевести на `useRoleSet`/`role-set.ts` |
| Inline label-карты | `participantsColumns.tsx:78-81,166-169`, `ParticipantsPool.tsx:35-38`, `TournamentHistoryCell.tsx:12-34`, `TournamentParticipantsPage.tsx:174-177`, `TournamentTeamsPage.tsx:70-73`, `OverviewRoleSplit.tsx:22-25`, `OverviewTopHeroesTable.tsx:29-31`, `HeroUserStatsPopover.tsx:23-25`, `compare/constants.ts:17-20`, `UsersRedesignClient.tsx:75-78`, `mix-balancer-prefs.ts:36-39`, `TournamentsDivisionChart.tsx:21-29`, `balancer/feed/_components/mappingConfig.ts:104-109`, `ValueMapEditor.tsx:37-40,63-72`, `PlayerEditSheet.tsx:71-81` | заменить на `roleLabel(code)` из хука |
| Захардкоженные списки | `admin/content/heroes/page.tsx:33`, `draft/admin-control-model.ts:11`, `DraftCaptainsStep.tsx:42`, `DraftPoolStep.tsx:23`, `setup-model.ts:122`, `PlayerPool.tsx:39`, `balancer-page-helpers.ts:118`, `workspace-helpers.ts:23-27,95-97,392-396`, `balance-editor-helpers.ts:101-116`, `draft-workspace-model.ts:37-39` | взять из `RoleSet.codes` |
| Дефолты `"Damage"`/`"Tank"`/`"Support"` | `PlayerForm.tsx:68`, `TeamRosterEditor.tsx:74`, `useBalancerDragGhosts.ts:65-99`, `PickupLobbyPanel.tsx:291,539`, `PickupTeamsPanel.tsx:1045,1110`, `PickupAddPlayersDialog.tsx:615` | первый элемент `RoleSet.roles` |
| Дисциплино-зависимая логика | `heroVariantFromRole` и его 5 потребителей (`HeroImage.tsx`, `HeroesView.tsx`, `HeroCompareHero.tsx`, `HeroLeaderboardTable.tsx`, `HeroUserStatsPopover.tsx`) | переезжает в `src/games/overwatch/` |
| Только типы | `types/{balancer-admin,rank,user}.types.ts`, `lib/roster-shape.ts`, `PregameHeroBans.tsx`, `SharePlayerCard.tsx`, `PageHero.tsx` | `PlayerRoleOption` → `string` |
| Тесты | ~47 файлов с литералами ролей | правятся вместе со своим модулем; `roster-shape.test.ts` и `participantsColumns.test.tsx` пинят сам набор — переписываются на фикстуру `RoleSet` |

`components/admin/achievements/ConditionFlowEditor.tsx:607-612` (захардкоженные `<SelectItem value="Tank">` в редакторе
листьев ачивок) — на стыке с фазой B: список берётся из ролей дисциплины турнира.

### A9. i18n и ассеты

Новое пространство имён `disciplines`, ключи `disciplines.<slug>.roles.<code>`. Флекс-слот — платформенный, не
дисциплинный: он остаётся под существующим `common.roles.flex` (`en.json:188-192`), а три ключа рядом с ним
(`tank`/`damage`/`support`) из `common.roles.*` удаляются — они уезжают в `disciplines.overwatch.roles.*`. Правила
(`frontend/src/i18n/messages.parity.test.ts`):

- `en.json` и `ru.json` обязаны иметь **идентичные наборы ключей** — иначе CI падает. Значение-заглушка проходит,
  отсутствие ключа — нет.
- Для интерполированных ключей в репозитории есть прецедент: второй тест перечисляет значения
  `Tournament.team_formation` и требует `common.<value>` в обоих словарях. Повторяем его для кодов ролей:
  тест читает `definition.py`-эквивалент (фикстуру с кодами) и требует `disciplines.<slug>.roles.<code>` в обоих локалях.
  Роль, добавленная без переводов, роняет CI, а не деградирует в точечный ключ в проде.
- Фоллбэк писать в коде не нужно: `getMessageFallback` (`frontend/src/i18n/request.ts:35-38`) уже рендерит сам ключ.
  `label` из каталога — фоллбэк на стороне данных, для дисциплины, добавленной без релиза фронта.
- `disciplines` добавляется в `frontend/src/i18n/zone-namespaces.json` для всех трёх зон
  (`web`, `admin`, `tools` — роли рендерятся во всех). Файл **генерируется**: `bun run lint:zones --write-i18n`,
  правило Z4 гейта пересчитывает его и падает на расхождении (`docs/frontend-zones.md:122-125`).

Ассеты: `/public/roles/Tank.png|Damage.png|Support.png|Flex.svg` → `/public/roles/overwatch/{tank,damage,support}.png`
и платформенный `/public/roles/flex.svg`. `next.config.mjs` **не меняется**: это same-origin пути, `remotePatterns`
касается только внешних CDN, а `images.unoptimized: true` выключает валидацию доменов. Иконка дисциплины —
`/public/disciplines/<slug>.svg`.

### A10. Тесты

| Уровень | Что проверяем | Где |
| --- | --- | --- |
| `domain/` (без БД) | `RoleSet.normalize` регистронезависим и не принимает алиасов; `slot_codes` содержит `flex`, `codes` — нет; `parse_roster_slots` принимает набор второй дисциплины и отвергает чужой код; `resolve_roster_shape` идёт турнир → workspace → дисциплина | `backend/shared/tests/test_roles.py`, правки в `test_roster_shape.py` |
| Миграция | на копии дампа: `player.role` до/после ALTER'а совпадает построчно; `downgrade` возвращает enum | ручной прогон + запись результата в PR |
| Сид | `ensure_discipline_catalog` идемпотентен: два прогона подряд не меняют строки; изменение `label` в декларации обновляет строку | `backend/shared/tests/test_discipline_catalog.py` |
| Контракт | `test_rpc_route_parity.py` и `check_rpc_docs.py` зелёные на новых субъектах | существующие гейты |
| Фронт | `useRoleSet` отдаёт порядок из `sort_order`; неизвестный код рендерится как код, а не пропадает (регрессия на `PlayerRoleIcon.tsx:47-49`, который сегодня возвращает `null`) | `src/hooks/useRoleSet.test.ts` |
| i18n | перечисление кодов ролей × 2 локали | расширение `messages.parity.test.ts` |

Тесты, которые **удаляются**, а не переписываются: те, что пинят сам набор из четырёх ролей как контракт
(`shared/tests/test_heroclass_flex.py`, часть кейсов `test_roster_shape.py`). Они защищали инвариант, который эта
работа сознательно снимает; перепинить их на новый текст — значит зафиксировать ту же ошибку под другим именем.

### A11. Документация

| Файл | Правка |
| --- | --- |
| `docs/glossary.md` | новые термины «Дисциплина», «Роль», «Флекс-слот»; `:38` (roster shape) и `:52` (division) перестают ссылаться на роли Overwatch как на данность |
| `docs/database_erd.md` | перегенерация `uv run python backend/scripts/export_erd.py`. Ключ секции не меняется (пакет уже `shared/models/catalog/`), но метки сущностей в mermaid станут `CATALOG_HERO` вместо `OVERWATCH_HERO` — `entity(table) = f"{schema}_{name}".upper()`. Новых маркеров `<!-- ERD:auto … -->` не нужно: `Discipline` живёт в существующем пакете |
| `docs/business-logic-inventory.md` | §4-§6 (регистрация, roster shape, формирование команд) — роль перестаёт быть фиксированной тройкой |
| `docs/architecture.md` | схема `overwatch` → `catalog` в таблице схем |
| `frontend/src/i18n/GLOSSARY.md` | русские подписи ролей |
| `frontend/src/app/(site)/docs/diagrams.ts` | 10 мест с `overwatch` в рукописной ERD |
| `docs/README.md` | ссылка на этот документ в «In-flight work» |

---

## 6. Фаза B — шов статистики

### B1. Парсер перестаёт писать серию

Дословно Phase 1 из `2026-09-13-decouple-stats-from-tournament.md:85-98`. Инвариант (`:87`): единственные, кто пишет
`Encounter.home_score`/`away_score`/`status`/`result_status` — finalize-пути tournament-svc.

Конкретно: `_enqueue_match_log_tournament_events`
(`backend/parser-service/src/services/match_logs/flows.py:126-159`, вызывается из `flows.py:1181`) перестаёт класть в
outbox `TournamentStandingsInvalidatedEvent` и `EncounterCompletedEvent`. Вместо них — тонкое
`MatchParsedEvent {event_id, encounter_id, match_id, map_id, home_score, away_score}` в
`backend/shared/schemas/events.py` (обязательный `event_id`, `ARCHITECTURE.md:248-250`), через
`enqueue_outbox_event` в той же транзакции (`flows.py:1165-1186` — она уже атомарна).
Потребитель в tournament-svc — за явным флагом формы `logs_are_official`, по умолчанию выключенным.
Инвалидацию кэша **чтений матча** оставляем, инвалидацию `TOURNAMENT_STANDINGS` убираем.

Проверка (из того же плана, `:98`): распарсить лог для LIVE-encounter'а, по которому капитаны не отчитались →
счёт серии не изменился, джоб пересчёта таблицы не поставлен, `matches.match` и статистика на месте,
ачивки на статах отработали.

### B2. `stats_context`

Реализация §4.4. Порядок — как в чеклисте `ARCHITECTURE.md:459-482`: сначала методы порта и их тесты,
потом замена вызовов.

Что переезжает на порт:
- `conditions/__init__.py:97-171` (`get_all_eligible_users`, `get_eligible_keys` — джойн
  Tournament→Encounter→Match→Team→Player→WorkspaceMember) → `stats_context.eligible_members`;
- `parser-service/src/rpc/achievements.py:40,76` и `engine/runner.py:24,56` (`TournamentRepository` как зависимость) →
  порт;
- `flows.py:19` (`MatchRepository` из `shared.repository.tournament`) — остаётся: `matches.match` принадлежит
  стат-стороне, репозиторий просто лежит в турнирном модуле. Переезжает в `shared/repository/matches.py`;
- `parser-service/src/services/tournament/service.py:7,30` — обёртка над `TournamentRepository`, удаляется целиком;
- `analytics-service/src/models/__init__.py:20-26` — wildcard уходит; FK в `analytics.*` на `tournament.*` **остаются**
  (это внешние ключи в одной БД, а не импорт), сузить их — фаза 2 старого плана, не эта работа.

После этого включается `.importlinter`-контракт, и всё, что не пролезло, попадает в `ignore_imports` поимённо.

### B3. `disciplines/overwatch/` — доменный слой

**Парсер.** Нейтральный DTO вместо pandas-DataFrame наружу:

```python
@dataclass(frozen=True)
class ParsedMatch:
    map_name: str; gamemode: str | None
    home_team_name: str; away_team_name: str
    home_score: int; away_score: int; duration: float | None
    participants: tuple[ParsedParticipant, ...]   # battle_name, team_name
    rounds: tuple[ParsedRound, ...]
    stats: tuple[ParsedStat, ...]       # participant, hero | None, round, code: str, value: float
    kills: tuple[ParsedKill, ...]
    events: tuple[ParsedEvent, ...]
```

Поля выведены из того, что персистентный слой сегодня действительно достаёт из `data: list[str]`:
MatchStart (`flows.py:224-236`), MatchEnd (`:301-309`), PlayerJoined (`:170-175`), Kill (`:512-539`),
MatchEvent (`:596-609`), PlayerStat (`:833-849`). `code: str` вместо `LogStatsName` — единственное существенное
расширение; для OW коды совпадают с именами членов enum, так что запись в колонку остаётся прежней.

`MatchLogProcessor` разрезается по шву «парсинг / персистентность», который в нём уже есть:

| Остаётся в `core/` | Уезжает в `disciplines/overwatch/parser.py` |
| --- | --- |
| получение байтов из S3, size guard, `content_hash`-дедуп, `set_processing` (`flows.py:1381-1414`) | `_load_and_format_data`, `_assign_round_numbers` (`:200-239`) |
| резолв/создание `Match`, `delete_for_match` ×3, bulk insert, commit, outbox (`:1121-1186`) | `validate`, `_preload_data`, `process_teams`, `get_map`, `process_kills`, `process_events`, `create_stats` |
| реаппер, backfill-оркестрация | `impact.py`, `baselines.py`, `hero_aliases.py` |

`core/ingest` вместо безусловного `MatchLogProcessor` делает
`parser_for(stats_context.discipline_of_tournament(...).slug).parse(raw, ctx)`.
Неизвестная дисциплина → 422 `unsupported_discipline`, не молчаливый дроп.
Идемпотентность не меняется: дедуп по `content_hash` до парсинга, delete-and-reinsert после.

**Листья ачивок.** Из 31 модуля в `engine/conditions/` десять трогают `Hero`/`HeroClass`/`LogStatsName`/`Map`/
`Gamemode`/`MatchEvent` и уезжают в `disciplines/overwatch/achievements/`:
`aggregate.py` (`global_stat_sum`, `distinct_count` — резолвят `stat` через `LogStatsName`), `hero.py`,
`hero_pickrate.py`, `kill_feed.py`, `log_stat_rank.py`, `map_coverage.py`, `match_event.py`, `mvp.py`,
`stat_threshold.py`, `team_otp.py`, плюс субусловия `player_role`/`player_div` внутри `team.py:63,116`.
Остальные ~20 (`bracket`, `standing`, `streak`, `registration`, `draft`, `encounter*`, `tournament_*`, `player`,
`rank_history`, `participation`, `teammate_recurrence`, `div_span`, `division`, `match_win`, `match_criteria`,
`standing_count`, `reached_playoffs`) — чистая турнирная логика, остаются в `core/achievements/`.

Механизм регистрации не меняется: `_REGISTRY` + `@register(name)` + `execute_leaf`
(`engine/conditions/__init__.py:70-84`). Меняется только то, какие модули импортируются: ядро всегда,
дисциплинные — при регистрации дисциплины. Рулы (`achievements.rule.condition_tree`, JSON) уже данные —
они не мигрируют.

**Валидация правил.** `resolve_stat_name`/`validate_stat_name` (`conditions/__init__.py:31-49`) перестают ходить в
`LogStatsName` и начинают — в `catalog.stat` дисциплины. Это и есть то, что делает редактор ачивок
мультидисциплинарным.

### B4. Каталог статов

`catalog.stat` (§4.3) заменяет две захардкоженные вещи:
`LOG_STATS_DEFAULT_DIRECTION` / `is_ascending_stat` (`shared/core/enums.py:265-288`) и неявные подписи статов в UI.
Сид — из `definition.py` (§A4), 43 строки для Overwatch.

`matches.statistics.name` остаётся `Enum(LogStatsName)`: 27 млн строк. Вторая дисциплина добавляет свои значения
через `ALTER TYPE ... ADD VALUE` (без rewrite таблицы), а `catalog.stat` описывает их для UI и валидации.
Расхождение «enum в хранении / таблица в контракте» — сознательный долг, записанный в §11.

### B5. `rpc.stats.*` — волнами

Пути HTTP не меняются. Меняется `RouteSpec.Queue`, местоположение хендлера, ключи в `openapi_docs.py`/
`openapi_schemas.py` и имена `$ref`-схем (`tournament.AdminMatchDetail` → `stats.AdminMatchDetail`).
Новый пакет `gateway/internal/stats/{routes.go,cacheable.go}`, проводка в `gateway/cmd/gateway/main.go`
(`statsEdge := edge.New(rpcClient, logger, resolver.Resolve)` + `Register`/`RegisterCached`) **до** catch-all
404-гарда `/api/v1/` на `main.go:395-397`. Группы тегов в `gateway/internal/apidocs/groups.go:57-61` пересобираются.

| Волна | Маршрут | Было | Стало |
| --- | --- | --- | --- |
| B5a | `GET /api/v1/matches` | `rpc.tournament.list_matches` | `rpc.stats.match.list` |
| | `GET /api/v1/matches/{id}` | `rpc.tournament.get_match` | `rpc.stats.match.get` |
| | `GET /api/v1/matches/{id}/kill-feed` | `rpc.tournament.get_match_kill_feed` | `rpc.stats.match.kill_feed` |
| | `GET /api/v1/admin/matches` | `rpc.tournament.admin_matches_list` | `rpc.stats.match.admin_list` |
| | `GET /api/v1/admin/matches/{match_id}` | `rpc.tournament.admin_match_get` | `rpc.stats.match.admin_get` |
| | `GET /api/v1/tournaments/statistics/{history,division,overall}` | `rpc.tournament.statistics_*` | `rpc.stats.tournament.*` |
| B5b | `GET /api/v1/statistics/{dashboard,champion,winrate,won-maps}` | `rpc.app.statistics.*` | `rpc.stats.leaderboard.*` / `rpc.stats.dashboard.overall` |
| | `GET /api/v1/heroes/statistics/playtime` | `rpc.app.heroes.playtime` | `rpc.stats.hero.playtime` |
| | `GET /api/v1/heroes/{hero_id}/leaderboard` | `rpc.app.heroes.leaderboard` | `rpc.stats.hero.leaderboard` |
| | `GET /api/v1/users/{id}/{heroes,maps,matches/summary}` | `rpc.app.users.*` | `rpc.stats.player.*` |
| B5c | `POST /api/v1/achievement/calculate[/{tournament_id}]` + 23 маршрута `/api/v1/admin/ws/{workspace_id}/achievements/**` | `rpc.parser.ach.*` | `rpc.stats.achievement.*` |
| | `POST /api/v1/admin/impact/recompute-baselines` | `rpc.parser.impact.*` | `rpc.stats.impact.*` |
| — | `rpc.parser.{logs,rank,subscription,settings,discord_channel,metadata}.*` | — | **остаются** `rpc.parser.*`: это приём файлов, внешние коллекторы и глобальные настройки, а не геймплейная статистика |
| — | `rpc.analytics.*` | — | **остаются**: отдельный деплой с ML-профилем ресурсов; переименование дало бы ноль поведения при полном обходе маршрутов, схем и тестов. Пересмотреть, когда/если analytics схлопнется в стат-движок |

`/api/v1/admin/logs/stats` (`rpc.parser.logs.stats`) остаётся у парсера несмотря на слово «stats» в пути:
это статистика очереди приёма, не игроков.

Важно для B5b: перенос *горячих публичных чтений* из app-svc — это перенос нагрузки. Поэтому они едут в `stats-svc`
(`serve_rpc.py`), а не в воркер с pandas (§3, решение 5). `app-service/.importlinter` теряет `services.statistics`
из уровня L1 — файл правится в той же волне (`backend/docs/architecture/layering.md:17`).

### B6. Процессы и инфраструктура

Новый compose-сервис `stats-svc` по образцу блока `analytics-svc`/`stream-svc`
(`docker-compose.yml`, `docker-compose.production.yml`): тот же образ, что у `parser-svc`,
`command: faststream run serve_rpc:app`, `env_file: [common.env, parser.env]`, свой порт метрик,
свои resource limits. `Upstreams` в `gateway/internal/config/config.go:140-146` **не трогаем**:
это только для сервисов, которые ещё проксируются по HTTP; чистый RPC туда не добавляется.

`Makefile` (таблица `PROD_SIZE`), `monitoring/prometheus` (скрейп нового порта),
`.github/workflows/test-backend.yml` (матрица per-service pytest — пакет тот же, новых записей не нужно).

### B7. Проверки фазы B

| Что | Как |
| --- | --- |
| B1 | сценарий из `2026-09-13:98` дословно, на dev-стенде |
| Парсер-реестр | распарсить тот же лог до и после разреза → `matches.match`, `statistics`, `kill_feed`, `event` совпадают построчно (сравнение дампа таблиц по `match_id`) |
| Неизвестная дисциплина | турнир с дисциплиной без парсера → 422 `unsupported_discipline`, `LogProcessingRecord.status='failed'` с внятным `error_message`, ни одной строки в `matches.*` |
| Листья | существующий `test_achievement_engine_nodes.py` зелёный после переезда 10 модулей; `engine/conditions` ядра не импортирует ничего из `disciplines/` |
| Границы | `lint-imports` в обоих сервисах; `backend/tests/test_repository_boundaries.py` |
| Контракты | `test_rpc_route_parity.py`, `check_rpc_docs.py`, `export_openapi_schemas.sh --check` после каждой волны B5 |
| Латентность | до/после B5b: p95 `/api/v1/statistics/champion` и `/api/v1/users/{id}/heroes` из Grafana — перенос не должен их ухудшить |

### B8. Переименование пакета (последним, опционально)

`backend/parser-service/` → `backend/stats-service/`. Механическая правка: `pyproject.toml` (uv workspace),
`Dockerfile`/`build.args.APP_PATH`, два compose-файла, `.github/workflows/test-backend.yml`,
`backend/README.md` + `docs/README.md:47-56`, пути в `.importlinter`, `logs/parser*`.
Ноль поведения, вся выгода — в названии. Делать отдельным PR, когда содержимое устоялось; до тех пор имя каталога
врёт, и это меньшее из зол по сравнению с переименованием посреди переезда.

---

## 7. Фаза C — фронт дисциплин

Минимум, который делает вторую дисциплину возможной, и ни строчки сверх:

1. `src/games/registry.ts` + `src/games/overwatch/` (§A8).
2. Туда уезжает всё, что знает про героев OW: `heroVariantFromRole`, `HeroRadar`'s `RADAR_STATS`,
   вкладки Heroes/Maps из `TournamentStatsPage.tsx:104-260`, кластер `users/components/heroes/*`.
3. `src/lib/ow-ladder.ts` и `src/lib/division-grid.ts` **не трогаем**: `ow-ladder.generated.json` — артефакт,
   гейтящийся в CI (`scripts/export_ow_ladder.py`), а второй ладдер — явно вне области (§11).
   Когда он понадобится, `DEFAULT_DIVISION_GRID` станет дефолтом дисциплины, а не глобальным.
4. Никакого `basePath`/`assetPrefix`/Module Federation. `docs/frontend-zones.md:78-102` перечисляет четыре
   single-instance блокера любого сплита (QueryClient, WS, ротация токена, host→workspace резолв) — ни один из них
   эта работа не решает и не должна.

---

## 8. Раскатка, бэкфилл, откат

Порядок релизов. Каждый — самостоятельно работающая система.

| Релиз | Содержимое | Откат |
| --- | --- | --- |
| R1 | `catsch001` + правка `schema=` в моделях и FK-строках | `ALTER SCHEMA catalog RENAME TO overwatch`, реверт кода |
| R2 | `disc0001` + `disc0002` + сид + модели + `discipline_access`; API ещё отдаёт роли по-старому | drop колонок и таблиц; данные никто не читает |
| R3 | `plrole001` + `RoleSet` + удаление `player-role.ts`/`roles.ts` + ломающий контракт роли (§A7) + фронт | обратный ALTER; фронт и бэк катятся одним тегом, частичного отката нет **by design** |
| R4 | B1 (парсер не пишет серию) | вернуть два события в outbox |
| R5 | B2 + B3 + B4 + `.importlinter` | реверт кода, схема не менялась |
| R6 | B5a → B5b → B5c, по одному релизу на волну; `stats-svc` поднимается в B5a | каждая волна — реверт `Queue`-литералов и места хендлера |
| R7 | B8 (переименование) | реверт |

R3 — единственный релиз без частичного отката: фронт и бэкенд меняют контракт роли одновременно. Это приемлемо,
потому что `deploy-production.yml` собирает все 10 образов из одного тега и катит их вместе; смешанной версии
в проде не бывает.

Бэкфиллов данных ровно два, оба внутри миграций и оба тривиальные:
`tournament.discipline_id = overwatch` и приведение типа `player.role` (значения уже правильные).
Ни одной операции по 27-миллионной таблице.

---

## 9. Чеклист CI

Перед каждым PR по этой работе:

```
bash scripts/lint.sh                                  # ruff check + format --check
cd backend && uv run pytest shared/tests parser-service/tests tournament-service/tests app-service/tests
cd backend && uv run python scripts/export_erd.py     # + git add ../docs/database_erd.md
bash scripts/export_openapi_schemas.sh                # после любой правки субъектов
python3 backend/scripts/check_rpc_docs.py
cd backend && uv run lint-imports                     # там, где появился .importlinter
cd frontend && bun run typecheck && bun run lint && bun run lint:design && bun run lint:zones && bun run test:split
cd gateway && go vet ./... && go test -race ./...
python3 scripts/check_doc_links.py
```

Гейты, которые эта работа задевает по построению:
`export_erd.py --check` (переименование схемы меняет метки сущностей), `check_rpc_docs.py` (каждый новый субъект),
`export_openapi_schemas.sh --check` (перенос `$ref`), `lint:zones` Z4 (регенерация `zone-namespaces.json`),
`messages.parity.test.ts` (ключи ролей в двух локалях), `test_rpc_route_parity.py` (шлюз vs подписчики).

Коммиты: `type(scope): imperative subject`. Существующего scope под каталог игр нет; вводится `discipline`
(например `feat(discipline): role catalog tables`), для второй фазы — `stats`.

---

## 10. Риски

| Риск | Вероятность | Митигация |
| --- | --- | --- |
| ALTER `player.role` на проде идёт дольше окна | средняя | таблица — одна строка на слот состава, не миллионы; `_with_lock_retry` с `lock_timeout=3s` и backoff; прогон на копии дампа до мержа обязателен |
| Пропущенная копия словаря ролей на фронте рендерит пустоту | **высокая** — сегодня `PlayerRoleIcon.tsx:47-49` возвращает `null` на незнакомой роли | после удаления `player-role.ts` компилятор ловит импорты; для строковых литералов — чеклист §A8 плюс правило «неизвестный код рендерится как код», зафиксированное тестом |
| Перенос горячих чтений в B5b ухудшает латентность | средняя | они едут в `stats-svc`, а не в воркер с pandas; before/after p95 в чеклисте B7 |
| `.importlinter` ставится раньше, чем убраны нарушения, и блокирует работу | средняя | контракт включается в B2 **после** переезда, нарушения — поимённо в `ignore_imports`, как `PENDING_REPOSITORY_MIGRATION` |
| Потеря enum'а `slot_code` в OpenAPI ломает внешних потребителей | низкая | публичных SDK на эти поля нет; список ролей едет в payload'е турнира (§A7) |
| Слепой `sed overwatch→catalog` ломает `overwatch_rank` | средняя | §A1 явно перечисляет ~58 вхождений другого контекста; правка только по списку файлов §A2 |
| Реестры вырождаются в абстракцию ради абстракции | средняя | `ARCHITECTURE.md:314-316`; три словаря, ноль `Protocol`-ов, ноль фабрик. Ревьюер отклоняет любой четвёртый уровень косвенности |

---

## 11. Явно вне области

Каждый пункт — с признаком, по которому его стоит начать.

| Не делаем | Начать, когда |
| --- | --- |
| `discipline_id` на `catalog.{hero,map,gamemode}` | появилась вторая дисциплина с собственным каталогом сущностей |
| Второй рейтинговый ладдер / `division_grid` по дисциплине | у второй дисциплины есть публичный API рангов |
| `matches.statistics.name` в `varchar` | вторая дисциплина реально пишет статистику и `ALTER TYPE ADD VALUE` стал неудобен |
| Перенос analytics в `rpc.stats.*` | analytics перестал быть отдельным деплоем с ML-профилем |
| `Match.encounter_id` nullable, субъект статистики = `workspace_member` | фазы 2-3 старого плана (`2026-09-13:100-119`) — когда заболят микс/скрим |
| `competitive_fact`-проекция для листьев ачивок | фаза 4 там же (`:120-124`) — когда вычисление станет измеримо дорогим |
| Module Federation, Next multi-zone | триггеры из `docs/frontend-zones.md:80-82`: сборка > 8 мин, вторая команда блокируется на деплоях, админка на отдельном хосте |
| Переименование `custom_game` | никогда, если не появится причина сильнее вкуса |

---

## 12. Открытые вопросы

1. **Может ли workspace переопределять подписи и иконки ролей дисциплины?** Сейчас — нет: `discipline_role` глобальна.
   Прецедент для «да» есть (`division_grid` версионируется на workspace). Отложено до первого запроса;
   если понадобится, добавляется `workspace_discipline_role_override`, а не колонка в глобальную таблицу.
2. **Может ли турнир менять дисциплину после создания?** Предполагается «нет после публикации регистрации»:
   смена инвалидирует состав, роли игроков и всю статистику. Нужно решить, гейтить это в сервисе или CHECK'ом на фазу.
3. **Второй парсер формата для той же дисциплины** (например, другой экспортёр логов OW) — реестр допускает
   несколько парсеров на дисциплину, но `parser_for()` возвращает один. Разрешается `sniff()`-ом при появлении
   второго формата, не раньше.
