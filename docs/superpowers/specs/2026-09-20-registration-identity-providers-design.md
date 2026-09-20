# Провайдеры идентичности в регистрации — дизайн

**Дата:** 2026-09-20
**Статус:** на согласовании
**Метод:** superpowers:brainstorming (архитектурный путь)

---

## 1. Проблема

Провайдер аккаунта не существует как понятие. Вместо него — набор полей,
добавленных по-разному, и справочники провайдера, размноженные по обеим
сторонам стека. Добавление одного провайдера сегодня — правка ~20 файлов.

### 1.1 Справочник label/иконка — 6 копий

| Где | Что хранит |
|---|---|
| `backend/shared/services/admission/gates.py:48` `_PROVIDER_LABELS` | подписи для текста правила подписки |
| `frontend/src/lib/social-providers.ts:39` `SOCIAL_PROVIDER_CONFIG` | label, icon, color, placeholder, profileUrl, oauthEligible |
| `frontend/src/lib/oauth-providers.ts:3` `OAUTH_PROVIDER_META` | title + icon (подмножество предыдущего) |
| `frontend/src/lib/subscription-requirement.ts:27` `PROVIDER_LABELS` | подписи |
| `frontend/src/components/admin/collectors/subscription-shared.tsx:47` `PROVIDER_LABELS` | подписи |
| `frontend/src/components/admin/OAuthProviderBadge.tsx:7` `PROVIDER_META` | label + иконка |

### 1.2 Regex BattleTag — 5 мест, 3 разные грамматики

| Место | Грамматика | Кто применяет |
|---|---|---|
| `frontend/src/components/balancer/form/_components/formConfig.ts:30` | `[^#]{2,12}#[0-9]{4,}` | дефолт конфига формы (админка) |
| `frontend/src/components/registration/validation.ts:39` | `[^#]{2,12}#[0-9]{4,}` | живая валидация визарда |
| `backend/app-service/src/core/config.py:9` | `[\w0-9]{2,12}#[0-9]{4,}` | настройка сервиса |
| `backend/parser-service/src/core/config.py:10` | `[\w0-9]{2,12}#[0-9]{4,}` | сбор рангов |
| `backend/tournament-service/src/domain/registration/utils.py:41` | `[\w][\w ]{0,30}#[0-9]{3,}` | парсинг Google-таблиц |

Один и тот же тег валиден в одном месте и невалиден в другом. Кириллический
ник проходит фронт и отвергается `app-service`; тег с пробелом проходит фронт и
парсер таблиц, но не `app-service`.

Остальные грамматики (`formConfig.ts:31-33`): Discord `^[a-z0-9_.]{2,32}$`,
Twitch `^[a-zA-Z0-9_]{4,25}$`, Boosty `^[^#]{2,50}$` — существуют только на
фронте; бэк их не знает вовсе и валидирует эти поля лишь тем, что организатор
случайно сохранил в конфиге формы.

### 1.3 Нормализация хэндла — 4 копии

`backend/shared/core/social.py:72`, `backend/tournament-service/src/services/registration/validation.py:180`
(`_canonicalize_battle_tag`), `frontend/src/components/registration/validation.ts:44`
(`normalizeBattleTag`), `frontend/src/components/registration/validation.ts:146`
(`normalizeSocialHandle`). Плюс две копии SQL-нормализатора в миграциях
(`mrank01_member_rank.py:42`, `draftreg1_draft_player_registration.py:153`).

### 1.4 Маппинг «поле → провайдер» — 2 копии, плюс литералы

`backend/tournament-service/src/services/registration/validation.py:34`
`VERIFIED_FIELD_PROVIDERS` + `:39` `_VERIFIED_FIELD_LABELS` + `:347` литеральный
кортеж полей ↔ `frontend/src/components/registration/validation.ts:24` +
`:11` `BUILT_IN_LABELS` + `:30` `BUILT_IN_LABEL_KEYS`.

### 1.5 Извлечение хэндла из OAuth-ответа — 3 копии

`backend/identity-service/src/services/oauth_accounts.py:190` `_oauth_handle`,
`backend/shared/services/social_identity.py:313` `_oauth_handle_candidates`,
`backend/identity-service/src/services/players.py:113` `_verify_ownership`.

### 1.6 UI — блок на провайдера

