# ERD базы данных — anak-tournaments

Единая PostgreSQL-база, которую делят все Python-сервисы монорепы. ORM-модели
(SQLAlchemy) разложены по **доменным подпакетам** внутри
`backend/shared/models/<domain>/` — `identity/` (auth_user, rbac, oauth,
api_key, user, social, user_merge_audit), `tenancy/` (workspace, settings),
`catalog/` (hero, map, gamemode), `division_grid/`, `tournament/` (tournament,
stage, team, encounter, encounter_link, encounter_map, standings, computation,
challonge), `registration/`, `balancer/` (balance, draft), `matches/`,
`achievements/`, `analytics/`, `ranks/`, `ingestion/`, `preferences/`,
`platform/`. Физически таблицы разложены по **Postgres-схемам** — они же
служат границами доменов (имя подпакета не всегда совпадает с именем схемы:
напр. `ranks/` → схема `overwatch_rank`, `ingestion/` → `log_processing`).

Ниже — обзор схем, карта доменов и отдельная ER-диаграмма на каждый домен
(Mermaid `erDiagram`, рендерится в GitHub / VS Code / любом Mermaid-вьюере).

> **Актуальность.** Документ отражает финальное состояние после
> identity/workspace-рефактора и нормализаций Challonge / map-veto / draft /
> predictions. Alembic head — **`dbarch06`**. Сводка изменений — в конце
> файла («История изменений схемы»).

> Соглашение об именах на диаграммах: имя сущности = `SCHEMA_TABLE`, потому что
> одно и то же имя таблицы встречается в разных схемах (`auth.user` vs
> `players.user` vs `achievements.user`; `tournament.team` vs `balancer.team`;
> `tournament.tournament` vs `analytics.tournament`). Столбцы в диаграммах —
> это PK, FK, UK и ключевые бизнес-поля; широкие таблицы обрезаны (помечено
> `… прочие поля`). Пунктирные/серые сущности со звёздочкой `*` — «чужие»
> якорные таблицы из другого домена, показаны только для связи.

---

## Postgres-схемы

| Схема | Домен | Ключевые таблицы | Владелец (сервис) |
|-------|-------|------------------|-------------------|
| `auth` | Аутентификация и RBAC | `user`, `refresh_token`, `oauth_connections`, `api_key`, `roles`, `permissions`, `user_roles`, `role_permissions`, `user_permission_deny` | auth-service |
| `players` | Идентичность игрока | `user`, `social_account`, `social_account_visibility`, `user_merge_audit` | app-service |
| `public` | Воркспейсы, сетки дивизионов, инфра | `workspace`, `workspace_member`, `division_grid*`, `settings`, `event_outbox` | app-service |
| `tournament` | Структура турнира и сетка | `tournament`, `stage`, `stage_item`, `team`, `player`, `standing`, `encounter`, `encounter_link`, `challonge_*`, `computation_job` | tournament-service |
| `overwatch` | Справочник игры | `hero`, `map`, `gamemode` | app / parser |
| `overwatch_rank` | Телеметрия рангов OW | `rank_snapshot`, `battle_tag_state`, `fetch_log` | parser-service |
| `matches` | Разобранные матч-логи | `match`, `statistics`, `kill_feed`, `assists`, `mv_hero_global_stats` (MV) | parser-service |
| `balancer` | Регистрация и балансировка | `registration*`, `balance*`, `team*`, `tournament_config`, `draft_*` | balancer-service |
| `achievements` | Движок достижений | `rule`, `evaluation_result`, `override`, `evaluation_run` | parser / app |
| `analytics` | Аналитика и ML | `tournament`, `shifts`, `performance`, `standings_distribution`, `match_quality`, `ml_*`, `job`, … | analytics-service |
| `log_processing` | Загрузка/парсинг логов | `record`, `discord_channel` | parser / discord |
| `realtime` | Журнал realtime-событий | `workspace_event` | gateway (Go) |

Общие «хабы», к которым сходятся почти все домены:

- **`public.workspace`** — арендатор (мультитенантность). Почти всё скоупится по `workspace_id`.
- **`players.user`** — доменная идентичность игрока (может существовать без аккаунта — «shadow player» из логов/CSV).
- **`auth.user`** — учётная запись для входа; линк к `players.user` — `1:0..1`.
- **`workspace_member`** — якорь принадлежности игрока к воркспейсу (уникальность по `workspace_id + player_id`); на него по `workspace_member_id` ссылаются ростер (`tournament.player`), регистрации (`balancer.registration`), драфт (`draft_team`/`draft_player`/`draft_pick`) и достижения (`evaluation_result`/`override`). Денормализованной роли нет — роль выводится из RBAC.
- **`tournament.tournament`** — турнир; корень для стадий, команд, матчей, регистраций, аналитики.
- **`overwatch.hero`** — герой; на него ссылаются статистика, топ-герои регистрации, достижения.

---

## 0. Карта доменов (какие схемы на что ссылаются)

```mermaid
flowchart TB
    subgraph IDENTITY["Идентичность и доступ"]
        AUTH["auth<br/>(учётки, RBAC)"]
        PLAYERS["players<br/>(игроки, соц-аккаунты)"]
        WS["public.workspace<br/>+ workspace_member"]
        GRID["public.division_grid*<br/>(сетки дивизионов)"]
    end

    subgraph COMPETITION["Соревнование"]
        TOUR["tournament<br/>(стадии, команды, сетка)"]
        MATCHES["matches<br/>(матч-логи, статистика)"]
        OW["overwatch<br/>(hero / map / gamemode)"]
        RANK["overwatch_rank<br/>(снапшоты рангов)"]
    end

    subgraph TEAMBUILD["Формирование команд"]
        BAL["balancer<br/>(регистрация, баланс)"]
        DRAFT["balancer.draft_*<br/>(live-драфт)"]
    end

    subgraph INSIGHT["Пост-обработка"]
        ACH["achievements<br/>(достижения)"]
        AN["analytics<br/>(shift / ML / прогнозы)"]
    end

    subgraph PLATFORM["Платформа / инфра"]
        LOG["log_processing<br/>(record, discord_channel)"]
        RT["realtime.workspace_event"]
        OUTBOX["public.event_outbox"]
        SET["public.settings"]
    end

    WS --> AUTH
    WS --> PLAYERS
    AUTH -. "1:0..1" .-> PLAYERS
    WS --> GRID

    TOUR --> WS
    TOUR --> GRID
    TOUR --> PLAYERS
    MATCHES --> TOUR
    MATCHES --> OW
    MATCHES --> PLAYERS
    RANK --> PLAYERS

    BAL --> TOUR
    BAL --> WS
    BAL --> PLAYERS
    BAL --> OW
    DRAFT --> BAL
    DRAFT --> TOUR

    ACH --> WS
    ACH --> TOUR
    ACH --> MATCHES
    ACH --> OW
    AN --> TOUR
    AN --> MATCHES
    AN --> BAL

    LOG --> TOUR
    LOG --> PLAYERS
    RT --> WS
```

