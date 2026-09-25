# Самозапись на микс через Discord + самостоятельная правка ролей

**Status:** draft

**Goal:** Игрок сам записывается на микс (кастомку) кнопкой в Discord или на доске микса и — если хост разрешил — сам
меняет порядок своих ролей и флекс. Доступно только аккаунтам, у которых привязаны **и** Discord, **и** Battle.net.
Сегодня в ростер микса пишут только хост и кохосты (`CustomGameService._writable`), самозаписи нет нигде.

**Architecture:** Две колонки на `balancer.custom_game` (режим записи, флаг правки ролей) + одна чистая политика
`mix_self_policy()` по образцу турнирного `self_edit_policy()` + четыре self-RPC в balancer-service, которые вызывают и
бот, и сайт. Мутация ролей — та же, что у хоста (`update_player`), отличается только гейт. Бот получает пять новых
действий и первый select-компонент; состояние по-прежнему живёт только в `custom_id` и БД.

**Tech Stack:** Alembic (`balancer`), balancer-service RPC, Go gateway routes, discord.py Components V2, Next.js
(`/balancer/mix/[gameId]`).

---

## Decision log

| Решение | Отклонено | Почему |
|---|---|---|
| Куда попадает записавшийся — настройка хоста (`pool` / `benched`) | Всегда пул; всегда скамейка | Выбор пользователя: одному хосту нужна открытая запись, другому — модерация |
| Одна колонка `self_signup` = `closed` \| `pool` \| `benched` | `bool open` + отдельный enum | Ровно три состояния; одна CHECK, нет невалидной пары «закрыто + скамейка» |
| Discord **и** доска микса | Только Discord | Выбор пользователя; те же RPC, а на сайте игрок сразу чинит привязки |
| Правка ролей разрешена, пока микс не `completed`/`cancelled` | Блок, пока игрок в показанном балансе; блок после первого баланса | Выбор пользователя; `balance_result_json` — снимок, правка действует со следующего баланса |
| Роль без ранга выбрать можно, с предупреждением | Только роли с рангом | Выбор пользователя; новичок без OW-снапшота иначе не выберет ничего |
| Игрок правит только `roles` и `is_flex` | Ранги, participation | Ранги — книга хоста (`MIX_ORDER`), participation — решение хоста |
| Новой таблицы нет: записавшийся = обычная `custom_game_player` | Отдельная «заявка на микс» | Хосту не нужен второй список; realtime и доска уже работают с ростером |
| Capability `custom_game.self_join` (allow-by-default) | Без неё | Админ отрезает конкретного игрока deny-строкой, не закрывая запись всем — как `registration.self_register` |
| Карточка в канале статична | Живой счётчик записавшихся | Бот канальные посты не редактирует by design; нужен `edit_message` + хранение `message_id` |
| Аудита нет | `record_audit` на self-действия | Хостовые действия миксов тоже не аудируются; realtime-доска показывает изменения |

## Что уже есть

- `CustomGamePlayer` (`backend/shared/models/custom_game.py:82`): `workspace_member_id` (unique с `custom_game_id`),
  `participation`, `role_selection_mode` (`all_ranked`/`explicit`), `is_flex`; `CustomGamePlayerRole` — `(role, priority)`.
- `CustomGameService.update_player` (`backend/balancer-service/src/services/custom_game.py:564`): `roles=None` →
  `ALL_RANKED`, список → `EXPLICIT` в порядке приоритета; `is_flex` — без штрафа за офф-роль (`isFullFlex`).
- `update_roster` удаляет строку, когда хост убирает игрока (`custom_game.py:551-553`); история матчей на
  `custom_game_player` не ссылается.
- `_seed_host_ranks` копирует найденный ранг в книгу хоста при добавлении.
- `emit_pickup_mix_updated` (`src/services/pickup_mix_realtime.py`) — единый realtime-сигнал доски.
- Доска `/balancer/mix/[gameId]` публичная (`frontend/src/config/auth.ts:7`).
- `workspace_discord_channel_id` — единственный канал, куда пишет микс (`custom_game.py:901`); `custom.post_discord`
  публикует `DiscordCommandEvent(action="post_message")`.
- Турнирная самозапись (`tournament-service/src/services/registration/service.py:550-602`): capability → player →
  `get_or_create_workspace_member` → `assign_workspace_system_role("player")`.