`frontend/src/components/registration/AccountStep.tsx:110-237` — четыре почти
идентичных блока, каждый со своей веткой `requireVerified ? VerifiedAccountSelect
: AccountCombobox`. Плюс `UnifiedRegistrationForm.tsx:657-660` — четыре списка
подсказок и `:754-757` — четыре пропса.

### 1.7 Список аккаунтов умеет только Battle.net

`smurf_tags` — отдельное встроенное поле (`smurf_tags_json`, `SmurfTagsInput`,
`_validate_list_pattern`, `parser: battle_tag_list` в маппинге таблиц). Для
Discord/Twitch/Boosty второго аккаунта указать нельзя вообще.

### 1.8 Хранение

`balancer.registration` держит по колонке на провайдера
(`backend/shared/models/registration/registration.py:207-212`):
`battle_tag`, `battle_tag_normalized`, `smurf_tags_json` (JSON),
`discord_nick`, `twitch_nick`, `boosty_nick`. Конфиг формы — JSON
(`built_in_fields_json`, `custom_fields_json`), ответы на пользовательские
поля — тоже JSON (`registration.custom_fields_json`).

Уникальность хэндла в турнире существует только для BattleTag
(`registration.py:180-186` `uq_balancer_registration_tournament_tag_active`).
Два участника одного турнира могут указать один Discord — это не ловится ничем.

---

## 2. Принятые решения

| Вопрос | Решение |
|---|---|
| Где живёт истина для фронта | **Вариант A** — реестр приезжает по сети (`GET /identity/providers`), фронт не пересобирается при добавлении провайдера |
| Список аккаунтов | **У всех провайдеров**, по образцу Battle.net. `smurf_tags` как понятие исчезает |
| Канон BattleTag | `[^#\s]{2,12}#\d{4,}` |
| Хранение | **Полная нормализация до 3НФ**, JSON-поля удаляются |

---

## 3. Модель домена

### 3.1 Реестр провайдеров

`backend/shared/core/social.py` — единственный источник истины.

> **Реализовано (фаза 0).** Дизайн предполагал новый модуль
> `shared/domain/identity/providers.py`. Каталог положен в уже существующий
> `shared/core/social.py`, чей докстринг и так объявлял его «single source of
> truth for the set of social providers»: это сняло 36 правок импортов, не
> создало ребра `core → domain` (обратного принятому в репозитории направлению)
> и оставило каталог модулем без зависимостей.

```python
@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str                              # 'battlenet' — ключ social_account.provider
    label: str
    order: int

    handle_pattern: str                  # БЕЗ якорей; якоря ставит валидатор
    handle_error_key: str                # i18n-ключ, не готовая строка
    normalize: Literal["casefold", "battletag"]

    supports_text: bool = True
    supports_oauth: bool = False
    supports_subscription: bool = False

    default_max_count: int = 1           # battlenet: 5 (бывшие смурфы)
    profile_url: str | None = None       # 'https://twitch.tv/{handle}'

    # Поля сырого OAuth-ответа: чем ЗАПИСАТЬ хэндл и чем его можно НАЗВАТЬ.
    # Раньше эти две формы жили в трёх местах (oauth_accounts._oauth_handle,
    # social_identity._oauth_handle_candidates, players._verify_ownership).
    oauth_primary_fields: tuple[str, ...] = ()
    oauth_alias_fields: tuple[str, ...] = ()
```

Начальное наполнение:

| id | pattern | normalize | oauth | subscription | default_max_count |
|---|---|---|---|---|---|
| `battlenet` | `[^#\s]{2,12}#\d{4,}` | `battletag` | да | нет | 5 |
| `discord` | `[a-z0-9_.]{2,32}(?:#\d{4})?` | `casefold` | да | да | 1 |
| `twitch` | `[a-z0-9_]{4,25}` | `casefold` | да | да | 1 |
| `boosty` | `[^#\s]{2,50}` | `casefold` | нет | да | 1 |
| `vk` | `[a-z0-9_.]{3,32}` | `casefold` | нет | нет | 1 |
| `youtube` | `@?[a-z0-9_.\-]{3,30}` | `casefold` | нет | нет | 1 |

Грамматики записаны в нижнем регистре и матчатся против НОРМАЛИЗОВАННОГО
хэндла — см. ниже. Хвост `(?:#\d{4})?` у Discord — снятый в 2023 дискриминатор:
аккаунты, зарегистрированные до миграции, до сих пор носят `name#0001`, и
грамматика без него отвергала бы существующие регистрации.