---

## 1. Аутентификация и RBAC (`auth`)

Учётные записи для входа, refresh-токены, OAuth-подключения, API-ключи и
ролевой доступ. RBAC — grant-only (роли → права) плюс **негативный overlay**
`user_permission_deny` (точечный запрет, перебивает даже суперюзера).

```mermaid
erDiagram
    AUTH_USER {
        int id PK
        string email UK
        string username UK
        string hashed_password "nullable (OAuth-only)"
        bool is_active
        bool is_superuser
        bool is_verified
        timestamp created_at
        timestamp updated_at
    }
    AUTH_REFRESH_TOKEN {
        int id PK
        string token UK
        int user_id FK
        uuid session_id
        timestamp expires_at
        bool is_revoked
        string ip_address
    }
    AUTH_OAUTH_CONNECTION {
        int id PK
        int auth_user_id FK
        string provider "UK(provider, provider_user_id)"
        string provider_user_id
        string access_token
        string refresh_token
        json provider_data
    }
    AUTH_API_KEY {
        int id PK
        int auth_user_id FK
        int workspace_id FK
        string public_id UK
        string secret_hash
        json scopes_json
        timestamp expires_at
        timestamp revoked_at
    }
    AUTH_ROLE {
        int id PK
        string name "UK per workspace (global when NULL)"
        int workspace_id FK "nullable: NULL = глобальная роль"
        bool is_system
    }
    AUTH_PERMISSION {
        int id PK
        string name UK
        string resource
        string action
    }
    AUTH_USER_ROLE {
        int id PK
        int user_id FK
        int role_id FK
    }
    AUTH_ROLE_PERMISSION {
        int id PK
        int role_id FK
        int permission_id FK
    }
    AUTH_USER_PERMISSION_DENY {
        int id PK
        int user_id FK
        int permission_id FK
        int workspace_id FK "nullable: NULL = глобальный deny"
        int created_by FK "nullable → auth.user (SET NULL); FK добавлен dbarch01"
        string reason
    }
    WORKSPACE {
        int id PK
    }

    AUTH_USER ||--o{ AUTH_REFRESH_TOKEN : "сессии"
    AUTH_USER ||--o{ AUTH_OAUTH_CONNECTION : "логинится через"
    AUTH_USER ||--o{ AUTH_API_KEY : "владеет"
    AUTH_USER ||--o{ AUTH_USER_ROLE : "назначены роли"
    AUTH_ROLE ||--o{ AUTH_USER_ROLE : "назначена кому"
    AUTH_ROLE ||--o{ AUTH_ROLE_PERMISSION : "даёт"
    AUTH_PERMISSION ||--o{ AUTH_ROLE_PERMISSION : "включено в роль"
    AUTH_USER ||--o{ AUTH_USER_PERMISSION_DENY : "запреты"
    AUTH_USER |o--o{ AUTH_USER_PERMISSION_DENY : "создал (created_by)"
    AUTH_PERMISSION ||--o{ AUTH_USER_PERMISSION_DENY : "что запрещено"
    WORKSPACE ||--o{ AUTH_ROLE : "скоупит (nullable)"
    WORKSPACE ||--o{ AUTH_API_KEY : "скоупит"
    WORKSPACE ||--o{ AUTH_USER_PERMISSION_DENY : "скоупит (nullable)"
```

> **Гигиена индексов/FK (dbarch01).** Ассоциативные таблицы `auth.user_roles`
> и `auth.role_permissions` получили индексы на обе FK-колонки (раньше
> резолвинг прав и каскадные удаления делали seq-scan). FK `deny.created_by →
> auth.user` добавлен как `NOT VALID` + `VALIDATE` (SET NULL).

---

## 2. Идентичность игрока и воркспейсы (`players` + `public`)

`players.user` — доменный игрок (независим от `auth.user`, может быть без
аккаунта). Соц-идентичности (battlenet/discord/twitch/…) сведены в
`social_account` с overlay-видимостью по воркспейсам. `workspace_member`
привязывает игрока к арендатору и служит якорем для ростеров и достижений.

```mermaid
erDiagram
    AUTH_USER {
        int id PK
        string email UK
    }
    PLAYERS_USER {
        int id PK
        string name UK
        int auth_user_id FK "UNIQUE, nullable — NULL = shadow player"
        string avatar_url
        timestamp created_at
    }
    PLAYERS_SOCIAL_ACCOUNT {
        int id PK
        int user_id FK
        string provider "UK(user, provider, username_normalized)"
        string username
        string username_normalized
        string provider_user_id "nullable; UK(provider, subject) when set"
        bool is_verified
        bool is_primary
    }
    PLAYERS_SOCIAL_VISIBILITY {
        int id PK
        int account_id FK
        int workspace_id FK "nullable: NULL = глобальная видимость"
    }
    PLAYERS_USER_MERGE_AUDIT {
        int id PK
        int source_user_id FK "nullable → players.user (SET NULL); FK с dbarch01"
        int target_user_id FK "nullable → players.user (SET NULL); FK с dbarch01"
        int operator_auth_user_id FK "nullable → auth.user"
        json field_policy_json
        json affected_counts_json
    }
    WORKSPACE {
        int id PK
        string slug UK
        string name
        bool is_active
        int default_division_grid_version_id FK "nullable"
    }
    WORKSPACE_MEMBER {
        int id PK
        int workspace_id FK
        int player_id FK "UK(workspace_id, player_id)"
        timestamp created_at
    }
    DIVISION_GRID_VERSION {
        int id PK
    }

    AUTH_USER |o--o| PLAYERS_USER : "владеет (1:0..1)"
    PLAYERS_USER ||--o{ PLAYERS_SOCIAL_ACCOUNT : "хендлы + смурфы"
    PLAYERS_SOCIAL_ACCOUNT ||--o{ PLAYERS_SOCIAL_VISIBILITY : "видимость по scope"
    WORKSPACE ||--o{ PLAYERS_SOCIAL_VISIBILITY : "scope (nullable=global)"
    AUTH_USER |o--o{ PLAYERS_USER_MERGE_AUDIT : "оператор merge"
    PLAYERS_USER |o--o{ PLAYERS_USER_MERGE_AUDIT : "источник merge (SET NULL)"
    PLAYERS_USER |o--o{ PLAYERS_USER_MERGE_AUDIT : "цель merge (SET NULL)"
    WORKSPACE ||--o{ WORKSPACE_MEMBER : "участники"
    PLAYERS_USER ||--o{ WORKSPACE_MEMBER : "член воркспейса"
    DIVISION_GRID_VERSION |o--o{ WORKSPACE : "дефолтная сетка"
```