- Бот: `owt:<action>:<target>` → `rpc.identity.discord_identity` → RPC действия (`interactions/dispatcher.py`);
  ответ на эфемерном сообщении заменяет его на месте (`dispatcher.py:178-182`); исход `not_linked` уже рисует кнопку
  `/?settings=profile`.
- Проверки «Discord **и** Battle.net» нет; `discord_identity` доказывает только Discord.

---

## Data model

Миграция `mixself01` (schema `balancer`):

```python
# custom_game
self_signup: Mapped[str] = mapped_column(String(16), nullable=False, default="closed", server_default="closed")
self_role_edit: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
# CheckConstraint("self_signup IN ('closed','pool','benched')", name="ck_custom_game_self_signup")
```

Enum `MixSelfSignup` (`closed`/`pool`/`benched`) рядом с `MixParticipation` в `backend/shared/core/enums.py`.

Клон (`CustomGameCreate.clone_from_game_id`) копирует `self_role_edit`; `self_signup` не копирует — новая сессия
стартует с закрытой записью.

Деплой — no-op: у всех существующих миксов запись закрыта, правка ролей выключена.

## Admission: `mix_self_policy`

`backend/balancer-service/src/domain/mix_self_service.py` — чистая функция, без `await`:

```python
@dataclass(frozen=True, slots=True)
class MixSelfPolicy:
    can_join: bool
    can_leave: bool
    can_edit_roles: bool
    join_blocker: str | None   # None, когда can_join
    edit_blocker: str | None   # None, когда can_edit_roles

def mix_self_policy(
    *,
    status: str,
    self_signup: str,
    self_role_edit: bool,
    on_roster: bool,
    missing_links: frozenset[str],   # подмножество {"discord", "battlenet"}
    has_player: bool,
    self_join_denied: bool,
    roster_size: int,
) -> MixSelfPolicy: ...
```

Порядок проверок фиксирован; первый провал — причина:

| # | Код | Условие | Режет |
|---|---|---|---|
| 1 | `mix_closed` | `status in {completed, cancelled}` | всё |
| 2 | `discord_not_linked` | `"discord" in missing_links` | join, edit |
| 3 | `battlenet_not_linked` | `"battlenet" in missing_links` | join, edit |
| 4 | `player_not_linked` | нет `players.user` с `auth_user_id` аккаунта | join, edit |
| 5 | `self_join_denied` | deny на `custom_game.self_join` в workspace микса | join, edit |
| 6 | `already_joined` / `not_on_roster` | `on_roster` / `not on_roster` | join / edit |
| 7 | `signup_closed` | `self_signup == "closed"` | join |
| 8 | `roster_full` | `roster_size >= 100` (тот же потолок, что `CustomGameRosterUpdate.member_ids`) | join |
| 9 | `role_edit_off` | `not self_role_edit` | edit |

`can_leave = on_roster and status not terminal` — выписаться можно всегда, даже без привязок.

Привязки: новый хелпер `missing_account_links(session, auth_user_id) -> frozenset[str]` в
`backend/shared/services/account_links.py` поверх `OAuthConnectionRepository.list_by_user_providers(providers=[
SocialProvider.DISCORD, SocialProvider.BATTLENET])`. Чтение `auth` через shared разрешено (`backend/ARCHITECTURE.md:293`).

Player: `UserRepository.get_by_auth_user_id` (`backend/shared/repository/identity.py:35`). Без player — `player_not_linked`;
обычная OAuth-привязка Battle.net привязывает и player (`oauth_accounts._attach_verified_social_account`), так что это
редкий случай, а не основной путь.

Capability: `_permission("custom_game", "self_join", "Self-join a pickup mix")` в `backend/shared/rbac/catalog.py`
рядом с `registration.self_register`; проверка — `auth_user.can_capability("custom_game", "self_join", workspace_id=…)`.

## RPC и маршруты

Новые subjects в `backend/balancer-service/src/rpc/custom.py`; гейт — политика, **не** `_require_mix` (записывающийся
может ещё не быть членом workspace). Бот не знает workspace: self-RPC принимают `custom_game_id`, workspace берут из строки
микса; если `workspace_id` пришёл (сайт) — он обязан совпасть, иначе 404.