Якоря (`\A…\Z` / `^(?:…)$`) навешивает один валидатор на каждой стороне —
паттерны в реестре и в пользовательских override хранятся без якорей. Сегодня
дефолты Discord/Twitch/Boosty якоря содержат, а BattleTag — нет; это
рассогласование исчезает.

### 3.2 Что выводится из реестра и перестаёт существовать

| Удаляется | Чем заменяется | Фаза |
|---|---|---|
| `shared/core/social.py:33` `SOCIAL_PROVIDERS` | `frozenset(PROVIDERS)` | 0 ✅ |
| `shared/core/social.py:45` `OAUTH_PROVIDERS` | `{p.id for p in PROVIDERS.values() if p.supports_oauth}` | 0 ✅ |
| `shared/core/social.py:48` `OAUTH_TO_SOCIAL` | `social_provider_for_oauth()` — тот же guard «не всякий OAuth-вход даёт social-идентичность», без второй таблицы | 0 ✅ |
| `shared/core/social.py:72` ветка battlenet | диспатч по `spec.normalize` | 0 ✅ |
| `tournament-service/.../validation.py:29,34,39` | один `_IDENTITY_FIELDS` (колонка → провайдер + label), остальное выводится | 0 ✅ |
| `tournament-service/.../validation.py:180` `_canonicalize_battle_tag` | `normalize_social_handle` | 0 ✅ |
| `tournament-service/.../validation.py:347` кортеж полей | итерация по `_IDENTITY_FIELDS` + `_FREE_TEXT_FIELDS` | 0 ✅ |
| `identity-service/.../oauth_accounts.py:190` `_oauth_handle` | `oauth_handle()` | 0 ✅ |
| `shared/services/social_identity.py:313` per-provider ветки | `oauth_handle_candidates()` | 0 ✅ |
| `app-service/.../users_admin.py:273` проверка «есть `#`» | `matches_handle_pattern()` — админский путь и самозапись дают одну форму | 0 ✅ |
| `shared/services/admission/gates.py:48` `_PROVIDER_LABELS` | `PROVIDERS[id].label` | 0 ✅ |
| `app-service/src/core/config.py:9`, `parser-service/src/core/config.py:10` `battle_tag_regex` | `PROVIDERS["battlenet"].handle_pattern` | 0 ✅ |
| `tournament-service/.../export.py:37` `_registration_identity_handles` | цикл по `registration_identity` | 2c |
| `frontend/src/lib/oauth-providers.ts` целиком | `lib/identity-providers.ts` | 1 |
| `frontend/src/lib/subscription-requirement.ts:27` `PROVIDER_LABELS` | то же | 1 |
| `frontend/.../subscription-shared.tsx:47` `PROVIDER_LABELS` | то же | 1 |
| `frontend/.../OAuthProviderBadge.tsx:7` `PROVIDER_META` | то же | 1 |
| `frontend/src/lib/social-providers.ts:39` (семантическая половина) | то же; иконка и цвет остаются локально | 1 |
| `frontend/.../formConfig.ts:30-33` четыре regex | сервер присылает готовый | 1 |
| `frontend/.../registration/validation.ts:24,30,39,44,146` | сервер присылает готовый | 1 |

Фаза 0 добавила то, чего в дизайне не было и что вылезло при реализации:

- **Организаторский regex стал ограниченным и кешируемым.** `compile_handle_pattern`
  режет паттерны длиннее 256 символов и поднимает `InvalidHandlePattern`;
  `validation.py` превращает это в 422 «форма настроена неверно» вместо 500.
  Раньше паттерн компилировался заново на каждом сабмите и падал `re.error`.
- **Грамматика применяется к нормализованному хэндлу.** Иначе каждая грамматика
  обязана заново кодировать правила нормализатора — именно так они и разошлись.

`tournament-service/src/domain/registration/utils.py:41` `BATTLE_TAG_RE`
переименовывается в `BATTLE_TAG_SCAN_RE` и остаётся как есть: это сканер
произвольного текста из Google-таблиц, у него другая задача (найти тег в
строке), и делать его строгим валидатором нельзя.

### 3.3 Способ указания аккаунта: capability × policy

```
capability = {text if spec.supports_text} ∪ {oauth if spec.supports_oauth}
policy     = form_field.input_mode          # 'any' | 'text' | 'oauth'
effective  = policy == 'any' ? capability : {policy} ∩ capability
```