> **`workspace_member`** ключуется на `player_id` (FK → `players.user`) с
> уникальностью `(workspace_id, player_id)`; денормализованной роли нет.
> **`players.social_account`** имеет частичный unique-индекс (dbarch01) для
> строк с `username_normalized IS NULL` (по `lower(btrim(username))`) — он
> закрывает обход основного `uq(user, provider, username_normalized)`, который
> не дедуплицирует NULL-хендлы.

---

## 3. Сетки дивизионов (`public.division_grid*`)

Версионируемые «сетки» рангов: тиры с диапазонами SR + маппинги между версиями
(для нормализации рангов между сезонами/OW-биндингами). Привязываются к
воркспейсу (или глобальные) и выбираются турниром.

```mermaid
erDiagram
    DIVISION_GRID {
        int id PK
        int workspace_id FK "nullable: NULL = глобальная; UK(workspace_id, slug)"
        string slug
        string name
    }
    DIVISION_GRID_VERSION {
        int id PK
        int grid_id FK "UK(grid_id, version)"
        int version
        string label
        string status "draft/published"
        int created_from_version_id FK "nullable (self)"
        timestamp published_at
    }
    DIVISION_GRID_TIER {
        int id PK
        int version_id FK "UK(version_id, slug); UK(version_id, sort_order)"
        string slug
        int number
        int rank_min
        int rank_max "nullable"
        int ow_rank_min "nullable"
        int ow_rank_max "nullable"
    }
    DIVISION_GRID_MAPPING {
        int id PK
        int source_version_id FK "UK(source, target)"
        int target_version_id FK
        bool is_complete
    }
    DIVISION_GRID_MAPPING_RULE {
        int id PK
        int mapping_id FK
        int source_tier_id FK
        int target_tier_id FK
        float weight
        bool is_primary
    }
    WORKSPACE {
        int id PK
    }
    TOURNAMENT {
        int id PK
        int division_grid_version_id FK "nullable"
    }

    WORKSPACE ||--o{ DIVISION_GRID : "владеет (nullable)"
    DIVISION_GRID ||--o{ DIVISION_GRID_VERSION : "версии"
    DIVISION_GRID_VERSION ||--o{ DIVISION_GRID_TIER : "тиры"
    DIVISION_GRID_VERSION |o--o| DIVISION_GRID_VERSION : "форкнута из"
    DIVISION_GRID_VERSION ||--o{ DIVISION_GRID_MAPPING : "источник"
    DIVISION_GRID_VERSION ||--o{ DIVISION_GRID_MAPPING : "цель"
    DIVISION_GRID_MAPPING ||--o{ DIVISION_GRID_MAPPING_RULE : "правила"
    DIVISION_GRID_TIER ||--o{ DIVISION_GRID_MAPPING_RULE : "source→target"
    DIVISION_GRID_VERSION |o--o{ WORKSPACE : "дефолт воркспейса"
    DIVISION_GRID_VERSION |o--o{ TOURNAMENT : "выбрана турниром"
```

---

## 4. Структура турнира: стадии, команды, ростер (`tournament`)

Турнир → стадии (Stage/StageItem/StageItemInput — новая модель сетки, `group` —
legacy) → команды и их ростер (`player`, привязан к `workspace_member`). Итоги —
в `standing`.

```mermaid
erDiagram
    TOURNAMENT {
        int id PK
        int workspace_id FK
        int number
        string name
        string status "draft/…"
        string team_formation "balancer/draft"
        int division_grid_version_id FK "nullable"
        bool is_finished
    }
    TOURNAMENT_GROUP {
        int id PK
        int tournament_id FK
        int stage_id FK "nullable (legacy → Stage)"
        string name
        bool is_groups
    }
    STAGE {
        int id PK
        int tournament_id FK
        string name
        string stage_type
        int order
        bool is_active
        bool is_completed
    }
    STAGE_ITEM {
        int id PK
        int stage_id FK
        string name
        string type
        int order
    }
    STAGE_ITEM_INPUT {
        int id PK
        int stage_item_id FK
        int slot
        string input_type
        int team_id FK "nullable"
        int source_stage_item_id FK "nullable"
        int source_position "nullable"
    }
    TOURNAMENT_TEAM {
        int id PK
        int tournament_id FK
        int captain_id FK "nullable → players.user"
        string name
        float avg_sr
        int total_sr
    }
    PLAYER {
        int id PK
        int tournament_id FK
        int team_id FK
        int workspace_member_id FK "якорь идентичности ростера"
        int related_player_id FK "nullable (self)"
        string role
        string sub_role
        int rank
        bool is_substitution
    }
    PLAYER_SUB_ROLE {
        int id PK
        int workspace_id FK "UK(workspace_id, role, slug)"
        string role
        string slug
        string label
        bool is_active
    }
    STANDING {
        int id PK
        int tournament_id FK
        int team_id FK
        int stage_id FK "nullable"
        int stage_item_id FK "nullable"
        int group_id FK "nullable (legacy)"
        int position
        int overall_position
        float points
    }
    WORKSPACE {
        int id PK
    }
    WORKSPACE_MEMBER {
        int id PK
    }
    PLAYERS_USER {
        int id PK
    }

    WORKSPACE ||--o{ TOURNAMENT : "проводит"
    TOURNAMENT ||--o{ STAGE : "стадии"
    TOURNAMENT ||--o{ TOURNAMENT_GROUP : "группы (legacy)"
    STAGE ||--o{ STAGE_ITEM : "элементы"
    STAGE ||--o{ TOURNAMENT_GROUP : "новая стадия ↔ legacy-группа"
    STAGE_ITEM ||--o{ STAGE_ITEM_INPUT : "слоты входа"
    TOURNAMENT_TEAM |o--o{ STAGE_ITEM_INPUT : "посев команды"
    STAGE_ITEM |o--o{ STAGE_ITEM_INPUT : "источник (advance)"
    TOURNAMENT ||--o{ TOURNAMENT_TEAM : "команды"
    PLAYERS_USER |o--o{ TOURNAMENT_TEAM : "капитан"
    TOURNAMENT_TEAM ||--o{ PLAYER : "ростер"
    TOURNAMENT ||--o{ PLAYER : "участники"
    WORKSPACE_MEMBER ||--o{ PLAYER : "идентичность"
    PLAYER |o--o{ PLAYER : "замена (related)"
    WORKSPACE ||--o{ PLAYER_SUB_ROLE : "каталог суб-ролей"
    TOURNAMENT ||--o{ STANDING : "итоги"
    TOURNAMENT_TEAM ||--o{ STANDING : "место команды"
    STAGE |o--o{ STANDING : "по стадии"
    STAGE_ITEM |o--o{ STANDING : "по элементу"
```

---

## 5. Встречи, сетка и синхронизация с Challonge (`tournament`)