| Subject | Маршрут (`/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}…`) | Auth |
|---|---|---|
| `custom.self_get` | `GET …/me` | required |
| `custom.self_join` | `POST …/me` | required |
| `custom.self_leave` | `DELETE …/me` | required |
| `custom.self_update` | `PATCH …/me` body `{roles?: RoleCode[] \| null, is_flex?: bool}` | required |
| `custom.set_self_service` | `PUT …/self-service` body `{self_signup?, self_role_edit?}` | required, `_writable` |
| `custom.post_signup` | `POST …/discord/signup` body `{self_signup: "pool" \| "benched"}` | required, `_writable` |

Ответ всех `self_*`:

```json
{
  "custom_game_id": 42,
  "name": "Пятничный микс",
  "status": "balanced",
  "self_signup": "pool",
  "self_role_edit": true,
  "seat": {"participation": "pool", "roles": ["tank", "support"], "is_flex": false,
           "ranks": {"tank": 3100, "support": null}},
  "unranked_roles": ["support"],
  "policy": {"can_join": false, "can_leave": true, "can_edit_roles": true,
             "join_blocker": "already_joined", "edit_blocker": null}
}
```

`seat = null`, когда игрока нет в ростере. `roles = null` означает `all_ranked`. `unranked_roles` — роли, по которым
`MemberRankService.resolve` (`MIX_ORDER`) ничего не нашёл: выбранные в `explicit` или все три в `all_ranked`.

Ошибки — обычный конверт `c.envelope`: 403 с `detail=<код>` для кодов 2-5, 409 для `mix_closed`/`signup_closed`/
`roster_full`/`role_edit_off`, 404 для `not_on_roster`. `already_joined` — **не** ошибка: `self_join` идемпотентен и
возвращает текущее состояние.

`custom.get` / `custom.list` дополняют `_dump_game` полями `self_signup`, `self_role_edit`.

Описания всех новых subjects — в `gateway/internal/openapi/schemas.json`, маршруты — в
`gateway/internal/balancer/routes.go` рядом с `custom.update_player`.

## Service logic

`CustomGameService` (`backend/balancer-service/src/services/custom_game.py`):

- **`_apply_player_patch(session, row, patch, allowed)`** — вынести из `update_player` текущую мутацию
  (`participation`/`roles`/`is_flex`). Хост вызывает с `_PLAYER_PATCH_FIELDS`, игрок — с `{"roles", "is_flex"}`;
  лишнее поле → 422 как сейчас.
- **`self_state(session, custom_game_id, auth_user)`** — собирает входы политики и ответ выше.
- **`self_join`**:
  1. политика → блокер = ошибка;
  2. `get_or_create_workspace_member(workspace_id, player_id)` + `assign_workspace_system_role(role_name="player")` —
     идемпотентно, как турнирная самозапись;
  3. `_new_roster_row(game.id, member_id, sort_order=len(roster))`, `participation = MixParticipation(game.self_signup)`,
     `role_selection_mode = ALL_RANKED`;
  4. `_seed_host_ranks` для новой строки;
  5. `emit_pickup_mix_updated(change="roster", actor_user_id=…)`.
  Строка уже есть → ничего не меняем (забенченный хостом не возвращается в пул). Гонка двух кликов упирается в unique
  `(custom_game_id, workspace_member_id)` → IntegrityError → отвечаем текущим состоянием.
- **`self_leave`** — `roster.delete(row)` (как `update_roster`), `emit_pickup_mix_updated(change="roster")`.
- **`self_update`** — политика `can_edit_roles` → `_apply_player_patch(..., allowed={"roles", "is_flex"})` →
  `emit_pickup_mix_updated(change="roster")`. Показанный баланс не трогаем.
- **`set_self_service`** — `_writable` → запись колонок → `emit_pickup_mix_updated(change="member")`.
- **`post_signup`** — `_writable` → `self_signup = body.self_signup` → канал `workspace_discord_channel_id` (нет —
  409, как `post_discord`) → `DiscordCommandEvent(action="post_message", card=signup_card(...))` в
  `DISCORD_COMMANDS_QUEUE` → `emit_pickup_mix_updated(change="member")`.

Карточка строится чистой функцией `signup_card(game, host_name, board_url)` в
`backend/balancer-service/src/domain/mix_discord.py`. `board_url` = `PUBLIC_SITE_URL` + `/balancer/mix/{id}`: в
config balancer-service добавить `public_site_url` (как у app-service и discord-service) и прокинуть env в
`docker-compose*.yml`.