`effective == ∅` — ошибка **при сохранении формы организатором**, а не тихий
даунгрейд в рантайме: турнир не должен обещать верификацию, которую невозможно
выдать (`input_mode='oauth'` для Boosty).

| effective | UI |
|---|---|
| `{text}` | список текстовых полей с regex-валидацией, подсказки — свои аккаунты провайдера |
| `{oauth}` | список выбирается из OAuth-подтверждённых `social_account`; пусто → CTA «привязать аккаунт» |
| `{text, oauth}` | выбор из подтверждённых + пункт «ввести вручную»; по умолчанию primary verified |

`require_verified` (булев, `BuiltInFieldConfig.require_verified`) удаляется
полностью: `true` мигрирует в `input_mode='oauth'`, `false` — в `'any'`.

---

## 4. Схема базы

### 4.1 `balancer.registration_identity`

Заменяет `registration.battle_tag`, `battle_tag_normalized`, `smurf_tags_json`,
`discord_nick`, `twitch_nick`, `boosty_nick`.

```sql
CREATE TABLE balancer.registration_identity (
    id                bigserial PRIMARY KEY,
    registration_id   bigint      NOT NULL,
    tournament_id     bigint      NOT NULL,
    provider          varchar(32) NOT NULL,
    handle            varchar(255) NOT NULL,
    handle_normalized varchar(255) NOT NULL,
    is_primary        boolean     NOT NULL DEFAULT false,
    position          smallint    NOT NULL DEFAULT 0,
    social_account_id bigint      NULL REFERENCES players.social_account(id) ON DELETE SET NULL,
    verified_at       timestamptz NULL,
    deleted_at        timestamptz NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_registration_identity_registration
        FOREIGN KEY (registration_id, tournament_id)
        REFERENCES balancer.registration (id, tournament_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_registration_identity_handle
    ON balancer.registration_identity (registration_id, provider, handle_normalized);

CREATE UNIQUE INDEX uq_registration_identity_primary
    ON balancer.registration_identity (registration_id, provider) WHERE is_primary;

CREATE UNIQUE INDEX uq_registration_identity_tournament
    ON balancer.registration_identity (tournament_id, provider, handle_normalized)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_registration_identity_lookup
    ON balancer.registration_identity (provider, handle_normalized);
```

`social_account_id IS NOT NULL` ⇔ аккаунт выбран через OAuth; `verified_at` —
снимок момента подтверждения. Текстовый ввод оставляет оба NULL.

**Денормализация.** `tournament_id` и `deleted_at` физически принадлежат
родителю. Они продублированы, потому что Postgres не строит уникальный индекс
через join, а `uq_registration_identity_tournament` — правило допуска («этим
тегом в этом турнире уже зарегистрировались»), которое нельзя оставлять
дисциплине сервисного слоя при конкурентных командных регистрациях.

- `tournament_id` держится составным FK на `registration (id, tournament_id)`
  (требуется добавить туда `UNIQUE (id, tournament_id)`) — согласованность
  доказуема, триггер не нужен.
- `deleted_at` FK'ом не выражается → один триггер
  `AFTER UPDATE OF deleted_at ON balancer.registration`, распространяющий
  значение на дочерние строки. Это единственная скрытая логика в дизайне.

**Что чинится попутно:** `uq_registration_identity_tournament` покрывает всех
провайдеров, а не только BattleTag. Сегодняшняя дыра (два участника с одним
Discord) закрывается.

### 4.2 Конфиг формы

Заменяет `registration_form.built_in_fields_json`
(`backend/shared/models/registration/registration.py:42`).