`encounter` — конкретная встреча (best-of), `encounter_link` — явные рёбра
продвижения (winner/loser → слот). Пул карт и вето (пул `map_veto_config`
нормализован из JSON `map_pool_ids` в дочернюю `map_veto_config_map` —
dbarch05). Плюс мост к Challonge (source/participant/match mapping + журнал
синка) и сохранённые фильтры.

> **Нормализация Challonge (dbarch04 + dbarch04b, применено на проде).**
> Легаси-колонки `challonge_id`/`challonge_slug` на `tournament`/`stage` и
> `encounter.challonge_id`, а также таблица `challonge_team` — **удалены**.
> Единственный источник правды: `challonge_source` +
> `challonge_participant_mapping` + `challonge_match_mapping` +
> `challonge_sync_log`. Исключение — `tournament.group.challonge_id` /
> `challonge_slug` **оставлены**: они хранят Challonge-значение маршрутизации
> `match.group_id` по группам (не покрывается source-моделью).

```mermaid
erDiagram
    ENCOUNTER {
        int id PK
        int tournament_id FK
        int tournament_group_id FK "nullable"
        int stage_id FK "nullable"
        int stage_item_id FK "nullable"
        int home_team_id FK "nullable"
        int away_team_id FK "nullable"
        int home_score
        int away_score
        int round
        int best_of
        string status
        string result_status
        int submitted_by_id FK "nullable → players.user"
        int confirmed_by_id FK "nullable → players.user"
    }
    ENCOUNTER_LINK {
        int id PK
        int source_encounter_id FK "UK(source, role)"
        int target_encounter_id FK
        string role "winner/loser"
        string target_slot "home/away"
    }
    ENCOUNTER_MAP_POOL {
        int id PK
        int encounter_id FK
        int map_id FK
        int order
        string picked_by "nullable"
        string status
    }
    MAP_VETO_CONFIG {
        int id PK
        int tournament_id FK
        int stage_id FK "nullable"
        json veto_sequence_json "шаги ban/pick — остаётся JSON"
    }
    MAP_VETO_CONFIG_MAP {
        int id PK
        int map_veto_config_id FK "UK(config, map)"
        int map_id FK "→ overwatch.map"
        int sort_order
    }
    ENCOUNTER_SAVED_VIEW {
        int id PK
        int workspace_id FK
        int auth_user_id FK "UK(workspace, user, name)"
        string name
        json filters_json
    }
    CHALLONGE_SOURCE {
        int id PK
        int tournament_id FK "UK(tournament, challonge_tournament_id)"
        int stage_id FK "nullable (SET NULL)"
        int stage_item_id FK "nullable (SET NULL)"
        int challonge_tournament_id
        string slug "nullable"
        string source_type "tournament/stage/group/playoff"
    }
    CHALLONGE_PARTICIPANT_MAPPING {
        int id PK
        int source_id FK
        int team_id FK
        int challonge_participant_id
    }
    CHALLONGE_MATCH_MAPPING {
        int id PK
        int source_id FK
        int encounter_id FK
        int challonge_match_id
    }
    CHALLONGE_SYNC_LOG {
        int id PK
        int tournament_id FK
        int source_id FK "nullable"
        string direction "import/export"
        string entity_type
        string status
    }
    TOURNAMENT {
        int id PK
    }
    TOURNAMENT_TEAM {
        int id PK
    }
    MAP {
        int id PK
    }

    TOURNAMENT ||--o{ ENCOUNTER : "встречи"
    TOURNAMENT_TEAM |o--o{ ENCOUNTER : "home/away"
    ENCOUNTER ||--o{ ENCOUNTER_LINK : "источник продвижения"
    ENCOUNTER ||--o{ ENCOUNTER_LINK : "цель продвижения"
    ENCOUNTER ||--o{ ENCOUNTER_MAP_POOL : "пул карт"
    MAP ||--o{ ENCOUNTER_MAP_POOL : "карта"
    TOURNAMENT ||--o{ MAP_VETO_CONFIG : "конфиг вето"
    MAP_VETO_CONFIG ||--o{ MAP_VETO_CONFIG_MAP : "пул карт (нормализован)"
    MAP ||--o{ MAP_VETO_CONFIG_MAP : "карта пула"
    TOURNAMENT ||--o{ CHALLONGE_SOURCE : "источники Challonge"
    CHALLONGE_SOURCE ||--o{ CHALLONGE_PARTICIPANT_MAPPING : "участники"
    TOURNAMENT_TEAM ||--o{ CHALLONGE_PARTICIPANT_MAPPING : "команда"
    CHALLONGE_SOURCE ||--o{ CHALLONGE_MATCH_MAPPING : "матчи"
    ENCOUNTER ||--o{ CHALLONGE_MATCH_MAPPING : "встреча"
    TOURNAMENT ||--o{ CHALLONGE_SYNC_LOG : "журнал синка"
    CHALLONGE_SOURCE |o--o{ CHALLONGE_SYNC_LOG : "по источнику"
    WORKSPACE ||--o{ ENCOUNTER_SAVED_VIEW : "сохранённые фильтры"
```

---

## 6. Матч-логи и справочник Overwatch (`matches` + `overwatch`)

Разобранные лог-файлы: `match` (карта во встрече), детальная per-round
`statistics`, `kill_feed`, события `assists`. Справочник игры — `hero`, `map`,
`gamemode`. `mv_hero_global_stats` — materialized view с глобальными рекордами
по героям (не таблица).

```mermaid
erDiagram
    GAMEMODE {
        int id PK
        string slug UK
        string name UK
    }
    MAP {
        int id PK
        int gamemode_id FK
        string name UK
        string image_path
    }
    HERO {
        int id PK
        string slug UK
        string name UK
        string type "tank/damage/support"
        string color
    }
    MATCH {
        int id PK
        int encounter_id FK
        int map_id FK
        int home_team_id FK
        int away_team_id FK
        int home_score
        int away_score
        float time
        string log_name
    }
    MATCH_STATISTICS {
        int id PK
        int match_id FK
        int team_id FK
        int user_id FK "→ players.user"
        int hero_id FK "nullable"
        int round
        string name "enum LogStatsName"
        float value
    }
    MATCH_KILL_FEED {
        int id PK
        int match_id FK
        int killer_id FK
        int victim_id FK
        int killer_hero_id FK
        int victim_hero_id FK
        int killer_team_id FK
        int victim_team_id FK
        float damage
        bool is_critical_hit
    }
    MATCH_EVENT {
        int id PK
        int match_id FK
        int team_id FK
        int user_id FK
        int hero_id FK "nullable"
        int related_user_id FK "nullable"
        string name "enum MatchEvent"
    }
    ENCOUNTER {
        int id PK
    }
    TOURNAMENT_TEAM {
        int id PK
    }
    PLAYERS_USER {
        int id PK
    }

    GAMEMODE ||--o{ MAP : "карты режима"
    ENCOUNTER ||--o{ MATCH : "карты встречи"
    MAP ||--o{ MATCH : "сыграна карта"
    TOURNAMENT_TEAM |o--o{ MATCH : "home/away"
    MATCH ||--o{ MATCH_STATISTICS : "статистика"
    MATCH ||--o{ MATCH_KILL_FEED : "kill feed"
    MATCH ||--o{ MATCH_EVENT : "события/ассисты"
    PLAYERS_USER ||--o{ MATCH_STATISTICS : "игрок"
    HERO |o--o{ MATCH_STATISTICS : "герой"
    HERO ||--o{ MATCH_KILL_FEED : "killer/victim hero"
    PLAYERS_USER ||--o{ MATCH_KILL_FEED : "killer/victim"
    PLAYERS_USER ||--o{ MATCH_EVENT : "актор"
    HERO |o--o{ MATCH_EVENT : "герой"
```