## Discord

### Карточка записи (канал микса)

`DiscordCard`, текст на ru (канальный пост общий, как `_DM_LOCALE` у app-service):

> **Запись на микс «{name}»** · хост {host}
> Нужны привязанные к аккаунту Discord и Battle.net.

Кнопки: **Записаться** (`mix.join`, success) · **Мои роли** (`mix.roles`) · **Выписаться** (`mix.leave`, danger) ·
ссылка **Доска микса**. `target` = `custom_game_id`. «Мои роли» есть всегда: при выключенной правке ответ показывает
роли только для чтения.

### Действия

`DiscordAction` (`backend/shared/schemas/events.py:32`) и `ACTIONS` (`interactions/actions.py`) — один список дважды,
равенство держит `tests/test_interactions.py`:

| Действие | RPC | Откуда |
|---|---|---|
| `mix.join` | `rpc.balancer.custom.self_join` | карточка |
| `mix.leave` | `rpc.balancer.custom.self_leave` | карточка, эфемерный ответ |
| `mix.roles` | `rpc.balancer.custom.self_get` | карточка, эфемерный ответ |
| `mix.roles_set` | `rpc.balancer.custom.self_update` `{roles}` | select в эфемерном ответе |
| `mix.flex` | `rpc.balancer.custom.self_update` `{is_flex}` | кнопка в эфемерном ответе |

`mix.flex` несёт желаемое значение в target: `42-on` / `42-off` (влезает в `[A-Za-z0-9_-]{1,40}`).

### Эфемерный ответ

Рендер `copy.mix_text(locale, state)` (по образцу `registration_text`):

- «Вы в пуле «{name}»» / «Вы на скамейке — хост переведёт в пул»;
- «Роли: Танк → Сапорт» или «Роли: все, по которым есть ранг»; «Флекс: вкл»;
- предупреждение при `unranked_roles`: «Нет ранга: Сапорт — хост проставит»;
- если `can_edit_roles`: select ролей + кнопка «Флекс: вкл/выкл»;
- кнопка «Выписаться»; при `can_join` — «Записаться»;
- блокеры → текст по коду; `discord_not_linked`/`battlenet_not_linked`/`player_not_linked` → link-кнопка
  `/?settings=profile` (как существующий исход `not_linked`).

Кнопки и select на эфемерном сообщении заменяют его на месте — это уже делает `dispatcher.handle` для эфемерных
сообщений.

### Select ролей

Один string select, `custom_id = owt:mix.roles_set:42`. Discord не сохраняет порядок кликов, поэтому порядок зашит в
значение: все упорядоченные непустые наборы из `tank`/`damage`/`support` (3 + 6 + 6 = 15) плюс `all` («Все роли с
рангом» → `roles=null`) — 16 опций при лимите 25. Значение — `tank,support`; текущий выбор помечен `default`.
В подписи опции — ранг из книги хоста или «без ранга».

### Изменения бота

- `Action.request(target, values)` — `values` из `interaction.data["values"]` (пусто для кнопок); `mix.roles_set` берёт
  `values[0]`, разбирает и валидирует по `REGISTRATION_ROLE_CODES`.
- `InteractionsCog.on_interaction` уже фильтрует `InteractionType.component` — пропускает и select; передать `values`.
- `cards.py`: билдер `discord.ui.Select` в `ActionRow`, собирается и сразу `.stop()` (`_detached`), как кнопки.
  В схему `DiscordCard` select не попадает — его строит только бот.
- `dispatcher.reply`: для `mix.*` — `copy.mix_text` вместо `success_text`.
- `copy.py`: ru/en ключи для текста, опций select, всех кодов блокеров.

## Frontend

`frontend/src/app/balancer/mix/[gameId]/`:

- **Хост** (`PickupMixHeader.tsx`): контрол «Запись: закрыта / в пул / на скамейку», свитч «Игроки меняют роли»
  (`set_self_service`), кнопка «Открыть запись в Discord» (`post_signup`; выключена без mix-канала — та же подсказка,
  что у «Отправить в Discord»).
- **Игрок** — новая панель `PickupMySeatPanel.tsx`, видна вошедшему, когда `self_signup != closed` или он уже в ростере:
  записаться / выписаться / роли. Данные — `GET …/me` (`customGameKeys.me(gameId)`), инвалидация тем же
  `pickup_mix.updated`, что и доска.