```sql
CREATE TABLE balancer.registration_form_field (
    id            bigserial PRIMARY KEY,
    form_id       bigint      NOT NULL REFERENCES balancer.registration_form(id) ON DELETE CASCADE,
    field_key     varchar(32) NULL,       -- 'primary_role' | 'flex_role' | 'top_heroes' | 'stream_pov' | 'notes'
    provider      varchar(32) NULL,       -- заполнено вместо field_key для identity-полей
    enabled       boolean     NOT NULL DEFAULT true,
    required      boolean     NULL,       -- только не-identity; у identity роль «обязательности» играет min_count
    position      smallint    NOT NULL DEFAULT 0,

    input_mode    varchar(8)  NULL,       -- identity: 'any'|'text'|'oauth'
    min_count     smallint    NULL,       -- identity: минимум аккаунтов (0 = поле необязательно)
    max_count     smallint    NULL,       -- identity: максимум аккаунтов
    regex_override         varchar(255) NULL,
    error_message_override varchar(255) NULL,

    max_heroes    smallint    NULL,       -- top_heroes
    flex_mode     varchar(16) NULL,       -- flex_role: 'optional'|'all_roles'|'forced'

    CONSTRAINT ck_registration_form_field_kind
        CHECK ((field_key IS NULL) <> (provider IS NULL)),
    -- identity-строка описывается счётчиками, не булевой обязательностью;
    -- два источника «обязательно ли поле» разошлись бы при первом же расхождении
    CONSTRAINT ck_registration_form_field_identity_attrs
        CHECK (
            CASE WHEN provider IS NOT NULL
                 THEN required IS NULL AND input_mode IS NOT NULL
                      AND min_count IS NOT NULL AND max_count IS NOT NULL
                      AND min_count >= 0 AND max_count >= min_count AND max_count >= 1
                 ELSE required IS NOT NULL AND input_mode IS NULL
                      AND min_count IS NULL AND max_count IS NULL
                      AND regex_override IS NULL
            END
        )
);

CREATE UNIQUE INDEX uq_registration_form_field_key
    ON balancer.registration_form_field (form_id, field_key) WHERE field_key IS NOT NULL;
CREATE UNIQUE INDEX uq_registration_form_field_provider
    ON balancer.registration_form_field (form_id, provider) WHERE provider IS NOT NULL;

CREATE TABLE balancer.registration_form_field_subrole (
    field_id     bigint      NOT NULL REFERENCES balancer.registration_form_field(id) ON DELETE CASCADE,
    role_code    varchar(16) NOT NULL,
    subrole_slug varchar(64) NOT NULL,
    PRIMARY KEY (field_id, role_code, subrole_slug)
);
```

Nullable-колонки 3НФ не нарушают: каждый атрибут функционально зависит от
полного ключа `(form_id, field_key|provider)`. Нарушением была 1НФ — JSON и
повторяющиеся группы; группы (`subroles`, `options`) вынесены в свои таблицы.
Дробление на subtype-таблицы под каждый вид поля не требуется и добавило бы
четыре join'а к чтению, которое всегда идёт целиком.

### 4.3 Пользовательские поля и ответы

Заменяют `registration_form.custom_fields_json` и `registration.custom_fields_json`.

```sql
CREATE TABLE balancer.registration_form_custom_field (
    id            bigserial PRIMARY KEY,
    form_id       bigint       NOT NULL REFERENCES balancer.registration_form(id) ON DELETE CASCADE,
    field_key     varchar(64)  NOT NULL,
    label         varchar(255) NOT NULL,
    field_type    varchar(16)  NOT NULL,   -- text|number|select|checkbox|url
    required      boolean      NOT NULL DEFAULT false,
    placeholder   varchar(255) NULL,
    regex         varchar(255) NULL,
    error_message varchar(255) NULL,
    show_in_draft boolean      NOT NULL DEFAULT false,
    position      smallint     NOT NULL DEFAULT 0,
    UNIQUE (form_id, field_key)
);

CREATE TABLE balancer.registration_form_custom_option (
    field_id bigint       NOT NULL REFERENCES balancer.registration_form_custom_field(id) ON DELETE CASCADE,
    value    varchar(255) NOT NULL,
    position smallint     NOT NULL DEFAULT 0,
    PRIMARY KEY (field_id, value)
);

CREATE TABLE balancer.registration_custom_answer (
    registration_id bigint NOT NULL REFERENCES balancer.registration(id) ON DELETE CASCADE,
    field_id        bigint NOT NULL REFERENCES balancer.registration_form_custom_field(id) ON DELETE CASCADE,
    value_text      text   NULL,
    PRIMARY KEY (registration_id, field_id)
);
```

Ответ ссылается на определение поля по id, а не по строковому ключу — переимено-
вание поля перестаёт осиротять ответы (сегодня `custom_fields_json` — словарь по
ключу, и `makeUniqueCustomFieldKey` существует ровно чтобы этого избежать).

### 4.4 Что удаляется