---

## 7. Телеметрия рангов Overwatch (`overwatch_rank`)

Периодический сбор рангов через OverFast, привязан к battlenet-`social_account`
и `players.user`. `rank_snapshot` — временной ряд, `battle_tag_state` — стейт
планировщика (backoff/приоритет), `fetch_log` — история попыток воркера.

```mermaid
erDiagram
    RANK_SNAPSHOT {
        int id PK
        int user_id FK "→ players.user"
        int social_account_id FK "→ players.social_account (battlenet)"
        string battle_tag
        string platform
        string role
        string division "nullable (unranked)"
        int tier "nullable"
        int rank_value "nullable (mapped SR)"
        timestamp captured_at
    }
    BATTLE_TAG_STATE {
        int id PK
        int social_account_id FK "UNIQUE"
        int last_snapshot_id FK "nullable"
        string battle_tag
        string status
        int consecutive_failures
        timestamp next_eligible_at
        int priority_tier
    }
    FETCH_LOG {
        int id PK
        int social_account_id FK "nullable"
        string battle_tag
        string status
        string source
        int snapshots_written
        timestamp created_at
    }
    PLAYERS_USER {
        int id PK
    }
    PLAYERS_SOCIAL_ACCOUNT {
        int id PK
    }

    PLAYERS_USER ||--o{ RANK_SNAPSHOT : "ранги игрока"
    PLAYERS_SOCIAL_ACCOUNT ||--o{ RANK_SNAPSHOT : "по battlenet-аккаунту"
    PLAYERS_SOCIAL_ACCOUNT |o--o| BATTLE_TAG_STATE : "стейт сбора (1:0..1)"
    RANK_SNAPSHOT |o--o{ BATTLE_TAG_STATE : "последний снапшот"
    PLAYERS_SOCIAL_ACCOUNT |o--o{ FETCH_LOG : "история попыток"
```

---

## 8. Балансировка и регистрация (`balancer`)

Форма регистрации (`registration_form`), заявки игроков (`registration` + роли +
топ-герои + статусы), опциональный импорт из Google Sheets. Результат баланса —
`balance` → варианты → команды → слоты игроков. Конфиг балансера на уровне
турнира и воркспейса.

```mermaid
erDiagram
    BAL_REGISTRATION_FORM {
        int id PK
        int tournament_id FK "UNIQUE"
        int workspace_id FK
        bool is_open
        bool auto_approve
        json built_in_fields_json
        json custom_fields_json
    }
    BAL_REGISTRATION {
        int id PK
        int tournament_id FK
        int workspace_member_id FK "nullable, единственный якорь идентичности (SET NULL); dbarch02 удалил user_id"
        string battle_tag
        string battle_tag_normalized "UK(tournament, tag) активные"
        string status
        string balancer_status
        bool checked_in
        bool exclude_from_balancer
        timestamp submitted_at
        timestamp deleted_at "soft-delete"
    }
    BAL_REGISTRATION_ROLE {
        int id PK
        int registration_id FK "UK(registration, role)"
        string role
        string subrole "nullable"
        bool is_primary
        int priority
        int rank_value "nullable"
    }
    BAL_REGISTRATION_ROLE_HERO {
        int id PK
        int role_id FK "UK(role, priority); UK(role, hero)"
        int hero_id FK
        int priority
    }
    BAL_REGISTRATION_STATUS {
        int id PK
        int workspace_id FK "nullable; UK(workspace, scope, slug, kind)"
        string scope
        string slug
        string name
    }
    BAL_SHEET_FEED {
        int id PK
        int tournament_id FK "UNIQUE"
        string source_url
        string sheet_id
        bool auto_sync_enabled
        timestamp last_synced_at
    }
    BAL_SHEET_BINDING {
        int id PK
        int feed_id FK
        int registration_id FK "UNIQUE"
        string source_record_key "UK(feed, key)"
        string row_hash
    }
    BAL_BALANCE {
        int id PK
        int tournament_id FK "UNIQUE"
        int workspace_id FK "nullable"
        string algorithm
        json result_json
        int saved_by FK "nullable → auth.user"
        timestamp exported_at
    }
    BAL_BALANCE_VARIANT {
        int id PK
        int balance_id FK "UK(balance, variant_number)"
        int variant_number
        string algorithm
        float objective_score
        bool is_selected
    }
    BAL_TEAM {
        int id PK
        int balance_id FK
        int variant_id FK "nullable"
        int exported_team_id FK "nullable → tournament.team"
        string name
        float avg_sr
        int total_sr
    }
    BAL_TEAM_SLOT {
        int id PK
        int team_id FK
        string battle_tag_normalized
        string role
        int assigned_rank
        int discomfort
        bool is_captain
    }
    BAL_TOURNAMENT_CONFIG {
        int id PK
        int tournament_id FK "UNIQUE"
        int workspace_id FK
        json config_json
    }
    BAL_WORKSPACE_CONFIG {
        int id PK
        int workspace_id FK "UNIQUE"
        json config_json
    }
    TOURNAMENT {
        int id PK
    }
    WORKSPACE {
        int id PK
    }
    WORKSPACE_MEMBER {
        int id PK
    }
    HERO {
        int id PK
    }
    TOURNAMENT_TEAM {
        int id PK
    }

    TOURNAMENT |o--o| BAL_REGISTRATION_FORM : "форма (1:0..1)"
    TOURNAMENT ||--o{ BAL_REGISTRATION : "заявки"
    WORKSPACE_MEMBER |o--o{ BAL_REGISTRATION : "член (nullable — единственный якорь)"
    BAL_REGISTRATION ||--o{ BAL_REGISTRATION_ROLE : "роли"
    BAL_REGISTRATION_ROLE ||--o{ BAL_REGISTRATION_ROLE_HERO : "топ-герои"
    HERO ||--o{ BAL_REGISTRATION_ROLE_HERO : "герой"
    WORKSPACE ||--o{ BAL_REGISTRATION_STATUS : "каталог статусов (nullable)"
    TOURNAMENT |o--o| BAL_SHEET_FEED : "google-sheet (1:0..1)"
    BAL_SHEET_FEED ||--o{ BAL_SHEET_BINDING : "строки"
    BAL_REGISTRATION |o--o| BAL_SHEET_BINDING : "привязка строки"
    TOURNAMENT |o--o| BAL_BALANCE : "баланс (1:0..1)"
    BAL_BALANCE ||--o{ BAL_BALANCE_VARIANT : "варианты"
    BAL_BALANCE ||--o{ BAL_TEAM : "команды"
    BAL_BALANCE_VARIANT |o--o{ BAL_TEAM : "вариант"
    BAL_TEAM ||--o{ BAL_TEAM_SLOT : "слоты игроков"
    TOURNAMENT_TEAM |o--o{ BAL_TEAM : "экспорт в команду"
    TOURNAMENT |o--o| BAL_TOURNAMENT_CONFIG : "конфиг (1:0..1)"
    WORKSPACE |o--o| BAL_WORKSPACE_CONFIG : "конфиг (1:0..1)"
```