- Порядок ролей: вынести drag-список ролей и флекс из `PickupPlayerSheet.tsx` (`SortableRoleCard`/`RoleCardBody`) в
  `PickupRoleOrderEditor.tsx`; редактирование рангов остаётся в листе хоста, у игрока ранги только для чтения.
- Блокеры привязок → ссылка `/?settings=profile` (как `RegistrationSchemaForm.tsx:374`).
- `custom-game.service.ts`: `getMySeat`, `joinMix`, `leaveMix`, `updateMySeat`, `setSelfService`, `postSignup`;
  типы `MixSelfState`, `MixSelfPolicy`.
- i18n ru/en в сообщениях зоны balancer (держит `messages.parity.test.ts`).

---

## Edge cases

- **Повторный «Записаться»** — ответ «вы уже в пуле/на скамейке», строка не меняется.
- **Хост убрал игрока** — при открытой записи игрок может записаться снова. Постоянный запрет — deny на
  `custom_game.self_join`.
- **Хост/кохост записывается как игрок** — обычная самозапись; права хоста не меняются.
- **Правка ролей после баланса** — `balance_result_json` не пересчитывается; хост видит новые роли в лобби и
  перебалансирует.
- **Выписка игрока, сидящего в показанном балансе** — как удаление хостом: строка уходит, снимок баланса живёт до
  перебаланса.
- **Микс закрыт/отменён** — кнопки старой карточки отвечают `mix_closed`.
- **Запись закрыта хостом** — карточка остаётся, кнопка отвечает `signup_closed`; решает колонка, а не карточка.
- **Отвязал Battle.net, уже в ростере** — остаётся; записаться заново и править роли не может, выписаться может.
- **Бюджет 3 секунды** — `defer()` первым действием уже есть; self-RPC — один запрос к balancer (привязки читаются
  внутри), итого два RPC на клик, как сейчас.

## Phases

1. **Backend.** Миграция `mixself01`, `MixSelfSignup`, capability, `account_links.py`, `mix_self_service.py`,
   `_apply_player_patch` + self-методы сервиса, шесть subjects, `signup_card`, `public_site_url`, gateway routes, openapi.
2. **Бот.** `DiscordAction`/`ACTIONS` +5, `values` в `Action.request`, select-билдер, `copy.mix_text` + ключи.
3. **Frontend.** Контролы хоста, `PickupMySeatPanel`, `PickupRoleOrderEditor`, сервис, i18n.
4. **Docs.** `frontend/src/app/(site)/docs/_content/{ru,en}/players/` — раздел «Запись на микс»; таблица действий в
  `backend/discord-service/README.md`; §Mix в `docs/business-logic-inventory.md`; колонки в `docs/database_erd.md`.

## Verification

- `tests/test_mix_self_service.py` (balancer): табличный тест `mix_self_policy` — каждый код из таблицы порядка,
  приоритет кодов (закрытый микс без привязок → `mix_closed`), `can_leave` без привязок.
- `test_custom_game.py`: `self_join` идемпотентен; `benched`-режим сажает на скамейку; забенченный хостом не
  возвращается в пул; 403 `battlenet_not_linked`; 409 `signup_closed`/`mix_closed`/`roster_full`; `self_update`
  отклоняет `participation` (422) и работает только при `self_role_edit`; `self_leave` без привязок проходит.
- `tests/test_interactions.py` (бот): равенство `ACTIONS`/`DiscordAction`; значение select доходит до RPC как
  `roles=["tank","support"]`, `all` → `roles=None`; мусорное значение → 422 до RPC.
- Frontend: behavior-тест `PickupMySeatPanel` (блокер привязки рисует ссылку; `can_edit_roles=false` — редактор
  выключен).
- Смоук: локальный стек + тестовый guild → хост открывает запись → клик «Записаться» с аккаунта без Battle.net
  (ссылка на профиль) и с полным (строка на доске в реальном времени) → смена ролей select'ом → роли в листе хоста.

## Out of scope

Ранги от игрока; сабролли (у миксов их нет); лимит мест и лист ожидания; живой счётчик на карточке (`edit_message`);
DM хосту о новых записях; внеочередной `FetchRankEvent` при записи; проверка членства в Discord-гильдии для записи с
сайта.