| Объект | Файл |
|---|---|
| `registration.battle_tag`, `battle_tag_normalized`, `smurf_tags_json`, `discord_nick`, `twitch_nick`, `boosty_nick` | `shared/models/registration/registration.py:207-212` |
| `uq_balancer_registration_tournament_tag_active` | там же, `:180-186` |
| `registration.custom_fields_json` | там же, `:219` |
| `registration_form.built_in_fields_json`, `custom_fields_json` | там же, `:42` и рядом |

### 4.5 Вне объёма

- `tournament.encounter_report_form.built_in_fields_json`
  (`shared/models/tournament/encounter_report.py:187`) — та же форма конфига,
  но другая сущность. Не трогаем.
- `workspace_player.battle_tag_normalized`, `balancer.team_slot.battle_tag_normalized` —
  остаются. Это каноникализированный ключ игрока воркспейса и слота, не
  регистрационная идентичность.
- `players.social_account` — уже нормализована, меняется только чтение.

---

## 5. Контракт API

### 5.1 Реестр (новый, глобальный, кешируемый)

`GET /identity/providers` →

```json
[{"id":"battlenet","label":"Battle.net","order":0,
  "handle_pattern":"[^#\\s]{2,12}#\\d{4,}","handle_error_key":"identity.battlenet.format",
  "normalize":"battletag","supports_text":true,"supports_oauth":true,
  "supports_subscription":false,"default_max_count":5,
  "profile_url":null}]
```

Потребители: страница профиля (привязка аккаунтов, `SocialAccountsEditor`,
бейджи), админка OAuth, редактор требований подписки. Кеш — сутки; реестр
глобальный, не зависит от турнира.

### 5.2 Чтение формы регистрации

`RegistrationFormRead.built_in_fields` (словарь) заменяется на два массива:

```json
{
  "identity_fields": [
    {"provider":"battlenet","enabled":true,
     "input_mode":"any","min_count":1,"max_count":5,
     "regex":"[^#\\s]{2,12}#\\d{4,}","error_message":null,"position":0}
  ],
  "fields": [
    {"field_key":"flex_role","enabled":true,"required":false,"flex_mode":"optional","position":4}
  ],
  "custom_fields": [
    {"id":41,"field_key":"team_name","label":"Команда","field_type":"text",
     "required":false,"placeholder":null,"regex":null,"error_message":null,
     "options":[],"show_in_draft":false,"position":0}
  ]
}
```

`regex` — **уже слитый** сервером `regex_override ?? spec.handle_pattern`. Фронт
о существовании дефолтов не знает; разойтись нечему. У identity-полей нет
`required`: обязательность выражается через `min_count >= 1` (см. §4.2).

### 5.3 Отправка регистрации

`RegistrationCreate` / `RegistrationUpdate`: поля `battle_tag`, `smurf_tags`,
`discord_nick`, `twitch_nick`, `boosty_nick` заменяются одним:

```json
{"identities":[
  {"provider":"battlenet","handle":"Ana#1234","is_primary":true},
  {"provider":"battlenet","handle":"Alt#1111","is_primary":false},
  {"provider":"discord","handle":"ana","is_primary":true}
]}
```

Серверная валидация (одна функция, реестр + конфиг формы):

1. провайдер известен и включён в форме;
2. `min_count ≤ len(handles) ≤ max_count`;
3. ровно один `is_primary`, если список непуст;
4. каждый хэндл матчит `regex_override ?? spec.handle_pattern` после
   `normalize_social_handle`;
5. нет дублей по `handle_normalized` внутри провайдера;
6. `input_mode='oauth'` → каждый хэндл совпадает с OAuth-подтверждённым
   `social_account` игрока (текущая `validate_verified_identity`, обобщённая на
   список).

### 5.4 Доступ в домене

На модели появляется узкий интерфейс, чтобы читатели не знали о схеме:

```python
reg.handles("battlenet")   -> tuple[str, ...]   # primary первым
reg.primary("battlenet")   -> str | None
reg.identities()           -> Mapping[str, tuple[str, ...]]
```

`reg.battle_tag` → `reg.primary("battlenet")`, `reg.smurf_tags_json` →
`reg.handles("battlenet")[1:]`, `reg.discord_nick` → `reg.primary("discord")`.

`shared/domain/roster.py:143-147` `PlayerRoster` теряет четыре поля и получает
`identities: Mapping[str, tuple[str, ...]]`; `RosterEngine.full_export`
(`shared/services/roster.py:492-496`) отдаёт тот же словарь.