---

## 9. Live-драфт (`balancer.draft_*`)

Snake-драфт: сессия на турнир, команды с капитанами, пул игроков и последовательность
пиков (server-authoritative часы, optimistic-concurrency `version`). Пул берётся
из сохранённого баланса. Идентичность капитана/игрока/актора пика якорится на
`workspace_member` (dbarch03 удалил легаси `*_user_id`-колонки). Per-role
данные игрока (`role_ranks`/`role_top_heroes`/`secondary_roles_json`) вынесены
из JSON в дочерние `draft_player_role` + `draft_player_role_hero` (dbarch03).

```mermaid
erDiagram
    DRAFT_SESSION {
        int id PK
        int tournament_id FK "1 активная на турнир (partial-unique)"
        int workspace_id FK
        int current_pick_id FK "nullable (circular)"
        int source_balance_id FK "nullable → balancer.balance"
        string status "setup/ready/live/paused/…"
        string format "snake"
        int rounds
        int pick_time_seconds
    }
    DRAFT_TEAM {
        int id PK
        int session_id FK "UK(session, draft_position)"
        int captain_workspace_member_id FK "nullable → workspace_member (SET NULL); dbarch03 удалил captain_user_id"
        int captain_auth_user_id FK "nullable → auth.user (сигнал 'это я')"
        int exported_team_id FK "nullable → tournament.team"
        string name
        int draft_position
    }
    DRAFT_PLAYER {
        int id PK
        int session_id FK "UK(session, workspace_member_id)"
        int workspace_member_id FK "nullable → workspace_member (SET NULL); dbarch03 удалил user_id"
        int drafted_by_team_id FK "nullable"
        string battle_tag
        string primary_role
        string status "available/drafted/…"
        int rank_value "nullable"
        json additional_info "прочий per-player bag (role_ranks/top_heroes/secondary вынесены в дочерние)"
    }
    DRAFT_PLAYER_ROLE {
        int id PK
        int draft_player_id FK "UK(draft_player, role)"
        string role
        int rank_value "nullable"
        bool is_secondary
        int priority
    }
    DRAFT_PLAYER_ROLE_HERO {
        int id PK
        int draft_player_role_id FK "UK(role, priority); UK(role, hero)"
        int hero_id FK "→ overwatch.hero"
        int priority
    }
    DRAFT_PICK {
        int id PK
        int session_id FK "UK(session, overall_no)"
        int draft_team_id FK
        int picked_player_id FK "nullable"
        int picked_by_workspace_member_id FK "nullable → workspace_member (SET NULL); dbarch03 удалил picked_by_user_id"
        int overall_no
        int round_no
        string status "upcoming/…"
        int version "optimistic lock"
    }
    TOURNAMENT {
        int id PK
    }
    WORKSPACE {
        int id PK
    }
    BAL_BALANCE {
        int id PK
    }
    WORKSPACE_MEMBER {
        int id PK
    }
    HERO {
        int id PK
    }
    TOURNAMENT_TEAM {
        int id PK
    }

    TOURNAMENT ||--o{ DRAFT_SESSION : "драфты"
    WORKSPACE ||--o{ DRAFT_SESSION : "скоуп"
    BAL_BALANCE |o--o{ DRAFT_SESSION : "пул из баланса"
    DRAFT_SESSION ||--o{ DRAFT_TEAM : "команды"
    DRAFT_SESSION ||--o{ DRAFT_PLAYER : "пул игроков"
    DRAFT_SESSION ||--o{ DRAFT_PICK : "пики"
    DRAFT_TEAM ||--o{ DRAFT_PICK : "чей пик"
    DRAFT_TEAM |o--o{ DRAFT_PLAYER : "задрафтован в"
    DRAFT_PLAYER ||--o{ DRAFT_PLAYER_ROLE : "роли (primary + off-role)"
    DRAFT_PLAYER_ROLE ||--o{ DRAFT_PLAYER_ROLE_HERO : "топ-герои"
    HERO ||--o{ DRAFT_PLAYER_ROLE_HERO : "герой"
    DRAFT_PLAYER |o--o{ DRAFT_PICK : "выбранный игрок"
    DRAFT_PICK |o--o| DRAFT_SESSION : "текущий пик"
    WORKSPACE_MEMBER |o--o{ DRAFT_TEAM : "капитан (member)"
    WORKSPACE_MEMBER |o--o{ DRAFT_PLAYER : "игрок (member)"
    WORKSPACE_MEMBER |o--o{ DRAFT_PICK : "актор пика (member)"
    TOURNAMENT_TEAM |o--o{ DRAFT_TEAM : "экспорт команды"
```

---

## 10. Достижения (`achievements`)

Декларативный движок: `rule` (условие как JSON-дерево) → `evaluation_result`
(кто и почему квалифицировался) + `override` (ручной grant/revoke overlay) +
`evaluation_run` (аудит прогонов). Идентичность — через `workspace_member`.
Легаси-таблицы `achievements.achievement` и `achievements.user`
(`AchievementUser`) **удалены** (данные смигрированы, таблицы дропнуты).