---

## 6. Фронтенд

| Что | Действие |
|---|---|
| `lib/identity-providers.ts` | новый; реестр из сети + локальная карта иконок/цветов по `id` с фолбэком |
| `lib/oauth-providers.ts` | удалить |
| `lib/social-providers.ts` | оставить только иконки/цвета/порядок отображения |
| `lib/subscription-requirement.ts:27`, `subscription-shared.tsx:47`, `OAuthProviderBadge.tsx:7` | удалить таблицы, читать реестр |
| `registration/validation.ts:24,30,39,44,146` | удалить; regex и label приходят с сервера |
| `balancer/form/_components/formConfig.ts:30-33` | удалить дефолтные regex; identity-поля строятся из реестра |
| `registration/AccountStep.tsx:110-237` | `form.identity_fields.map(...)` → один компонент |
| `registration/SmurfTagsInput.tsx` | удалить, поглощён списком |
| `registration/AccountCombobox.tsx`, `VerifiedAccountSelect.tsx` | становятся внутренними режимами нового компонента |
| `UnifiedRegistrationForm.tsx:657-660,754-757` | четыре списка подсказок → один `Map<provider, string[]>` |

Новый компонент `<IdentityFieldList provider spec policy accounts value onChange />`:
рисует список хэндлов с пометкой главного, кнопкой «добавить» (до `max_count`) и
режимом ввода по `effective`.

---

## 7. Объём переписывания

| Область | Замер (graft) |
|---|---|
| `battle_tag` / `battle_tag_normalized` | 117 символов в 65 файлах; без тестов — ~25 мест: balancer roster/draft/export, `parser` rank collection, `sheet_sync`, `rank_autofill`, `rank_sources`, `team_actions`, `audit`, `workspace_player_backfill`, `profile_visibility`, admission |
| `discord_nick`/`twitch_nick`/`boosty_nick`/`smurf_tags` | 74 символа в 38 файлах |
| `built_in_fields_json` | ~30 символов |
| `custom_fields_json` | ~15 символов |
| Фронт | 8 файлов |

Отдельного внимания требуют:

- `shared/repository/stream.py:164` `list_self_declared_channels` — SQL по
  `registration.twitch_nick`, становится join на `registration_identity`;
- `parser-service/.../overwatch_rank/service.py:206` — `select(battle_tag, smurf_tags_json)`;
- `tournament-service/.../sheet_sync.py:572-649` — сопоставление строк таблицы по
  `battle_tag_normalized`;
- `tournament-service/.../mapping_catalog.py:140-165` — каталог целей импорта из
  Google-таблиц содержит ключи `smurf_tags`/`discord_nick`/`twitch_nick`/`boosty_nick`;
  **сохранённые маппинги организаторов ссылаются на эти ключи и требуют миграции**;
- `tournament-service/.../audit.py:41-56` — карта полей аудита.

---

## 8. Фазы

| # | Содержание | Схема | Отгружается |
|---|---|---|---|
| 0 | Реестр, деривация констант, канон BattleTag, `BATTLE_TAG_SCAN_RE` | — | **сделано** |
| 1 | `GET /identity/providers`, `lib/identity-providers.ts`, снос шести фронтовых таблиц и шести regex | — | да |
| 2a | `registration_identity` + бэкфилл + двойная запись | +1 таблица | да |
| 2b | Читатели → `handles()`/`primary()` | — | да |
| 2c | `identities[]` в контракте, `<IdentityFieldList>`, снос шести колонок и индекса | −6 колонок | да |
| 3 | `registration_form_field`, `_subrole`, `_custom_field`, `_custom_option`, `registration_custom_answer`; снос обоих JSON-конфигов и ответов | +5 таблиц, −3 колонки | да |

Двойная запись на 2a — осознанное временное исключение из правила «чистый
переход»: это expand-migrate-contract для живой базы, а не API-шим. Живёт до
2c и удаляется вместе с колонками.

**Откуда берётся `identity_fields` в чтении формы.** Контракт §5.2 появляется
на 2c, потому что визарду нужны `min_count`/`max_count`/`input_mode`. Таблицы
`registration_form_field` тогда ещё нет, поэтому на 2c сервер собирает
`identity_fields` из `built_in_fields_json` (`require_verified` → `input_mode`,
`smurf_tags.enabled` → `battlenet.max_count`). На фазе 3 меняется только
источник данных за тем же контрактом — фронт не трогается вовсе. Это
внутренняя проекция, не второй публичный контракт.

---

## 9. Риски и что замерить до старта

### 9.1 Канон BattleTag — снят

Замер на живой БД выполнить не удалось (`95.179.157.197:5432` недоступен с
рабочей станции), но риск оказался мнимым и без него: грамматика применяется к
**нормализованному** хэндлу, а нормализатор BattleTag и так удаляет все
пробелы. `[^#]{2,12}` и `[^#\s]{2,12}` на строке без пробелов — одна и та же
грамматика, так что `Player # 1234` принимался и принимается.

Реально канон только **мягче** прежнего серверного `[\w0-9]{2,12}`: ники с
точкой (`co.ol#1234`) и другие не-`\w` символы начнут проходить `app-service`.
Это исправление, не регрессия.

Осталось проверить на данных, когда база будет доступна, — не канон, а
**новые** грамматики Discord/Twitch/Boosty, которых на сервере раньше не было
вовсе:

```sql
SELECT count(*) FILTER (WHERE lower(discord_nick) !~ '^[a-z0-9_.]{2,32}(#[0-9]{4})?$') AS bad_discord,
       count(*) FILTER (WHERE lower(twitch_nick)  !~ '^[a-z0-9_]{4,25}$')              AS bad_twitch,
       count(*) FILTER (WHERE lower(boosty_nick)  !~ '^[^#[:space:]]{2,50}$')          AS bad_boosty
FROM balancer.registration
WHERE deleted_at IS NULL;
```

Эти поля валидируются сервером впервые: до фазы 0 бэк знал только тот regex,
который организатор случайно сохранил в конфиге формы. Существующие строки не
трогаются — проверка срабатывает лишь при следующей отправке или правке, — но
ненулевой результат означает, что кто-то не сможет пересохранить свою
регистрацию, пока грамматику не расширят.

### 9.2 Уникальность на турнир расширяется на всех провайдеров

Существующие данные почти наверняка содержат коллизии Discord/Twitch. Перед
2a — отчёт:

```sql
SELECT tournament_id, provider, handle_normalized, count(*)
FROM balancer.registration_identity
WHERE deleted_at IS NULL
GROUP BY 1,2,3 HAVING count(*) > 1;
```

Индекс создаётся `CONCURRENTLY` **после** разрешения коллизий: оставить раннюю
регистрацию, остальные пометить организатору. Миграция не должна падать.

### 9.3 Организаторский regex исполняется на сервере

Сегодня `_compile_fullmatch_pattern` (`validation.py:198`) компилирует паттерн
на каждом сабмите, а фронт при ошибке компиляции молча отключает валидацию
(`validation.ts:64` `catch { return null }`). Опечатка организатора = 500 на
сабмите. Компиляция при сохранении формы закрывает обе дыры. Длина паттерна
ограничивается (ReDoS, паттерн приходит от организатора).

### 9.4 Сохранённые маппинги Google-таблиц

`mapping_catalog.py` и сохранённые привязки колонок ссылаются на ключи
`smurf_tags`/`discord_nick`/`twitch_nick`/`boosty_nick`. Миграция 2c обязана
переписать их на `provider`-ключи, иначе синхронизация таблиц молча перестанет
заполнять поля.

---

## 10. Проверка

| Что доказываем | Как |
|---|---|
| Реестр — единственный источник regex | grep на удалённые константы даёт ноль |
| Валидация сходится на обеих сторонах | один и тот же набор пар (хэндл, провайдер) прогоняется через бэковый валидатор и через фронтовый в тесте |
| Список работает у всех провайдеров | регистрация с двумя Discord-аккаунтами при `max_count=2` проходит, с тремя — 422 |
| Уникальность в турнире | вторая регистрация с тем же Discord в том же турнире — 409, в другом турнире — проходит |
| Ровно один primary | попытка записать два `is_primary` для провайдера — нарушение индекса |
| `input_mode='oauth'` | хэндл без подтверждённого `social_account` — 422; с подтверждённым — проходит |
| Невозможная политика | сохранение формы с `input_mode='oauth'` для Boosty — 422 |
| Миграция данных | число строк `registration_identity` = число непустых хэндлов во всех шести колонках до миграции |
| Визард | реальный прогон регистрации в браузере: текстовый режим, OAuth-режим, добавление второго аккаунта |