```mermaid
erDiagram
    ACH_RULE {
        int id PK
        int workspace_id FK "UK(workspace, slug)"
        int hero_id FK "nullable"
        string slug
        string name
        string category
        string scope
        string grain
        json condition_tree
        bool enabled
        int rule_version
    }
    ACH_EVALUATION_RESULT {
        int id PK
        int achievement_rule_id FK
        int workspace_member_id FK "UK(rule, member, tournament, match)"
        int tournament_id FK "nullable"
        int match_id FK "nullable"
        json evidence_json
        uuid run_id
    }
    ACH_OVERRIDE {
        int id PK
        int achievement_rule_id FK
        int workspace_member_id FK
        int tournament_id FK "nullable"
        int match_id FK "nullable"
        string action "grant/revoke"
        int granted_by FK "→ auth.user"
    }
    ACH_EVALUATION_RUN {
        uuid id PK
        int workspace_id FK
        int tournament_id FK "nullable"
        string trigger
        string status
        int results_created
    }
    WORKSPACE {
        int id PK
    }
    WORKSPACE_MEMBER {
        int id PK
    }
    TOURNAMENT {
        int id PK
    }
    MATCH {
        int id PK
    }
    HERO {
        int id PK
    }

    WORKSPACE ||--o{ ACH_RULE : "определяет"
    HERO |o--o{ ACH_RULE : "герой-достижение"
    ACH_RULE ||--o{ ACH_EVALUATION_RESULT : "результаты"
    WORKSPACE_MEMBER ||--o{ ACH_EVALUATION_RESULT : "получатель"
    TOURNAMENT |o--o{ ACH_EVALUATION_RESULT : "по турниру"
    MATCH |o--o{ ACH_EVALUATION_RESULT : "по матчу"
    ACH_RULE ||--o{ ACH_OVERRIDE : "overlay"
    WORKSPACE_MEMBER ||--o{ ACH_OVERRIDE : "получатель"
    WORKSPACE ||--o{ ACH_EVALUATION_RUN : "прогоны"
    ACH_EVALUATION_RUN |o--o{ ACH_EVALUATION_RESULT : "прогон (run_id, SET NULL; FK dbarch01)"
```

---

## 11. Аналитика и ML (`analytics`)

Сигналы поверх матч-логов: per-tournament статистика игрока (`analytics.tournament`),
shift-алгоритмы, снапшоты качества баланса, feature-store и реестр ML-моделей,
per-player performance (v2), распределения мест (Монте-Карло,
`standings_distribution` — **единственный** источник прогноза мест: скалярный
`predicted_place = round(mean_position)`; v1-таблица `predictions` удалена
dbarch06), качество матчей и аномалии + обратная связь ревьюера. `job` — единый
трекер пересчёта.

```mermaid
erDiagram
    AN_ALGORITHM {
        int id PK
        string name UK
        bool produces_shifts
    }
    AN_PLAYER {
        int id PK
        int tournament_id FK
        int player_id FK "→ tournament.player"
        int wins
        int losses
        int shift "nullable"
    }
    AN_SHIFT {
        int id PK
        int tournament_id FK
        int algorithm_id FK
        int player_id FK
        float shift
        float confidence
    }
    AN_PERFORMANCE {
        int id PK
        int tournament_id FK
        int player_id FK
        int algorithm_id FK "UK(tournament, player, algorithm)"
        float impact_score
        float raw_value
        float local_percentile
    }
    AN_STANDINGS_DISTRIBUTION {
        int id PK
        int tournament_id FK
        int team_id FK
        int algorithm_id FK
        float mean_position
        float prob_top1
        json position_histogram
    }
    AN_MATCH_QUALITY {
        int id PK
        int encounter_id FK
        int algorithm_id FK "UK(encounter, algorithm)"
        float quality_score
        json anomaly_flags
    }
    AN_PLAYER_ANOMALY {
        int id PK
        int tournament_id FK
        int player_id FK
        int source_encounter_id FK "nullable"
        string kind
        float score
    }
    AN_ANOMALY_FEEDBACK {
        int id PK
        int tournament_id FK
        int player_id FK "UK(tournament, player, kind)"
        int reviewer_user_id FK "nullable → auth.user"
        string kind
        string verdict
    }
    AN_BALANCE_SNAPSHOT {
        int id PK
        int tournament_id FK
        int balance_id FK "→ balancer.balance"
        int variant_id FK "nullable"
        int workspace_id FK "nullable"
        float avg_sr_overall
        float sr_std_dev
    }
    AN_BALANCE_PLAYER_SNAPSHOT {
        int id PK
        int balance_snapshot_id FK
        int tournament_id FK
        int user_id FK "nullable → players.user"
        int team_id FK "nullable"
        string assigned_role
        int assigned_rank
    }
    AN_ML_FEATURE {
        int id PK
        int tournament_id FK "UK(tournament, granularity, entity, feature_version)"
        string granularity
        int entity_id
        string feature_version
        json features
    }
    AN_ML_MODEL_ARTIFACT {
        int id PK
        int algorithm_id FK "UK(algorithm, model_kind, role, version)"
        int training_cutoff_tournament_id FK "nullable"
        string model_kind
        string version
        string storage_uri
        bool is_active
    }
    AN_EXPLANATION {
        int id PK
        int algorithm_id FK
        int tournament_id FK
        int entity_id
        string entity_kind
        json contributions
    }
    AN_JOB {
        int id PK
        int workspace_id FK "nullable; 1 running per workspace (partial-unique)"
        int tournament_id FK
        int requested_by_user_id FK "nullable → auth.user"
        string kind "compute/train_ml"
        string status
        json progress
    }
    TOURNAMENT {
        int id PK
    }
    PLAYER {
        int id PK
    }
    TOURNAMENT_TEAM {
        int id PK
    }
    ENCOUNTER {
        int id PK
    }
    BAL_BALANCE {
        int id PK
    }

    TOURNAMENT ||--o{ AN_PLAYER : "статистика игрока"
    PLAYER ||--o{ AN_PLAYER : "игрок"
    AN_ALGORITHM ||--o{ AN_SHIFT : "алгоритм"
    TOURNAMENT ||--o{ AN_SHIFT : "турнир"
    PLAYER ||--o{ AN_SHIFT : "игрок"
    AN_ALGORITHM ||--o{ AN_PERFORMANCE : "алгоритм"
    PLAYER ||--o{ AN_PERFORMANCE : "игрок"
    AN_ALGORITHM ||--o{ AN_STANDINGS_DISTRIBUTION : "алгоритм"
    TOURNAMENT_TEAM ||--o{ AN_STANDINGS_DISTRIBUTION : "команда"
    ENCOUNTER ||--o{ AN_MATCH_QUALITY : "встреча"
    AN_ALGORITHM ||--o{ AN_MATCH_QUALITY : "алгоритм"
    PLAYER ||--o{ AN_PLAYER_ANOMALY : "аномалия"
    ENCOUNTER |o--o{ AN_PLAYER_ANOMALY : "источник"
    PLAYER ||--o{ AN_ANOMALY_FEEDBACK : "вердикт"
    BAL_BALANCE ||--o{ AN_BALANCE_SNAPSHOT : "снапшот баланса"
    AN_BALANCE_SNAPSHOT ||--o{ AN_BALANCE_PLAYER_SNAPSHOT : "по игрокам"
    AN_ALGORITHM ||--o{ AN_ML_MODEL_ARTIFACT : "модель"
    AN_ALGORITHM ||--o{ AN_EXPLANATION : "атрибуция"
    TOURNAMENT ||--o{ AN_JOB : "пересчёты"
```

---

## 12. Платформа / операционные таблицы

Кросс-доменная инфраструктура: transactional outbox (`event_outbox`), журнал
realtime-событий (`workspace_event`), глобальные настройки (`settings`),
пайплайн загрузки логов (`log_processing.record`, `discord_channel`) и durable-
джобы вычисления сетки/итогов (`computation_job`, `recalculation_state`).

> `event_outbox` и `workspace_event` намеренно **без FK** — это append-only
> шины/журналы (`workspace_id`/`tournament_id`/`actor_user_id` хранятся как
> обычные `BigInteger` для развязки от жизненного цикла бизнес-строк).

```mermaid
erDiagram
    EVENT_OUTBOX {
        int id PK
        string event_id UK
        string event_type
        string routing_key
        json payload_json
        string status
        int attempts
        timestamp next_attempt_at
    }
    WORKSPACE_EVENT {
        int id PK
        string topic
        string event_type
        int workspace_id "не FK"
        int tournament_id "не FK"
        int actor_user_id "не FK"
        json payload
        timestamp occurred_at
    }
    SETTINGS {
        int id PK
        string key UK "напр. parser.rank_collection"
        json value
        int updated_by FK "nullable → auth.user"
    }
    LOG_RECORD {
        int id PK
        int tournament_id FK
        int uploader_id FK "nullable → players.user"
        int attached_encounter_id FK "nullable"
        string filename
        string status "pending/processing/done/failed"
        string source "upload/discord/manual"
        string content_hash
    }
    DISCORD_CHANNEL {
        int id PK
        int tournament_id FK "UNIQUE"
        int guild_id
        int channel_id UK
        bool is_active
    }
    COMPUTATION_JOB {
        int id PK
        int tournament_id FK
        int stage_id FK "nullable"
        int stage_item_id FK "nullable"
        int requested_by_user_id FK "nullable → auth.user"
        string kind
        string status
        string idempotency_key "partial-unique активные"
    }
    RECALCULATION_STATE {
        int tournament_id PK "FK → tournament"
        int requested_generation
        int completed_generation
    }
    TOURNAMENT {
        int id PK
    }
    STAGE {
        int id PK
    }
    ENCOUNTER {
        int id PK
    }
    PLAYERS_USER {
        int id PK
    }
    AUTH_USER {
        int id PK
    }

    TOURNAMENT ||--o{ LOG_RECORD : "логи турнира"
    PLAYERS_USER |o--o{ LOG_RECORD : "загрузивший"
    ENCOUNTER |o--o{ LOG_RECORD : "привязка к встрече"
    TOURNAMENT |o--o| DISCORD_CHANNEL : "канал сбора (1:0..1)"
    TOURNAMENT ||--o{ COMPUTATION_JOB : "джобы вычисления"
    STAGE |o--o{ COMPUTATION_JOB : "по стадии"
    TOURNAMENT |o--o| RECALCULATION_STATE : "счётчик поколений (1:1)"
    AUTH_USER |o--o{ SETTINGS : "кто менял"
    AUTH_USER |o--o{ COMPUTATION_JOB : "инициатор"
```

---

## Заметки по чтению диаграмм

- **Мультитенантность.** Почти каждая бизнес-таблица несёт `workspace_id`
  (напрямую или транзитивно через `tournament`/`workspace_member`). Глобальные
  сущности (роль/деней/сетка/статус) допускают `workspace_id = NULL`.
- **Двойная идентичность.** `auth.user` (вход) и `players.user` (игрок) — разные
  таблицы, связь `1:0..1`. Ростер (`tournament.player`), регистрации
  (`balancer.registration`), драфт (`draft_*`) и достижения
  (`evaluation_result`/`override`) якорятся на `workspace_member`
  (= уникальность `workspace_id + player_id`), что и есть суть
  identity/workspace-рефактора. Денормализованной роли на `workspace_member`
  нет — роль выводится из RBAC.
- **Единственный legacy.** Осталась только `tournament.group` (→ `stage`).
  `achievements.achievement`/`achievements.user` и `analytics.predictions`
  (v1) — **удалены** (см. «История изменений схемы»).
- **Циклические FK.** `draft_session.current_pick_id ↔ draft_pick.session_id`
  (создаётся с `use_alter`); `division_grid_version.created_from_version_id` и
  `tournament.player.related_player_id` — само-ссылки.
- **Enum `encounterstatus`.** Тип перенесён из схемы `public` в `tournament`
  (dbarch01); хранит имя члена (`COMPLETED`/`PENDING`/`OPEN`), не `.value`.
- `mv_hero_global_stats` — **materialized view** (не в диаграммах как таблица):
  глобальные рекорды по (hero, stat), обновляется вне транзакций.

---

## История изменений схемы

Документ актуализирован под финальное состояние (Alembic head — **`dbarch06`**).
Ключевые изменения относительно прежнего mid-refactor состояния:

- **Identity/workspace-рефактор.** `players.user.auth_user_id` (unique nullable;
  NULL = shadow-player) — линк `1:0..1` к `auth.user`. `public.workspace_member`
  ключуется на `player_id` (FK → `players.user`) с уникальностью
  `(workspace_id, player_id)`; денормализованная роль убрана. На
  `workspace_member_id` теперь якорятся `balancer.registration` (dbarch02),
  `tournament.player` (iwrefac07, NOT NULL), `draft_team`/`draft_player`/`draft_pick`
  (dbarch03) и `achievements.evaluation_result`/`override`.
- **Challonge-нормализация (dbarch04 + dbarch04b).** Удалены
  `tournament.tournament.challonge_id`/`challonge_slug`,
  `tournament.stage.challonge_id`/`challonge_slug`,
  `tournament.encounter.challonge_id` и таблица `tournament.challonge_team`.
  Источник правды — `challonge_source` + `challonge_participant_mapping` +
  `challonge_match_mapping` + `challonge_sync_log`. **Оставлены**
  `tournament.group.challonge_id`/`challonge_slug` (routing-значение
  `match.group_id` по группам).
- **JSON-нормализация (dbarch05).** `map_veto_config.map_pool_ids` (JSON) →
  дочерняя `map_veto_config_map`; `veto_sequence_json` остался JSON.
- **Draft-нормализация (dbarch03).** `draft_player.role_ranks`/`role_top_heroes`/
  `secondary_roles_json` (JSON) → `draft_player_role` + `draft_player_role_hero`.
- **Predictions (dbarch06).** `analytics.predictions` (v1) удалена;
  `analytics.standings_distribution` (v2) — единственный источник прогноза мест.
- **Гигиена индексов/FK (dbarch01).** Индексы на `auth.user_roles`/
  `auth.role_permissions`; новые FK: `achievements.evaluation_result.run_id →
  evaluation_run`, `players.user_merge_audit.source_user_id`/`target_user_id →
  players.user`, `auth.user_permission_deny.created_by → auth.user`; перенос
  типа `encounterstatus` `public` → `tournament`; частичный unique-индекс на
  `players.social_account` для NULL-хендлов.
