# Самозапись на микс через Discord — Implementation Plan
**Status:** design approved

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Игрок с привязанными Discord и Battle.net сам записывается на микс (кнопкой в Discord или на доске) и, если хост разрешил, сам меняет порядок своих ролей и флекс.

**Architecture:** Две колонки на `balancer.custom_game` (`self_signup` = `closed`|`pool`|`benched`, `self_role_edit`), одна чистая политика `mix_self_policy()`, self-методы `CustomGameService` поверх вынесенного `_apply_player_patch`, шесть RPC в balancer-service. Бот получает пять `mix.*`-действий и первый select, состояние по-прежнему только в `custom_id` и БД. Фронт: контролы хоста в шапке микса и панель «Ваше место» на публичной доске.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic (hand-written), FastStream RPC, pytest через `uv`; Go gateway; discord.py 2.6 Components V2; Next.js, TanStack Query, next-intl, `@dnd-kit`, vitest + bun:test.

**Spec:** [`design.md`](./design.md) — прочитать первым; каждая задача опирается на него.

## Global Constraints

- Маршрутизация по коду из `.claude/CLAUDE.md`: graft/CodeGraph первыми, `grep/glob/read` — запасной путь.
- Номера строк в задачах — по дереву на момент написания плана; при расхождении ищите по символу.
- Backend-тесты — по пакету, из `backend/`: `uv run pytest <service>/tests/<file>.py -q` (`shared/tests`, `balancer-service/tests`, `discord-service/tests`). Lint: `uv run bash scripts/lint.sh`.
- Gateway: `cd gateway && go test ./internal/balancer/...`.
- Frontend: одиночный vitest-файл — `bunx vitest run <path>`, bun:test-файл — `bun test <path>` (какой раннер у файла — `bun run test:split`). Финальные гейты: `bun run typecheck && bun run lint && bun run lint:zones && bun run test:split && bun run test:vitest && bun run test:bun`. Никогда `next build` для проверки.
- Новые колонки ⇒ `cd backend && uv run python scripts/export_erd.py`; изменённые Pydantic-модели провода ⇒ `bash scripts/export_openapi_schemas.sh`; новый маршрут ⇒ `uv run python scripts/check_rpc_docs.py`. CI падает, если что-то устарело.
- Миграция `mixself01`, `down_revision = "varcap01"` (текущая единственная голова). Hand-written, как соседние ревизии.
- Деплой — no-op: `self_signup` по умолчанию `closed`, `self_role_edit` — `false`.
- Коды блокеров и статусы — ровно: 403 `discord_not_linked`/`battlenet_not_linked`/`player_not_linked`/`self_join_denied`; 409 `mix_closed`/`signup_closed`/`roster_full`/`role_edit_off`; 404 `not_on_roster`; `already_joined` — не ошибка. `HTTPException(detail=<код>)` голой строкой (бот читает код из `message`, см. Deviations A6).
- `MAX_ROSTER = 100` — тот же потолок, что `CustomGameRosterUpdate.member_ids`.
- Игрок пишет только `roles` и `is_flex`; ранги — книга хоста, `participation` — решение хоста. Аудита self-действий нет.
- Бот: два RPC на клик (identity → действие), `defer()` первым, никаких stateful View; все новые строки — ru и en.
- Clean cutover: без шимов и алиасов; каждый вызывающий мигрирует в задаче, которая меняет его контракт.
- Коммит после каждой задачи, conventional commits (`feat(balancer): …`, `feat(discord): …`, `feat(mix): …`, `docs(mix): …`).

## Порядок выполнения

```
A1 → A2, A3 → A4 → A5 → A6a → A6b → A6c → A7 → A8 → A9 → A10 → A11
```

- A2 и A3 независимы друг от друга, обе нужны A4.
- A7 (карточка записи) — после A6b: `DiscordActionButton` отвергает `mix.*`, пока их нет в `DiscordAction`.
- Фронт (A8+) опирается на провод A5/A7.
- Финальные backend-гейты (один раз, после A7): `cd backend && bash scripts/export_openapi_schemas.sh --check && uv run python scripts/check_rpc_docs.py && uv run python scripts/export_erd.py --check`.

---

## Deviations from spec и проверенные факты

Собраны по частям; каждая — результат сверки спеки с кодом.

### Backend (A1–A5, A7)

Источник: `docs/mix-self-signup-discord/design.md`.
Не входит: discord-service (A6), frontend.

---

#### Deviations from spec

1. **`seat.ranks` — полный словарь из трёх ролей.** В примере спеки (строки 151-153) показаны только выбранные роли.
   Пишем все `REGISTRATION_ROLE_CODES` (`tank`/`damage`/`support`), значение `null` — ранга нет. Согласовано с
   A6: боту нужны ранги для подписей всех 16 опций select'а. `unranked_roles` остаётся узким списком
   (выбранные роли без ранга, либо все три в `all_ranked`).
2. **`signup_card` принимает keyword-аргументы, а не ORM-строку.** Спека пишет `signup_card(game, host_name, board_url)`;
   пишем `signup_card(*, mix_name, host_name, board_url, custom_game_id)` — иначе «чистая функция» тянет модель
   (`build_lineup_embed` в том же модуле ровно так и устроен: `backend/balancer-service/src/domain/mix_discord.py:96-105`).
3. **`emit_pickup_mix_updated` для self-методов зовётся в сервисе, для хостовых (`set_self_service`, `post_signup`) — в RPC.**
   У self-RPC нет `workspace_id` (бот его не знает), а в ответ он не входит по контракту, поэтому сигнал шлёт сервис.
   Хостовые пути остаются как все соседние writes в `src/rpc/custom.py` (`custom.update_player`, `custom.set_team_names`, …).
4. **`MixSelfSignup` не добавляется в `shared/core/enums.__all__`.** Соседние `MixStatus`, `MixParticipation`,
   `MixRoleSelectionMode` там тоже отсутствуют (`backend/shared/core/enums.py:616-666`) — список неполный by design.
5. **`dev docker-compose.yml` править не нужно.** `balancer-svc` уже подключает `./backend/env/common.env`
   (`docker-compose.yml:235-237`), где `PUBLIC_SITE_URL` задан (`backend/env/common.env.example:18`). Явная строка
   нужна только в `docker-compose.production.yml`, как у `app-svc` (`docker-compose.production.yml:326-328`).
6. **`custom_game.self_join` попадает в роль `host`.** `_host_permission_names()` берёт *все* permission'ы с
   `resource == "custom_game"` (`backend/shared/rbac/catalog.py:160`). Это безвредно и совпадает с прецедентом:
   `_admin_permission_names()` уже раздаёт `registration.self_register` и `account.*`. Существующий
   `shared/tests/test_rbac_catalog_host_role.py` проверяет включения, а не точное множество — правки не требует.
7. **Строки в спеке немного разъехались с кодом** (сам код на месте): `update_player` — `custom_game.py:566`
   (в спеке 564), удаление строки ростера — `custom_game.py:546-548` (в спеке 551-553),
   `workspace_discord_channel_id` — `custom_game.py:896` (в спеке 901). `CustomGamePlayer` (`models/custom_game.py:82`)
   и турнирная самозапись (`registration/service.py:550-602`) совпадают.
8. **Фикстура `test_custom_public_reads.py:83-92` ломается от новых полей дампа** (`SimpleNamespace` без
   `self_signup`/`self_role_edit`) — чинится в A1.

### Discord-бот (A6)

Секция `## Discord` спеки `docs/mix-self-signup-discord/design.md` (строки 202-260).
Область: `backend/discord-service` (`src/interactions/{actions,cards,dispatcher,copy}.py`,
`src/cogs/interactions.py`, `tests/test_interactions.py`), `backend/shared/schemas/events.py`
(`DiscordAction`), `backend/discord-service/README.md`.
Не входит: RPC balancer-service и `signup_card` (backend-задачи A1–A5, A7), фронт (A8–A11).

---

#### Deviations from spec

1. **Блокер приходит в `message`, а не в `code`.** Спека (строки 162-164) пишет «403 с `detail=<код>`».
   Backend-часть (A4/A5) фиксирует: `raise HTTPException(status_code=403, detail="battlenet_not_linked")` —
   голая строка. `shared/rpc/common.py:234-258` (`http_error`) кладёт `details["fields"]` **только**
   для `detail` типа `list`/`dict`; для строки `details` пуст, и `envelope`
   (`shared/rpc/common.py:298-300`) отдаёт `rpc_error(status_to_code(403), "battlenet_not_linked")`.
   Значит `dispatcher._refusal_code` (`dispatcher.py:55-63`) вернёт `"forbidden"`, а код блокера
   выживет только в `Outcome.message`. План вводит `_mix_blocker(outcome)`, который проверяет
   **и** `outcome.code`, **и** `outcome.message` против известного множества кодов — так бот
   переживёт и переход бэка на `detail={"code": ...}`. `_refusal_code` не трогаем: он общий с
   турнирными действиями, где `details["fields"]` реально есть.

2. **`seat.ranks` — всегда три ключа.** В примере спеки (строка 152) показаны только выбранные роли.
   Backend-часть (A4/A5) фиксирует: дамп отдаёт все `REGISTRATION_ROLE_CODES`, значение `int | null`.
   Боту это нужно: подпись каждой из 16 опций селекта называет ранги, включая невыбранные роли.

3. **Ранги — в `description` опции, не в `label`.** `discord.SelectOption` даёт две строки подписи.
   `label` = «Танк → Саппорт», `description` = «Танк 3100 · Саппорт без ранга». Спека говорит «в
   подписи опции — ранг или „без ранга“» (строка 250), не уточняя поле; разделение держит список
   читаемым и оставляет запас по лимиту в 100 символов.

4. **Валидация значения селекта происходит до RPC identity, а не внутри `request`-вызова.**
   Спека (строка 255) говорит «`mix.roles_set` берёт `values[0]`, разбирает и валидирует», задание —
   «invalid → отказ бота без RPC». Сегодня `action.request(target)` вызывается на строке
   `dispatcher.py:107`, то есть **после** `rpc.identity.discord_identity`. План переносит построение
   тела в начало `perform`, до обращения к брокеру: мусорное значение не стоит ни одного RPC.

5. **`participation` бывает трёх значений.** `MixParticipation` (`shared/core/enums.py:311-314`) —
   `must_play` / `pool` / `benched`. Спека в тексте ответа называет только пул и скамейку; хост
   может перевести записавшегося в `must_play`, поэтому `copy.mix_text` словит и его.

6. **Таблицы действий в README ещё нет.** Спека (строка 304) говорит «таблица действий в
   `backend/discord-service/README.md`». Сегодня там проза (`README.md:88-111`), перечисляющая
   действия одной скобкой на строке 97-98. A6c эту таблицу заводит и правит прозу.

---

#### Что проверено в коде

| Факт | Где |
|---|---|
| `Action(subject, request, accepts, settles)`, `request: Callable[[str], dict]` | `src/interactions/actions.py:50-66` |
| `ACTIONS` — 6 записей, `_invite`/`_tournament`/`_nothing`/`_everything` | `actions.py:31-47`, `74-89` |
| `_CUSTOM_ID` = `^owt:(?P<action>[a-z_.]+):(?P<target>[A-Za-z0-9_-]{1,40})$` — `42-on` и `mix.roles_set` подходят | `actions.py:28` |
| `parse_custom_id` зовёт `action.accepts(target)`; `values` ему недоступны | `actions.py:101-109` |
| `card_view(card)`, `_detached` (`view.stop()`), `settle` | `src/interactions/cards.py:40-64`, `67-86` |
| `perform(discord_user_id, action_name, target)`; тело RPC — `{"identity": …, **action.request(target)}` | `src/interactions/dispatcher.py:78-119` |
| `reply(outcome, action_name, locale)`; ветки ok/not_linked/inactive/unavailable/failed | `dispatcher.py:121-147` |
| `_card(color, text, *buttons)` | `dispatcher.py:154-156` |
| `handle(interaction, action_name, target)`; эфемерное сообщение заменяется на месте | `dispatcher.py:158-186` |
| `_refusal_code`: `details["fields"][0]["code"]`, иначе `error["code"]` | `dispatcher.py:55-63` |
| `Status`, `Outcome(status, data, code, message)` | `dispatcher.py:44-52` |
| `InteractionsCog.on_interaction` читает `interaction.data["custom_id"]` | `src/cogs/interactions.py:28-46` |
| `copy.Locale`, `_TEXT`, `_ROLES` (`tank/damage/support/flex`), `_role`, `text`, `error_text` | `src/interactions/copy.py:16-22`, `139-143`, `175-193` |
| `DiscordAction` Literal, `DiscordActionButton.target` pattern `^[A-Za-z0-9_-]{1,40}$` | `backend/shared/schemas/events.py:32-39`, `63` |
| `REGISTRATION_ROLE_CODES == ("tank", "damage", "support")` | `shared/domain/player_sub_roles.py:15-16` (проверено запуском) |
| `status_to_code`: 403→`forbidden`, 404→`not_found`, 409→`conflict` | `shared/schemas/rpc.py:102-115` |
| `_TRANSIENT = {"unavailable", "internal", "rate_limited"}` — `conflict`/`forbidden`/`not_found` дают `failed` | `dispatcher.py:42`, `117` |
| Тесты: `_Rpc`, `_dispatcher()`, `_interaction()`, `_reply_text()`, `IsolatedAsyncioTestCase` | `tests/test_interactions.py:34-86` |
| `set(ACTIONS) == set(get_args(DiscordAction))` | `tests/test_interactions.py:130-131` |
| discord.py 2.6.4: `ActionRow(Select(...))` внутри `LayoutView` рендерится как `{"type": 1, "components": [{"type": 3, "custom_id": …, "options": […]}]}` | проверено запуском на `backend/.venv` |

### Frontend и доки (A8–A11)

Спека: `docs/mix-self-signup-discord/design.md`, разделы **Frontend**, **Phases 3–4**, **Verification**.
Зона ответственности: `frontend/src/services/custom-game.service.ts`, `frontend/src/app/balancer/mix/**`,
i18n `frontend/src/i18n/messages/{ru,en}.json`, пользовательские доки `players/mixes.mdx`,
`docs/business-logic-inventory.md`.

Не моё: бэкенд (A1–A5, A7), бот и `backend/discord-service/README.md` (A6),
`docs/database_erd.md` (регенерируется в A1 командой `uv run python scripts/export_erd.py` — здесь только упоминание).

---

#### Deviations from spec

Проверено по коду; расхождения со спекой и с формулировкой задания:

1. **«Та же подсказка, что у „Отправить в Discord“»** — подсказки нет. Существующая кнопка поста
   (`PickupTeamsPanel.tsx:364-392`) при отсутствии `game.settings.workspace_discord_channel_id` **не рендерится
   вовсе** (`{canWrite && onPostToDiscord && game?.settings.workspace_discord_channel_id ? … : null}`), её
   `title` — просто `"Post to Discord"`. Кнопка «Открыть запись в Discord» по заданию должна быть **disabled**,
   поэтому подсказка вводится новая: `title={t("noChannel")}`, ключ `mixes.self.noChannel`. Существующую кнопку
   поста не трогаем.
2. **i18n у доски микса неоднороден.** `PickupMixList`/`PickupCreateMixDialog`/`PickupLeaderboard` ходят в
   `useTranslations("mixes.*")`, а панели доски (`PickupMixHeader`, `PickupLobbyPanel`, `PickupTeamsPanel`,
   `PickupPlayerSheet`) — захардкоженный английский. Спека требует ru/en, поэтому **только новые** строки
   (контролы самозаписи + панель игрока) идут через `useTranslations("mixes.self")`; существующие строки
   заголовка (`Add players`, `Manage access`) остаются как есть — это не наша задача.
3. **Зона i18n.** Спека говорит «сообщения зоны balancer». Такой зоны нет: `/balancer` рендерится в зоне
   **`tools`** (`frontend/src/app/balancer/layout.tsx:12`), и неймспейс `mixes` уже в её списке
   (`frontend/src/i18n/zone-namespaces.json:133`). Правок `zone-namespaces.json` не требуется.
4. **`messages.parity.test.ts` ключи по интерполяции не видит.** Коды блокеров и режимы записи читаются как
   `t(\`blocker.${code}\`)` / `t(\`signup.${mode}\`)`, поэтому добавляются в уже существующий блок
   `describe("interpolated message keys")` (`frontend/src/i18n/messages.parity.test.ts:31-47`) — списком-контрактом,
   ровно как там сделано для `formations`. Импортировать список из `src/app/**` **нельзя**: правило Z2
   (`frontend/scripts/check-zone-boundaries.mjs:13`) запрещает импорт из `src/app` за его пределами.
5. **`usePickupMix.behavior.test.tsx` мокает весь модуль сервиса** (`:30-50`) частичными `customGameKeys` и
   `customGameService`. Новый `useQuery` по `customGameKeys.me(...)` уронит существующие тесты, пока мок не
   дополнен — правка мока входит в A10 обязательным шагом, а не «попутно».
6. **Блокеры привязок ведут через `useAccountSettingsModalStore`**, как в `RegistrationSchemaForm.tsx:376`
   (`openAccountSettings("profile")`). Модалка смонтирована в корневом layout (`frontend/src/app/layout.tsx:113`),
   то есть работает и в зоне `tools`. Вариант `<Link href="/?settings=profile">` (как в
   `DiscordSection.tsx:419`) не выбран: он перезагружает страницу микса.
7. **Тесты фронта не типизируются**: `frontend/tsconfig.json:48-49` исключает `**/*.test.ts(x)`. Поэтому
   существующая фикстура `game()` в `PickupMixHeader.behavior.test.tsx:31-48` легально не содержит `settings`
   и `roster_shape`; новые поля добавляем только те, что нужны тесту.
8. **Пакетный менеджер — bun** (`frontend/bun.lock`), CI зовёт `bun run test:vitest` / `bun run test:bun`
   (`.github/workflows/ci-frontend.yml:69-71`). Одиночный vitest-файл — `bunx vitest run <path>`.
   Файлы `src/app/balancer/mix/**/*.test.ts(x)` уже в allow-list vitest (`vitest.config.ts:92-93`), новые
   записи туда не нужны. `src/i18n/messages.parity.test.ts` — **bun:test** (`:1`).
9. **Панели доски — презентационные**, данные и мутации держит страница/`usePickupMix` (см. `PickupPlayerSheet`,
   `PickupMixHeader`). `PickupMySeatPanel` следует этому: принимает `state`+колбэки, своего `useQuery` не имеет,
   поэтому его behavior-тест не требует `QueryClientProvider`.
10. **Инвалидация `me` по realtime бесплатна**: `RESOURCE_QUERY_KEYS["workspace.pickup_mix"]` роняет
    `customGameKeys.all(id)` = `["custom-games", id]` (`frontend/src/lib/realtime/resources.ts:120`), а
    `customGameKeys.me(ws, id)` — префиксный потомок. Отдельной подписки не заводим; контракт пинуется тестом в A8.

---

## Tasks

### Task A1: Колонки `self_signup`/`self_role_edit`, enum, capability, клон, дамп

**Files:**
- Create: `backend/migrations/versions/mixself01_mix_self_signup.py`
- Modify: `backend/shared/core/enums.py` (после 314), `backend/shared/models/custom_game.py` (33-40, 60),
  `backend/shared/rbac/catalog.py` (91), `backend/balancer-service/src/services/custom_game.py` (474-479),
  `backend/balancer-service/src/rpc/custom.py` (212-236)
- Test: `backend/shared/tests/test_custom_game_models.py` (9-14, 17-24),
  `backend/balancer-service/tests/test_custom_game.py` (111-124, 328-376),
  `backend/balancer-service/tests/test_custom_public_reads.py` (83-92, 104-109)

**Interfaces:**
- Produces: `shared.core.enums.MixSelfSignup` (`CLOSED="closed"`, `POOL="pool"`, `BENCHED="benched"`);
  `models.CustomGame.self_signup: str`, `models.CustomGame.self_role_edit: bool`;
  `_permission("custom_game", "self_join", "Self-join a pickup mix")`;
  `_dump_game(...) -> {..., "self_signup": str, "self_role_edit": bool}`
- Consumes: alembic head `varcap01`

- [ ] **Step 1: Write the failing test**

`backend/shared/tests/test_custom_game_models.py` — в класс `TestMixEnums` после строки 14:

```python
    def test_self_signup_has_exactly_three_modes(self):
        assert {mode.value for mode in enums.MixSelfSignup} == {"closed", "pool", "benched"}
```

в класс `TestCustomGameModel` после строки 24:

```python
    def test_self_service_switches_are_columns_with_a_closed_default(self):
        # The signup mode decides *where* a self-signed player lands, so it is
        # one column with three states rather than a bool plus an enum -- there
        # is no valid "closed + benched" pair to represent.
        columns = models.CustomGame.__table__.columns
        assert columns["self_signup"].server_default.arg == "closed"
        assert columns["self_role_edit"].server_default.arg == "false"
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in models.CustomGame.__table__.constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        assert "closed" in checks["ck_custom_game_self_signup"]
        assert "pool" in checks["ck_custom_game_self_signup"]
        assert "benched" in checks["ck_custom_game_self_signup"]
```

`backend/balancer-service/tests/test_custom_game.py` — в `_game()` (строки 112-122) добавить дефолты и новый тест клона
после `test_create_clone_drops_members_who_left_the_workspace` (строка 394):

```python
    async def test_create_clone_copies_the_role_edit_switch_but_closes_signup(self) -> None:
        """A clone is a NEW session: whoever the host let edit their own roles
        keeps that, but the signup window reopens by hand, never by inheritance."""
        source = _game(id=5, self_signup="pool", self_role_edit=True)
        self.games.get.return_value = source
        self.roster.list_for_game.return_value = []

        game = await self.service.create(
            self.session,
            workspace_id=1,
            host_user_id=9,
            name="Rematch",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertTrue(game.self_role_edit)
        self.assertEqual(game.self_signup, "closed")
```

`backend/balancer-service/tests/test_custom_public_reads.py` — расширить фикстуру строк 83-92 и её проверки:

```python
        row = SimpleNamespace(
            id=3,
            workspace_id=7,
            host_user_id=5,
            name="Friday mix",
            status="balanced",
            selected_variant_index=2,
            next_map_id=None,
            self_signup="pool",
            self_role_edit=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
```

и после строки 109:

```python
        self.assertEqual("pool", item["self_signup"])
        self.assertIs(True, item["self_role_edit"])
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd backend
uv run pytest shared/tests/test_custom_game_models.py balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_public_reads.py -q
```

FAIL: `AttributeError: MixSelfSignup` (модуль `shared.core.enums`), `KeyError: 'self_signup'` в
`models.CustomGame.__table__.columns`, `AttributeError: 'SimpleNamespace' object has no attribute 'self_signup'`
у клона и `KeyError: 'self_signup'` в дампе списка.

- [ ] **Step 3: Minimal implementation**

`backend/shared/core/enums.py`, после `MixParticipation` (строка 314) и перед `MixRoleSelectionMode`:

```python
class MixSelfSignup(StrEnum):
    """Who may put themselves on a mix roster, and where they land.

    One column, three states: ``closed`` is no self-signup at all, ``pool``
    seats a self-signed player straight into the pool, ``benched`` parks them
    for the host to promote. A bool plus a destination enum would admit a
    fourth, meaningless pair ("closed, but onto the bench").
    """

    CLOSED = "closed"
    POOL = "pool"
    BENCHED = "benched"
```

`backend/shared/models/custom_game.py` — в `__table_args__` (33-40) добавить CHECK:

```python
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'balanced', 'completed', 'cancelled')",
            name="ck_custom_game_status",
        ),
        CheckConstraint(
            "self_signup IN ('closed', 'pool', 'benched')",
            name="ck_custom_game_self_signup",
        ),
        # (no per-mix points_per_win check: the knob is the host's, see above)
        {"schema": "balancer"},
    )
```

и после строки 60 (`balance_result_version`):

```python
    # Whether players may seat THEMSELVES here, and where that lands them:
    # closed | pool | benched. Every existing mix ships closed, so the feature
    # is opt-in per session rather than a platform-wide change of who writes a
    # roster.
    self_signup: Mapped[str] = mapped_column(
        String(16), nullable=False, default="closed", server_default="closed"
    )
    # Whether a seated player may re-order their OWN roles and flip flex. The
    # host's book of ranks stays the host's either way.
    self_role_edit: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
```

`backend/shared/rbac/catalog.py` — после строки 91 (`registration.self_register`):

```python
    _permission("custom_game", "self_join", "Self-join a pickup mix"),
```

`backend/migrations/versions/mixself01_mix_self_signup.py` (новый файл):

```python
"""Self-signup switches on a pickup mix: the signup mode and the role-edit flag.

Revision ID: mixself01
Revises: varcap01
Create Date: 2026-09-25 00:00:00.000000

Two columns on ``balancer.custom_game``. ``self_signup`` is one column with
three states rather than a bool plus a destination enum, so "closed, but onto
the bench" cannot be represented at all -- hence the CHECK rather than a Postgres
ENUM type, which would need its own migration for every future state.

Deploy is a no-op: every existing mix gets ``closed``/``false``, which is exactly
today's behaviour (only the host and co-hosts write a roster), so the previous
release keeps serving unchanged while this runs.

No index: both columns are read only alongside the mix row itself.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixself01"
down_revision: str | Sequence[str] | None = "varcap01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "custom_game",
        sa.Column("self_signup", sa.String(length=16), server_default="closed", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("self_role_edit", sa.Boolean(), server_default="false", nullable=False),
        schema="balancer",
    )
    op.create_check_constraint(
        "ck_custom_game_self_signup",
        "custom_game",
        "self_signup IN ('closed', 'pool', 'benched')",
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_constraint("ck_custom_game_self_signup", "custom_game", schema="balancer", type_="check")
    op.drop_column("custom_game", "self_role_edit", schema="balancer")
    op.drop_column("custom_game", "self_signup", schema="balancer")
```

`backend/balancer-service/src/services/custom_game.py`, `create()` — заменить конструктор строк 474-479:

```python
        game = models.CustomGame(
            workspace_id=workspace_id,
            host_user_id=host_user_id,
            name=trimmed,
            status=MixStatus.DRAFT,
            # A clone is a new session: the host's "players edit their own roles"
            # choice carries over, the open signup window deliberately does not.
            self_role_edit=bool(source.self_role_edit) if source is not None else False,
        )
```

`backend/balancer-service/src/rpc/custom.py`, `_dump_game` — после строки 229 (`"next_map_id": game.next_map_id,`):

```python
        # Whether players may seat themselves here (closed | pool | benched) and
        # whether a seated one may re-order their own roles. Both are read by the
        # board's host controls and by the player's own panel.
        "self_signup": game.self_signup,
        "self_role_edit": game.self_role_edit,
```

- [ ] **Step 4: Run, expected PASS**

```
cd backend
uv run pytest shared/tests/test_custom_game_models.py balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_public_reads.py -q
uv run python scripts/export_erd.py
```

- [ ] **Step 5: Commit**

```
git add backend/migrations/versions/mixself01_mix_self_signup.py backend/shared/core/enums.py backend/shared/models/custom_game.py backend/shared/rbac/catalog.py backend/balancer-service/src/services/custom_game.py backend/balancer-service/src/rpc/custom.py backend/shared/tests/test_custom_game_models.py backend/balancer-service/tests/test_custom_game.py backend/balancer-service/tests/test_custom_public_reads.py docs/database_erd.md frontend/src/app/\(site\)/docs/schema.generated.json
git commit -m "feat(mix): self-signup mode and self role-edit switch on a mix"
```

---

### Task A2: `missing_account_links` в shared

**Files:**
- Create: `backend/shared/services/account_links.py`
- Test: `backend/shared/tests/test_account_links.py` (новый)

**Interfaces:**
- Produces: `async def missing_account_links(session: AsyncSession, auth_user_id: int) -> frozenset[str]`
- Consumes: `OAuthConnectionRepository.list_by_user_providers(session, *, auth_user_id, providers)`
  (`backend/shared/repository/identity.py:804-817`), `SocialProvider.DISCORD`/`BATTLENET`
  (`backend/shared/core/social.py:60-61`)

- [ ] **Step 1: Write the failing test**

`backend/shared/tests/test_account_links.py`:

```python
"""``missing_account_links`` -- which of the two required OAuth links an account lacks.

A mix self-signup needs BOTH Discord (the bot only knows who clicked) and
Battle.net (the roster is named after a BattleTag). The helper answers which one
is missing so the caller can name it, rather than a bare "not allowed". Stubbed
repository: the query itself is one ``IN`` filter, the behaviour worth pinning is
the subset it reports.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from shared.core.social import SocialProvider
from shared.services import account_links

SESSION = object()  # the stub never touches it


class _StubConnections:
    def __init__(self, providers=()):
        self.providers = list(providers)
        self.asked: list[list[str]] = []

    async def list_by_user_providers(self, _session, *, auth_user_id, providers):
        del auth_user_id
        self.asked.append(list(providers))
        return [SimpleNamespace(provider=provider) for provider in self.providers if provider in providers]


@pytest.fixture
def connections(monkeypatch):
    stub = _StubConnections()
    monkeypatch.setattr(account_links, "_connections", stub)
    return stub


def test_no_connections_means_both_links_are_missing(connections) -> None:
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"discord", "battlenet"})


def test_only_discord_linked_names_battlenet(connections) -> None:
    connections.providers = [SocialProvider.DISCORD]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"battlenet"})


def test_only_battlenet_linked_names_discord(connections) -> None:
    connections.providers = [SocialProvider.BATTLENET]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"discord"})


def test_both_linked_is_empty(connections) -> None:
    connections.providers = [SocialProvider.DISCORD, SocialProvider.BATTLENET]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset()


def test_an_unrelated_link_does_not_satisfy_either_requirement(connections) -> None:
    """Twitch/Boosty connections exist on the same table; neither proves a
    BattleTag nor a Discord identity."""
    connections.providers = [SocialProvider.TWITCH]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"discord", "battlenet"})
    assert connections.asked == [["discord", "battlenet"]]
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd backend
uv run pytest shared/tests/test_account_links.py -q
```

FAIL: `ImportError: cannot import name 'account_links' from 'shared.services'`.

- [ ] **Step 3: Minimal implementation**

`backend/shared/services/account_links.py`:

```python
"""Which of the account links a self-service mix signup requires are missing.

Two providers, and both for a concrete reason: Discord because the bot can only
act for an account that linked the Discord user who clicked, Battle.net because a
mix roster row is named after a BattleTag and its ranks are resolved through the
player identity that link creates.

Reading ``auth`` through shared is allowed here (backend/ARCHITECTURE.md:293) --
this is a read of one OAuth table, not identity business logic.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider
from shared.repository import OAuthConnectionRepository

__all__ = ("REQUIRED_LINK_PROVIDERS", "missing_account_links")

#: Order is the order a caller reports a blocker in, so it matches the admission
#: table in docs/mix-self-signup-discord/design.md.
REQUIRED_LINK_PROVIDERS: tuple[str, ...] = (SocialProvider.DISCORD, SocialProvider.BATTLENET)

_connections = OAuthConnectionRepository()


async def missing_account_links(session: AsyncSession, auth_user_id: int) -> frozenset[str]:
    """The subset of :data:`REQUIRED_LINK_PROVIDERS` this account has no OAuth row for."""
    rows = await _connections.list_by_user_providers(
        session, auth_user_id=auth_user_id, providers=list(REQUIRED_LINK_PROVIDERS)
    )
    linked = {row.provider for row in rows}
    return frozenset(provider for provider in REQUIRED_LINK_PROVIDERS if provider not in linked)
```

- [ ] **Step 4: Run, expected PASS**

```
cd backend
uv run pytest shared/tests/test_account_links.py -q
```

- [ ] **Step 5: Commit**

```
git add backend/shared/services/account_links.py backend/shared/tests/test_account_links.py
git commit -m "feat(mix): report which required account links are missing"
```

---

### Task A3: Чистая политика `mix_self_policy`

**Files:**
- Create: `backend/balancer-service/src/domain/mix_self_service.py`
- Test: `backend/balancer-service/tests/test_mix_self_service.py` (новый)

**Interfaces:**
- Produces: `MAX_ROSTER = 100`;
  `MixSelfPolicy(can_join: bool, can_leave: bool, can_edit_roles: bool, join_blocker: str | None, edit_blocker: str | None)`;
  `mix_self_policy(*, status, self_signup, self_role_edit, on_roster, missing_links, has_player, self_join_denied, roster_size) -> MixSelfPolicy`

- [ ] **Step 1: Write the failing test**

`backend/balancer-service/tests/test_mix_self_service.py`:

```python
"""``mix_self_policy`` -- the fixed order of admission checks for self-signup.

The order is the contract: the FIRST failing check is the reason a client shows,
so a closed mix must never be reported as "link your Battle.net" and a player who
lost a link must still be able to leave. Table-driven over every code in
docs/mix-self-signup-discord/design.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.domain.mix_self_service import MAX_ROSTER, mix_self_policy  # noqa: E402

BOTH = frozenset({"discord", "battlenet"})


def _policy(**overrides):
    kwargs = {
        "status": "draft",
        "self_signup": "pool",
        "self_role_edit": True,
        "on_roster": False,
        "missing_links": frozenset(),
        "has_player": True,
        "self_join_denied": False,
        "roster_size": 0,
    }
    kwargs.update(overrides)
    return mix_self_policy(**kwargs)


def test_an_open_mix_admits_a_fully_linked_newcomer() -> None:
    policy = _policy()
    assert (policy.can_join, policy.join_blocker) == (True, None)
    assert policy.can_leave is False  # not on the roster yet
    assert (policy.can_edit_roles, policy.edit_blocker) == (False, "not_on_roster")


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_a_terminal_mix_refuses_everything(status: str) -> None:
    policy = _policy(status=status, on_roster=True)
    assert (policy.can_join, policy.can_leave, policy.can_edit_roles) == (False, False, False)
    assert (policy.join_blocker, policy.edit_blocker) == ("mix_closed", "mix_closed")


def test_a_closed_mix_outranks_a_missing_link() -> None:
    """Precedence, not a coincidence: telling an unlinked player to link their
    account for a cancelled mix sends them fixing the wrong thing."""
    policy = _policy(status="cancelled", missing_links=BOTH, has_player=False)
    assert (policy.join_blocker, policy.edit_blocker) == ("mix_closed", "mix_closed")


@pytest.mark.parametrize(
    ("missing", "code"),
    [
        (frozenset({"discord"}), "discord_not_linked"),
        (frozenset({"battlenet"}), "battlenet_not_linked"),
        (BOTH, "discord_not_linked"),
    ],
)
def test_a_missing_link_blocks_join_and_edit(missing: frozenset[str], code: str) -> None:
    policy = _policy(missing_links=missing, on_roster=True)
    assert (policy.join_blocker, policy.edit_blocker) == (code, code)
    assert (policy.can_join, policy.can_edit_roles) == (False, False)


def test_leaving_survives_losing_a_link() -> None:
    """Unlinking Battle.net while rostered must not trap somebody in a lineup."""
    assert _policy(missing_links=BOTH, on_roster=True).can_leave is True


def test_no_player_identity_blocks_join_and_edit() -> None:
    policy = _policy(has_player=False, on_roster=True)
    assert (policy.join_blocker, policy.edit_blocker) == ("player_not_linked", "player_not_linked")


def test_a_missing_link_outranks_a_missing_player() -> None:
    policy = _policy(missing_links=frozenset({"battlenet"}), has_player=False)
    assert policy.join_blocker == "battlenet_not_linked"


def test_a_denied_capability_blocks_join_and_edit() -> None:
    policy = _policy(self_join_denied=True, on_roster=True)
    assert (policy.join_blocker, policy.edit_blocker) == ("self_join_denied", "self_join_denied")
    assert policy.can_leave is True


def test_a_seated_player_is_already_joined_and_may_edit() -> None:
    policy = _policy(on_roster=True)
    assert (policy.can_join, policy.join_blocker) == (False, "already_joined")
    assert (policy.can_edit_roles, policy.edit_blocker) == (True, None)


def test_already_joined_outranks_a_closed_signup_window() -> None:
    """A host closing signup must not make a seated player's panel read
    "signup_closed" -- they are in, and leaving still works."""
    policy = _policy(on_roster=True, self_signup="closed")
    assert policy.join_blocker == "already_joined"
    assert policy.can_leave is True


def test_a_closed_signup_window_blocks_a_newcomer() -> None:
    assert _policy(self_signup="closed").join_blocker == "signup_closed"


def test_a_full_roster_blocks_a_newcomer() -> None:
    assert _policy(roster_size=MAX_ROSTER).join_blocker == "roster_full"
    assert _policy(roster_size=MAX_ROSTER - 1).join_blocker is None


def test_a_closed_window_outranks_a_full_roster() -> None:
    assert _policy(self_signup="closed", roster_size=MAX_ROSTER).join_blocker == "signup_closed"


def test_the_hosts_switch_governs_role_edits_only() -> None:
    policy = _policy(on_roster=True, self_role_edit=False)
    assert (policy.can_edit_roles, policy.edit_blocker) == (False, "role_edit_off")
    assert policy.can_leave is True
    assert policy.join_blocker == "already_joined"


def test_not_being_on_the_roster_outranks_the_hosts_switch() -> None:
    policy = _policy(on_roster=False, self_role_edit=False)
    assert policy.edit_blocker == "not_on_roster"
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd backend
uv run pytest balancer-service/tests/test_mix_self_service.py -q
```

FAIL: `ModuleNotFoundError: No module named 'src.domain.mix_self_service'`.

- [ ] **Step 3: Minimal implementation**

`backend/balancer-service/src/domain/mix_self_service.py`:

```python
"""Who may seat themselves in a mix, leave it, and re-order their own roles.

Pure and session-free by the same argument as the tournament's
``self_edit_policy``: the read path calls it while serializing one player's
panel and the write path calls it again to enforce, and both must get the same
answer from the same inputs.

The order of the checks IS the contract -- the first failure is the reason the
client renders, so a terminal mix reports ``mix_closed`` rather than sending an
unlinked player off to link an account for a cancelled session.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("MAX_ROSTER", "MixSelfPolicy", "mix_self_policy")

#: Same ceiling the host's own roster write enforces
#: (``CustomGameRosterUpdate.member_ids``), so self-signup cannot grow a lineup
#: past a size the host could not have built by hand.
MAX_ROSTER = 100

#: A mix in one of these is history: nothing about its lineup is writable.
_TERMINAL = frozenset({"completed", "cancelled"})


@dataclass(frozen=True, slots=True)
class MixSelfPolicy:
    can_join: bool
    can_leave: bool
    can_edit_roles: bool
    #: Machine code for the client to translate; ``None`` while joining is open.
    join_blocker: str | None
    #: Same, for editing one's own roles.
    edit_blocker: str | None


def mix_self_policy(
    *,
    status: str,
    self_signup: str,
    self_role_edit: bool,
    on_roster: bool,
    missing_links: frozenset[str],
    has_player: bool,
    self_join_denied: bool,
    roster_size: int,
) -> MixSelfPolicy:
    """The caller's own rights over one mix.

    ``missing_links`` is a subset of ``{"discord", "battlenet"}``;
    ``has_player`` says whether the account resolves to a ``players.user`` row;
    ``self_join_denied`` is the negative-RBAC overlay on ``custom_game.self_join``.
    """
    if status in _TERMINAL:
        return MixSelfPolicy(False, False, False, "mix_closed", "mix_closed")

    # Leaving is deliberately unconditional past the terminal check: somebody
    # who unlinked Battle.net after joining must not be stuck in the lineup.
    can_leave = on_roster

    identity_blocker: str | None = None
    if "discord" in missing_links:
        identity_blocker = "discord_not_linked"
    elif "battlenet" in missing_links:
        identity_blocker = "battlenet_not_linked"
    elif not has_player:
        identity_blocker = "player_not_linked"
    elif self_join_denied:
        identity_blocker = "self_join_denied"
    if identity_blocker is not None:
        return MixSelfPolicy(False, can_leave, False, identity_blocker, identity_blocker)

    if on_roster:
        join_blocker: str | None = "already_joined"
    elif self_signup == "closed":
        join_blocker = "signup_closed"
    elif roster_size >= MAX_ROSTER:
        join_blocker = "roster_full"
    else:
        join_blocker = None

    if not on_roster:
        edit_blocker: str | None = "not_on_roster"
    elif not self_role_edit:
        edit_blocker = "role_edit_off"
    else:
        edit_blocker = None

    return MixSelfPolicy(join_blocker is None, can_leave, edit_blocker is None, join_blocker, edit_blocker)
```

- [ ] **Step 4: Run, expected PASS**

```
cd backend
uv run pytest balancer-service/tests/test_mix_self_service.py -q
```

- [ ] **Step 5: Commit**

```
git add backend/balancer-service/src/domain/mix_self_service.py backend/balancer-service/tests/test_mix_self_service.py
git commit -m "feat(mix): admission policy for self-signup and self role edits"
```

---

### Task A4: `CustomGameService` — `_apply_player_patch` + self-методы

**Files:**
- Modify: `backend/balancer-service/src/services/custom_game.py` (1-65 импорты/константы, 271-304 `__init__`,
  566-614 `update_player`, вставка новых методов после `set_participation` на 645)
- Test: `backend/balancer-service/tests/test_custom_game.py` (18-29 импорты, 111-124 `_game`, 165-259 `setUp`,
  новый блок тестов после строки 642)

**Interfaces:**
- Produces:
  - `_reject_unknown(patch: Mapping[str, Any], allowed: frozenset[str]) -> None`
  - `CustomGameService._apply_player_patch(session, row, patch, allowed: frozenset[str]) -> None`
  - `CustomGameService.self_state(session, *, custom_game_id: int, auth_user, workspace_id: int | None = None) -> dict`
  - `CustomGameService.self_join(...) -> dict`, `.self_leave(...) -> dict`
  - `CustomGameService.self_update(session, *, custom_game_id, auth_user, patch: Mapping[str, Any], workspace_id=None) -> dict`
  - `CustomGameService.set_self_service(session, *, workspace_id, custom_game_id, patch: Mapping[str, Any], actor_user_id, actor_is_superuser=False) -> models.CustomGame`
  - новые kwargs конструктора: `players`, `workspace_members`, `load_missing_links`, `enroll_member`, `grant_player_role`
- Consumes: `mix_self_policy`, `MAX_ROSTER` (A3), `missing_account_links` (A2), `MixSelfSignup` (A1),
  `UserRepository.get_by_auth_user_id` (`shared/repository/identity.py:35`),
  `WorkspaceMemberRepository.get_by_player` (`shared/repository/workspace.py:176-189`),
  `get_or_create_workspace_member` (`shared/repository/workspace.py:439-484`),
  `assign_workspace_system_role` (`shared/rbac/bootstrap.py:85-106`),
  `emit_pickup_mix_updated` (`src/services/pickup_mix_realtime.py:31`)

- [ ] **Step 1: Write the failing test**

`backend/balancer-service/tests/test_custom_game.py` — импорты (после строки 28) и хелпер после `_ranks` (строка 158):

```python
from sqlalchemy.exc import IntegrityError  # noqa: E402
```

```python
def _auth(user_id: int = 42, *, denied: bool = False) -> SimpleNamespace:
    """The gateway-rehydrated identity a self-service call carries."""
    return SimpleNamespace(
        id=user_id,
        is_superuser=False,
        can_capability=lambda _resource, _action, workspace_id=None: not denied,
    )
```

`_game()` (строки 112-122) получает два новых дефолта:

```python
        "self_signup": "closed",
        "self_role_edit": False,
```

`setUp` — после строки 212 (`self.roster.delete = AsyncMock()`):

```python
        # A single-row insert: `self_join` seats one player, unlike the host's
        # bulk `create_many`, and needs an id for the role child table.
        self.roster.create = AsyncMock(side_effect=lambda _s, row: row)
        # The self-service identity chain: auth account -> players.user ->
        # workspace_member. Linked and enrolled unless a test says otherwise.
        self.players = MagicMock()
        self.players.get_by_auth_user_id = AsyncMock(return_value=_row(id=70, auth_user_id=42))
        self.workspace_members = MagicMock()
        self.workspace_members.get_by_player = AsyncMock(return_value=None)
        # Both required OAuth links present unless a test removes one.
        self.load_missing_links = AsyncMock(return_value=frozenset())
        self.enroll_member = AsyncMock(
            side_effect=lambda _s, *, workspace_id, player_id: _row(id=7, player_id=player_id)
        )
        self.grant_player_role = AsyncMock()
        self.emit = AsyncMock()
        self._emit_patch = patch("src.services.custom_game.emit_pickup_mix_updated", new=self.emit)
        self._emit_patch.start()
        self.addCleanup(self._emit_patch.stop)
```

и в конструктор сервиса (строки 242-258) добавить:

```python
            players=self.players,
            workspace_members=self.workspace_members,
            load_missing_links=self.load_missing_links,
            enroll_member=self.enroll_member,
            grant_player_role=self.grant_player_role,
```

Новые тесты — после `test_set_participation_terminal_409` (строка 642):

```python
    async def test_self_join_seats_a_newcomer_in_the_pool(self) -> None:
        """The signup mode decides where they land; the row is an ordinary
        roster row, so the board and the host sheet need no second list."""
        seated: list = []
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.side_effect = lambda _s, _game_id: list(seated)
        self.roster.create.side_effect = lambda _s, row: seated.append(row) or row
        self.workspace_members.get_by_player.side_effect = [None, _row(id=7, player_id=70)]

        state = await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        [created] = seated
        self.assertEqual(created.workspace_member_id, 7)
        self.assertEqual(created.participation, MixParticipation.POOL)
        self.assertEqual(created.role_selection_mode, MixRoleSelectionMode.ALL_RANKED)
        self.assertEqual(created.sort_order, 0)
        self.enroll_member.assert_awaited_once()
        self.grant_player_role.assert_awaited_once_with(
            self.session, user_id=42, workspace_id=1, role_name="player"
        )
        self.assertEqual(self.emit.await_args.kwargs["change"], "roster")
        self.assertEqual(state["seat"]["participation"], MixParticipation.POOL)
        self.assertEqual(state["policy"]["join_blocker"], "already_joined")

    async def test_self_join_benched_mode_parks_the_newcomer(self) -> None:
        self.games.get.return_value = _game(self_signup="benched")
        self.roster.list_for_game.return_value = []

        await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        (_session_arg, created), _kwargs = self.roster.create.await_args
        self.assertEqual(created.participation, MixParticipation.BENCHED)

    async def test_self_join_is_idempotent_and_never_unbenches(self) -> None:
        """A host benched them on purpose; clicking Join again must not walk
        that back, and must not 409 either."""
        row = _roster_row(1, 7, 0, participation=MixParticipation.BENCHED)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        state = await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.roster.create.assert_not_awaited()
        self.assertEqual(row.participation, MixParticipation.BENCHED)
        self.assertEqual(state["seat"]["participation"], MixParticipation.BENCHED)
        self.assertEqual(state["policy"]["join_blocker"], "already_joined")

    async def test_self_join_a_lost_race_answers_with_the_seated_state(self) -> None:
        """Two clicks land on uq_custom_game_player_member; the loser reports
        the row the winner wrote instead of a 500."""
        seated = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.side_effect = [[], [seated], [seated]]
        self.roster.create.side_effect = IntegrityError("insert", {}, Exception("duplicate key"))
        self.workspace_members.get_by_player.side_effect = [None, _row(id=7, player_id=70)]

        state = await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(state["policy"]["join_blocker"], "already_joined")
        self.assertIsNotNone(state["seat"])

    async def test_self_join_without_battlenet_403(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []
        self.load_missing_links.return_value = frozenset({"battlenet"})

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "battlenet_not_linked")
        self.roster.create.assert_not_awaited()

    async def test_self_join_when_the_host_closed_signup_409(self) -> None:
        self.games.get.return_value = _game(self_signup="closed")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "signup_closed")

    async def test_self_join_on_a_finished_mix_409(self) -> None:
        self.games.get.return_value = _game(status="completed", self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "mix_closed")

    async def test_self_join_on_a_full_roster_409(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = [
            _roster_row(index + 1, index + 100, index) for index in range(MAX_ROSTER)
        ]

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "roster_full")

    async def test_self_join_denied_for_this_account_403(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_join(
                self.session, custom_game_id=11, auth_user=_auth(denied=True), workspace_id=1
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "self_join_denied")

    async def test_self_leave_works_without_account_links(self) -> None:
        """Unlinking Battle.net must not trap somebody in tonight's lineup."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.side_effect = [[row], []]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.load_missing_links.return_value = frozenset({"discord", "battlenet"})

        state = await self.service.self_leave(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.roster.delete.assert_awaited_once_with(self.session, row)
        self.assertIsNone(state["seat"])
        self.assertEqual(self.emit.await_args.kwargs["change"], "roster")

    async def test_self_leave_when_not_on_the_roster_404(self) -> None:
        self.games.get.return_value = _game(self_signup="pool")
        self.roster.list_for_game.return_value = []

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_leave(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "not_on_roster")

    async def test_self_update_reorders_the_players_own_roles(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        await self.service.self_update(
            self.session,
            custom_game_id=11,
            auth_user=_auth(),
            patch={"roles": ["support", "tank"], "is_flex": True},
            workspace_id=1,
        )

        self.player_roles.replace_for_player.assert_awaited_once_with(self.session, 1, ["support", "tank"])
        self.assertEqual(row.role_selection_mode, MixRoleSelectionMode.EXPLICIT)
        self.assertTrue(row.is_flex)

    async def test_self_update_rejects_participation_422(self) -> None:
        """Bench and must-play are the host's call, whatever the switch says."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_update(
                self.session,
                custom_game_id=11,
                auth_user=_auth(),
                patch={"participation": MixParticipation.MUST_PLAY},
                workspace_id=1,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(row.participation, MixParticipation.POOL)

    async def test_self_update_needs_the_hosts_switch_409(self) -> None:
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=False)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_update(
                self.session, custom_game_id=11, auth_user=_auth(), patch={"is_flex": True}, workspace_id=1
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "role_edit_off")
        self.assertFalse(row.is_flex)

    async def test_self_state_reports_every_role_rank_and_the_unranked_ones(self) -> None:
        """The bot labels all 16 select options, so all three roles carry a
        number or an explicit null; `unranked_roles` narrows that to what the
        player actually plays."""
        row = _roster_row(1, 7, 0, roles=["tank", "support"])
        self.games.get.return_value = _game(self_signup="pool", self_role_edit=True)
        self.roster.list_for_game.return_value = [row]
        self.workspace_members.get_by_player.return_value = _row(id=7, player_id=70)
        self.ranks.resolve.return_value = {(7, "tank"): ResolvedRank(3100, "author")}

        state = await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)

        self.assertEqual(state["seat"]["ranks"], {"tank": 3100, "damage": None, "support": None})
        self.assertEqual(state["seat"]["roles"], ["tank", "support"])
        self.assertEqual(state["unranked_roles"], ["support"])
        self.assertEqual(state["self_signup"], "pool")
        self.assertIs(state["self_role_edit"], True)

    async def test_self_state_of_a_mix_in_another_workspace_404(self) -> None:
        self.games.get.return_value = _game(workspace_id=2)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.self_state(self.session, custom_game_id=11, auth_user=_auth(), workspace_id=1)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_set_self_service_writes_both_switches(self) -> None:
        game = _game()
        self.games.get.return_value = game

        await self.service.set_self_service(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            patch={"self_signup": "benched", "self_role_edit": True},
            actor_user_id=9,
        )

        self.assertEqual(game.self_signup, "benched")
        self.assertTrue(game.self_role_edit)

    async def test_set_self_service_requires_the_host_403(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_self_service(
                self.session, workspace_id=1, custom_game_id=11, patch={"self_signup": "pool"}, actor_user_id=8
            )
        self.assertEqual(ctx.exception.status_code, 403)
```

Импорты теста дополнить (строки 18-29): `MAX_ROSTER` из `src.domain.mix_self_service`:

```python
from src.domain.mix_self_service import MAX_ROSTER  # noqa: E402
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd backend
uv run pytest balancer-service/tests/test_custom_game.py -q
```

FAIL: `TypeError: CustomGameService.__init__() got an unexpected keyword argument 'players'`.

- [ ] **Step 3: Minimal implementation**

`backend/balancer-service/src/services/custom_game.py` — импорты (после строки 21 и в блоке repository/services):

```python
from sqlalchemy.exc import IntegrityError
```

```python
from shared.core.enums import (
    CasualTeamSide,
    HeroClass,
    MixParticipation,
    MixRoleSelectionMode,
    MixSelfSignup,
    MixStatus,
)
```

```python
from shared.rbac import assign_workspace_system_role
from shared.repository import (
    CasualMatchRepository,
    CasualPlayerRepository,
    CasualTeamRepository,
    CustomGameCoHostRepository,
    CustomGamePlayerRepository,
    CustomGamePlayerRoleRepository,
    CustomGameRepository,
    CustomGameTeamNameRepository,
    MapRepository,
    UserBalancerConfigRepository,
    UserRepository,
    WorkspaceMemberRepository,
)
from shared.repository.workspace import get_or_create_workspace_member
from shared.services.account_links import missing_account_links
```

```python
from src.domain.mix_self_service import MAX_ROSTER, MixSelfPolicy, mix_self_policy
from src.services.pickup_mix_realtime import emit_pickup_mix_updated
```

Константы — после строки 65 (`_PLAYER_PATCH_FIELDS`):

```python
#: What a PLAYER may patch on their own row. Ranks are the host's book and
#: participation is the host's decision, so neither is here.
_SELF_PATCH_FIELDS = frozenset({"roles", "is_flex"})

#: HTTP status per admission blocker (``mix_self_policy``). 403 is "fix your
#: account", 409 "the mix says no", 404 "you are not in this lineup".
_BLOCKER_STATUS = {
    "mix_closed": status.HTTP_409_CONFLICT,
    "discord_not_linked": status.HTTP_403_FORBIDDEN,
    "battlenet_not_linked": status.HTTP_403_FORBIDDEN,
    "player_not_linked": status.HTTP_403_FORBIDDEN,
    "self_join_denied": status.HTTP_403_FORBIDDEN,
    "signup_closed": status.HTTP_409_CONFLICT,
    "roster_full": status.HTTP_409_CONFLICT,
    "role_edit_off": status.HTTP_409_CONFLICT,
    "not_on_roster": status.HTTP_404_NOT_FOUND,
}


def _blocker(code: str) -> HTTPException:
    """The refusal for one admission code; ``detail`` IS the code, so a client
    (site or bot) translates it instead of parsing English."""
    return HTTPException(status_code=_BLOCKER_STATUS[code], detail=code)


def _reject_unknown(patch: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown fields {unknown}")


@dataclass(frozen=True, slots=True)
class _SelfContext:
    """Everything one self-service call reads, resolved once."""

    game: models.CustomGame
    player: Any
    member: Any
    roster: list[models.CustomGamePlayer]
    row: models.CustomGamePlayer | None
    policy: MixSelfPolicy
```

(добавить `from dataclasses import dataclass` в импорты.)

`__init__` — новые kwargs после `run_balance=_run_balance` (строка 288) и присваивания после строки 304:

```python
        players: UserRepository = UserRepository(),
        workspace_members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        load_missing_links=missing_account_links,
        enroll_member=get_or_create_workspace_member,
        grant_player_role=assign_workspace_system_role,
```

```python
        self.players = players
        self.workspace_members = workspace_members
        self.load_missing_links = load_missing_links
        self.enroll_member = enroll_member
        self.grant_player_role = grant_player_role
```

`update_player` — заменить тело мутации (строки 578-614) так, чтобы правка жила в одном месте:

```python
        """Patch one roster row's participation, role selection and flex mode."""
        # Before the game read on purpose: an unknown key is a client bug, and
        # answering 422 for it must not depend on the row existing.
        _reject_unknown(patch, _PLAYER_PATCH_FIELDS)
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        row = next((item for item in roster if item.workspace_member_id == workspace_member_id), None)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game player not found")
        await self._apply_player_patch(session, row, patch, _PLAYER_PATCH_FIELDS)
        await session.flush()
        return game

    async def _apply_player_patch(
        self,
        session: AsyncSession,
        row: models.CustomGamePlayer,
        patch: Mapping[str, Any],
        allowed: frozenset[str],
    ) -> None:
        """Apply a validated lineup patch to one row, within ``allowed`` fields.

        One mutation for two callers: the host patches the whole row
        (``_PLAYER_PATCH_FIELDS``), a player only their own role order and flex
        (``_SELF_PATCH_FIELDS``). The difference between them is the gate, not
        the write -- a self edit that diverged here would be a second, subtly
        different way to set the same three columns.
        """
        _reject_unknown(patch, allowed)
        if "participation" in patch:
            try:
                row.participation = MixParticipation(patch["participation"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid participation",
                ) from exc
        if "roles" in patch:
            roles = _normalize_roles(patch["roles"])
            row.role_selection_mode = (
                MixRoleSelectionMode.ALL_RANKED if roles is None else MixRoleSelectionMode.EXPLICIT
            )
            await self.player_roles.replace_for_player(session, row.id, roles or ())
        if "is_flex" in patch:
            if not isinstance(patch["is_flex"], bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="is_flex must be a boolean",
                )
            row.is_flex = patch["is_flex"]
```

Новые методы — после `set_participation` (строка 645):

```python
    async def _self_context(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None,
    ) -> _SelfContext:
        """The mix, the caller's own seat in it, and the policy over both.

        The workspace comes from the mix row, not the caller: the bot knows a
        ``custom_game_id`` and nothing else. When a ``workspace_id`` IS supplied
        (the site's route carries one) it must agree, or this is a 404 -- the same
        answer a mix of another workspace gets everywhere else.
        """
        game = await self.games.get(session, custom_game_id)
        if game is None or (workspace_id is not None and game.workspace_id != workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        player = await self.players.get_by_auth_user_id(session, auth_user.id)
        member = (
            None
            if player is None
            else await self.workspace_members.get_by_player(
                session, workspace_id=game.workspace_id, player_id=player.id
            )
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        row = (
            None
            if member is None
            else next((item for item in roster if item.workspace_member_id == member.id), None)
        )
        policy = mix_self_policy(
            status=game.status,
            self_signup=game.self_signup,
            self_role_edit=game.self_role_edit,
            on_roster=row is not None,
            missing_links=await self.load_missing_links(session, auth_user.id),
            has_player=player is not None,
            self_join_denied=not auth_user.can_capability(
                "custom_game", "self_join", workspace_id=game.workspace_id
            ),
            roster_size=len(roster),
        )
        return _SelfContext(game=game, player=player, member=member, roster=roster, row=row, policy=policy)

    async def _self_dump(self, session: AsyncSession, ctx: _SelfContext) -> dict[str, Any]:
        """One player's view of one mix: their seat, and what they may do next.

        ``ranks`` carries all three roles, ``None`` included: the Discord role
        select labels every option with a number or "no rank", and a sparse dict
        would make the bot guess. ``unranked_roles`` is the narrower list the
        warning is built from -- the roles this player actually plays.
        """
        seat: dict[str, Any] | None = None
        unranked: list[str] = []
        if ctx.row is not None:
            stored = (await self.player_roles.roles_for_players(session, [ctx.row.id])).get(ctx.row.id, [])
            explicit = ctx.row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
            resolved = await self.ranks.resolve(
                session,
                workspace_id=ctx.game.workspace_id,
                members={ctx.row.workspace_member_id: ctx.player.id if ctx.player is not None else None},
                roles=list(REGISTRATION_ROLE_CODES),
                order=MIX_ORDER,
                author_user_id=ctx.game.host_user_id,
                grid=await get_effective_division_grid(session, None),
            )
            ranks: dict[str, int | None] = {}
            for role in REGISTRATION_ROLE_CODES:
                rank = resolved.get((ctx.row.workspace_member_id, role))
                ranks[role] = rank.value if rank is not None else None
            considered = list(stored) if explicit else list(REGISTRATION_ROLE_CODES)
            unranked = [role for role in considered if ranks.get(role) is None]
            seat = {
                "participation": ctx.row.participation,
                # ``null`` means all_ranked: every role this player has a number
                # for plays, which is a different statement from an empty list.
                "roles": list(stored) if explicit else None,
                "is_flex": ctx.row.is_flex,
                "ranks": ranks,
            }
        return {
            "custom_game_id": ctx.game.id,
            "name": ctx.game.name,
            "status": ctx.game.status,
            "self_signup": ctx.game.self_signup,
            "self_role_edit": ctx.game.self_role_edit,
            "seat": seat,
            "unranked_roles": unranked,
            "policy": {
                "can_join": ctx.policy.can_join,
                "can_leave": ctx.policy.can_leave,
                "can_edit_roles": ctx.policy.can_edit_roles,
                "join_blocker": ctx.policy.join_blocker,
                "edit_blocker": ctx.policy.edit_blocker,
            },
        }

    async def self_state(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Read-only: what this account's seat is and what it may do."""
        return await self._self_dump(
            session,
            await self._self_context(
                session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
            ),
        )

    async def self_join(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Seat this account in the mix, enrolling it in the workspace if needed.

        Idempotent by design: an existing row is left EXACTLY as it is, so a
        player the host benched cannot walk that back by clicking Join again.
        """
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if ctx.row is not None:
            return await self._self_dump(session, ctx)
        if ctx.policy.join_blocker is not None:
            raise _blocker(ctx.policy.join_blocker)

        # Same two idempotent steps the tournament self-registration takes
        # (tournament-service/src/services/registration/service.py:582-602): the
        # membership row anchors the roster row, the baseline RBAC role makes the
        # account an ordinary workspace player rather than a role-less anchor.
        member = ctx.member or await self.enroll_member(
            session, workspace_id=ctx.game.workspace_id, player_id=ctx.player.id
        )
        await self.grant_player_role(
            session, user_id=auth_user.id, workspace_id=ctx.game.workspace_id, role_name="player"
        )
        row = _new_roster_row(ctx.game.id, member.id, len(ctx.roster))
        row.participation = MixParticipation(ctx.game.self_signup)
        try:
            async with session.begin_nested():
                await self.roster.create(session, row)
        except IntegrityError:
            # Two clicks raced onto uq_custom_game_player_member. The other one
            # seated them, so report the state it produced instead of a 500.
            return await self.self_state(
                session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
            )
        await self._seed_host_ranks(
            session, ctx.game, await self.members(session, ctx.game.workspace_id, [member.id])
        )
        await session.flush()
        await emit_pickup_mix_updated(
            session, ctx.game.workspace_id, change="roster", actor_user_id=auth_user.id
        )
        return await self.self_state(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )

    async def self_leave(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Drop this account's own row, exactly as the host removing it would.

        Deliberately does not require the account links: somebody who unlinked
        Battle.net after joining must still be able to get out of the lineup.
        """
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if not ctx.policy.can_leave or ctx.row is None:
            # A terminal mix refuses every write; anything else means this
            # account simply holds no row in this lineup.
            raise _blocker("mix_closed" if ctx.policy.join_blocker == "mix_closed" else "not_on_roster")
        await self.roster.delete(session, ctx.row)
        await session.flush()
        await emit_pickup_mix_updated(
            session, ctx.game.workspace_id, change="roster", actor_user_id=auth_user.id
        )
        return await self.self_state(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )

    async def self_update(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        patch: Mapping[str, Any],
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Re-order this account's own roles / flip its flex flag.

        The stored balance is NOT recomputed: it is a snapshot of a search the
        host ran, and a role change takes effect the next time they balance.
        """
        _reject_unknown(patch, _SELF_PATCH_FIELDS)
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if ctx.row is None or not ctx.policy.can_edit_roles:
            raise _blocker(ctx.policy.edit_blocker or "not_on_roster")
        await self._apply_player_patch(session, ctx.row, patch, _SELF_PATCH_FIELDS)
        await session.flush()
        await emit_pickup_mix_updated(
            session, ctx.game.workspace_id, change="roster", actor_user_id=auth_user.id
        )
        return await self.self_state(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )

    async def set_self_service(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        patch: Mapping[str, Any],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """The host's two switches: who may seat themselves, and who may re-role."""
        _reject_unknown(patch, frozenset({"self_signup", "self_role_edit"}))
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if "self_signup" in patch:
            try:
                game.self_signup = MixSelfSignup(patch["self_signup"]).value
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid self_signup",
                ) from exc
        if "self_role_edit" in patch:
            if not isinstance(patch["self_role_edit"], bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="self_role_edit must be a boolean",
                )
            game.self_role_edit = patch["self_role_edit"]
        await session.flush()
        return game
```



- [ ] **Step 4: Run, expected PASS**

```
cd backend
uv run pytest balancer-service/tests/test_custom_game.py -q
```

- [ ] **Step 5: Commit**

```
git add backend/balancer-service/src/services/custom_game.py backend/balancer-service/tests/test_custom_game.py
git commit -m "feat(mix): self-service join, leave and role edit on a pickup mix"
```

---

### Task A5: RPC-субъекты, gateway-маршруты, OpenAPI/RPC-доки

**Files:**
- Modify: `backend/balancer-service/src/schemas/custom_game.py` (1-29 импорты/`__all__`, хвост файла),
  `backend/balancer-service/src/rpc/custom.py` (1-17 docstring, вставка после `_set_participation` на 555),
  `gateway/internal/balancer/routes.go` (после 92), `gateway/internal/balancer/routes_test.go` (170-198),
  `backend/balancer-service/src/openapi_schemas.py` (113-125),
  `backend/balancer-service/src/openapi_docs.py` (после 294), `gateway/internal/openapi/schemas.json` (регенерация)
- Test: `backend/balancer-service/tests/test_custom_game_contract.py` (хвост), `gateway/internal/balancer/routes_test.go`

**Interfaces:**
- Produces: subjects `rpc.balancer.custom.{self_get,self_join,self_leave,self_update,set_self_service}`;
  схемы `CustomGameSelfUpdate`, `CustomGameSelfServicePatch`;
  маршруты `GET|POST|DELETE|PATCH …/custom-games/{game_id}/me`, `PUT …/custom-games/{game_id}/self-service`
- Consumes: A4 (`self_state`/`self_join`/`self_leave`/`self_update`/`set_self_service`), `_game_id`/`_opt_int`/`_body`
  (`src/rpc/custom.py:59-93`)

- [ ] **Step 1: Write the failing test**

`backend/balancer-service/tests/test_custom_game_contract.py` — в конец файла:

```python
def test_self_update_distinguishes_an_unset_roles_field_from_a_null_one() -> None:
    """``null`` is "every ranked role"; omitting the key is "don't touch my
    roles". Collapsing the two would silently reset a role order on a flex
    toggle."""
    unset = _schemas().CustomGameSelfUpdate.model_validate({"is_flex": True})
    cleared = _schemas().CustomGameSelfUpdate.model_validate({"roles": None})
    assert unset.model_fields_set == {"is_flex"}
    assert cleared.model_fields_set == {"roles"}
    assert cleared.roles is None


def test_self_update_refuses_the_hosts_own_fields() -> None:
    with pytest.raises(ValidationError):
        _schemas().CustomGameSelfUpdate.model_validate({"participation": "must_play"})


def test_self_update_validates_role_codes() -> None:
    assert _schemas().CustomGameSelfUpdate.model_validate({"roles": ["support", "tank"]}).roles == [
        "support",
        "tank",
    ]
    with pytest.raises(ValidationError):
        _schemas().CustomGameSelfUpdate.model_validate({"roles": ["healer"]})


def test_self_service_patch_takes_the_three_signup_modes_and_nothing_else() -> None:
    patch = _schemas().CustomGameSelfServicePatch.model_validate({"self_signup": "benched"})
    assert patch.self_signup is enums.MixSelfSignup.BENCHED
    assert patch.model_fields_set == {"self_signup"}
    with pytest.raises(ValidationError):
        _schemas().CustomGameSelfServicePatch.model_validate({"self_signup": "open"})
    with pytest.raises(ValidationError):
        _schemas().CustomGameSelfServicePatch.model_validate({"self_role_edit": "yes"})
```

`gateway/internal/balancer/routes_test.go` — новый тест после `TestMixReadsArePublic` (строка 198):

```go
// TestMixSelfServiceRoutes pins the player's own surface. All four /me verbs
// share one pattern, so a wrong Method turns a read into a write (or a leave
// into a join); all of them are AuthRequired because the worker authorizes the
// clicker, and the host-only switches must not land on /me.
func TestMixSelfServiceRoutes(t *testing.T) {
	want := map[string]string{
		"GET /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me":            "rpc.balancer.custom.self_get",
		"POST /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me":           "rpc.balancer.custom.self_join",
		"DELETE /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me":         "rpc.balancer.custom.self_leave",
		"PATCH /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me":          "rpc.balancer.custom.self_update",
		"PUT /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/self-service":  "rpc.balancer.custom.set_self_service",
	}
	for _, route := range RosterRoutes {
		key := route.Method + " " + route.Pattern
		queue, ok := want[key]
		if !ok {
			continue
		}
		if route.Queue != queue {
			t.Fatalf("unexpected queue for %s: %#v", key, route)
		}
		if route.Auth != edge.AuthRequired {
			t.Fatalf("self-service route %s must be authenticated: %#v", key, route)
		}
		delete(want, key)
	}
	if len(want) != 0 {
		t.Fatalf("missing mix self-service routes: %#v", want)
	}
}
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd backend && uv run pytest balancer-service/tests/test_custom_game_contract.py -q
cd ../gateway && go test ./internal/balancer/...
```

FAIL: `AttributeError: module 'src.schemas.custom_game' has no attribute 'CustomGameSelfUpdate'`;
Go: `missing mix self-service routes: map[...]`.

- [ ] **Step 3: Minimal implementation**

`backend/balancer-service/src/schemas/custom_game.py` — импорт enum'а (строка 11) и `__all__`:

```python
from shared.core.enums import MixParticipation, MixSelfSignup
```

```python
    "CustomGameSelfServicePatch",
    "CustomGameSelfUpdate",
```

в конец файла:

```python
class CustomGameSelfUpdate(_Request):
    """What a PLAYER may change about their own seat.

    ``roles`` absent means "leave my role order alone"; ``roles: null`` means
    "every role I have a rank for". The two are distinguished by
    ``model_fields_set``, so a flex toggle cannot silently reset a role order.
    """

    roles: list[str] | None = None
    is_flex: StrictBool | None = None

    @field_validator("roles")
    @classmethod
    def _roles(cls, roles: list[str] | None) -> list[str] | None:
        if roles is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in roles:
            role = raw.strip().lower()
            if role not in REGISTRATION_ROLE_CODES:
                raise ValueError(f"unknown role {role}")
            if role not in seen:
                seen.add(role)
                normalized.append(role)
        return normalized


class CustomGameSelfServicePatch(_Request):
    """The host's self-service switches: the signup mode and the role-edit flag."""

    self_signup: MixSelfSignup | None = None
    self_role_edit: StrictBool | None = None
```

`backend/balancer-service/src/rpc/custom.py` — docstring (строки 3-6) дополнить перечислением:
`self_get,self_join,self_leave,self_update,set_self_service`, и добавить абзац:

```
The five ``self_*`` subjects are the PLAYER's own surface: they are gated by
``mix_self_policy`` inside the service rather than by ``_require_mix``, because
whoever is joining may not be a workspace member yet. ``workspace_id`` is
optional on them -- the bot knows only a ``custom_game_id`` -- and when present
must match the mix's own.
```

Обработчики — после `_set_participation` (строка 555):

```python
    @broker.subscriber("rpc.balancer.custom.self_get")
    async def _self_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            return await custom_game_service.self_state(
                session,
                custom_game_id=_game_id(data),
                auth_user=user,
                workspace_id=_opt_int(data, "workspace_id"),
            )

        return await c.envelope(logger, "custom.self_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_join")
    async def _self_join(data: dict, msg: RabbitMessage) -> dict:
        """Seat the caller. Not gated by ``_require_mix``: somebody joining a
        workspace's mix for the first time is not a member of it yet -- the
        enrolment is part of what this does."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            state = await custom_game_service.self_join(
                session,
                custom_game_id=_game_id(data),
                auth_user=user,
                workspace_id=_opt_int(data, "workspace_id"),
            )
            await session.commit()
            return state

        return await c.envelope(logger, "custom.self_join", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_leave")
    async def _self_leave(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            state = await custom_game_service.self_leave(
                session,
                custom_game_id=_game_id(data),
                auth_user=user,
                workspace_id=_opt_int(data, "workspace_id"),
            )
            await session.commit()
            return state

        return await c.envelope(logger, "custom.self_leave", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_update")
    async def _self_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            body = _body(schemas.CustomGameSelfUpdate, data)
            state = await custom_game_service.self_update(
                session,
                custom_game_id=_game_id(data),
                auth_user=user,
                # exclude_unset keeps "don't touch my roles" apart from
                # "roles: null" (= every ranked role).
                patch=body.model_dump(exclude_unset=True),
                workspace_id=_opt_int(data, "workspace_id"),
            )
            await session.commit()
            return state

        return await c.envelope(logger, "custom.self_update", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_self_service")
    async def _set_self_service(data: dict, msg: RabbitMessage) -> dict:
        """The host's switches, so this one IS an ordinary mix write: membership
        plus host-or-co-host in ``_writable``."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameSelfServicePatch, data)
            game = await custom_game_service.set_self_service(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                patch=body.model_dump(exclude_unset=True),
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="member", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_self_service", op, session_factory=_SF)
```

`gateway/internal/balancer/routes.go` — после строки 92 (`discord/post`):

```go
	// The player's own seat. One pattern, four verbs: read it, take it, drop it,
	// re-role it. AuthRequired because the worker authorizes the clicker (the bot
	// forwards the linked account's identity the same way the site does); the
	// worker, not this table, decides whether signup is open.
	{Method: "GET", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me", Queue: "rpc.balancer.custom.self_get", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthRequired, Timeout: fastReadTimeout},
	{Method: "POST", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me", Queue: "rpc.balancer.custom.self_join", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me", Queue: "rpc.balancer.custom.self_leave", IDParam: "game_id", Path: []string{"workspace_id"}, Auth: edge.AuthRequired},
	{Method: "PATCH", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/me", Queue: "rpc.balancer.custom.self_update", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
	// Host-only: whether players may seat themselves at all, and whether a
	// seated one may re-order their own roles.
	{Method: "PUT", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/self-service", Queue: "rpc.balancer.custom.set_self_service", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
```

`backend/balancer-service/src/openapi_schemas.py` — после строки 116 (`update_player`):

```python
    "rpc.balancer.custom.self_update": Op(request=custom_game.CustomGameSelfUpdate),
    "rpc.balancer.custom.set_self_service": Op(request=custom_game.CustomGameSelfServicePatch),
```

`backend/balancer-service/src/openapi_docs.py` — после блока `set_participation` (строка 294):

```python
    "rpc.balancer.custom.self_get": {
        "summary": "Get my mix seat",
        "description": (
            "Permission: any authenticated account; workspace membership is NOT required. "
            "Returns the caller's own seat in the mix (participation, role order, the ranks the "
            "host's book resolves for them) plus what they may do next: join, leave, edit roles, "
            "and the blocker code for each. `seat` is null when the caller is not on the roster."
        ),
    },
    "rpc.balancer.custom.self_join": {
        "summary": "Join a mix myself",
        "description": (
            "Permission: any authenticated account with both Discord and Battle.net linked and "
            "`custom_game.self_join` not denied; workspace membership is created on the way in. "
            "Seats the caller according to the mix's signup mode (pool or bench) and returns the "
            "same state as the read. Idempotent: an existing row is left untouched, bench included. "
            "403 for an unlinked account, 409 when signup is closed, the mix is over or the roster "
            "is full."
        ),
    },
    "rpc.balancer.custom.self_leave": {
        "summary": "Leave a mix myself",
        "description": (
            "Permission: any authenticated account holding a seat in this mix -- the account links "
            "are deliberately NOT required, so unlinking one cannot trap somebody in a lineup. "
            "Removes the caller's own roster row; the stored balance is kept until the host "
            "re-balances. 404 when the caller has no seat, 409 once the mix is over."
        ),
    },
    "rpc.balancer.custom.self_update": {
        "summary": "Update my mix seat",
        "description": (
            "Permission: a seated account, while the host's 'players edit their own roles' switch "
            "is on. Re-orders the caller's own roles (null = every role they have a rank for) and "
            "flips their flex flag; participation and ranks stay the host's. The shown balance is "
            "not recomputed -- the change applies to the next one. 409 when the switch is off, 404 "
            "when the caller has no seat."
        ),
    },
    "rpc.balancer.custom.set_self_service": {
        "summary": "Set custom game self-service switches",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Sets whether players may seat themselves (closed, into the pool, or onto the bench) and "
            "whether a seated player may re-order their own roles, then returns the refreshed mix."
        ),
    },
```

- [ ] **Step 4: Run, expected PASS**

```
cd backend
uv run pytest balancer-service/tests/test_custom_game_contract.py balancer-service/tests/test_custom_public_reads.py -q
bash scripts/export_openapi_schemas.sh
uv run python scripts/check_rpc_docs.py
cd ../gateway && go test ./internal/balancer/...
```

- [ ] **Step 5: Commit**

```
git add backend/balancer-service/src/schemas/custom_game.py backend/balancer-service/src/rpc/custom.py backend/balancer-service/src/openapi_schemas.py backend/balancer-service/src/openapi_docs.py backend/balancer-service/tests/test_custom_game_contract.py gateway/internal/balancer/routes.go gateway/internal/balancer/routes_test.go gateway/internal/openapi/schemas.json
git commit -m "feat(mix): self-service RPC subjects and gateway routes"
```

---

### Task A6a: `values` селекта проходят через Action/dispatcher/cog, билдер селекта в cards.py

**Files:**
- Modify `backend/discord-service/src/interactions/actions.py` (19, 31-47, 50-66, 74-89)
- Modify `backend/discord-service/src/interactions/cards.py` (11-20, 51-64)
- Modify `backend/discord-service/src/interactions/dispatcher.py` (17, 29, 78-107, 158-166)
- Modify `backend/discord-service/src/cogs/interactions.py` (28-46)
- Test `backend/discord-service/tests/test_interactions.py`

**Interfaces:**
- Produces `Action.request: Callable[[str, Sequence[str]], dict[str, Any]]` — может бросить
  `ValueError` для значения, которое бот не выпускал.
- Produces `cards.select_row(*, action: str, target: str, placeholder: str, options: Sequence[discord.SelectOption]) -> discord.ui.ActionRow`
- Produces `cards.card_view(card: DiscordCard, *, extra_rows: Sequence[discord.ui.ActionRow] = ()) -> discord.ui.LayoutView`
- Produces `ActionDispatcher.perform(discord_user_id: int, action_name: str, target: str, values: Sequence[str] = ()) -> Outcome`
- Produces `ActionDispatcher.handle(interaction: discord.Interaction, action_name: str, target: str, values: Sequence[str] = ()) -> None`
- Produces `Outcome(status="failed", code="bad_values")` — значение компонента не разобрано.
- Consumes `interaction.data["values"]` (discord.py component interaction payload).

- [ ] **Step 1: Написать падающий тест.**
  В `tests/test_interactions.py` дополнить импорт селект-билдером (строка 27):

  ```python
  from src.interactions.cards import card_view, select_row, settle  # noqa: E402
  ```

  И добавить класс в конец файла:

  ```python
  class SelectComponentTests(IsolatedAsyncioTestCase):
      """A select is routed by the same ``custom_id`` as a button, and Discord gives it a row of its own."""

      async def test_a_select_routes_like_a_button_and_sits_alone_in_its_row(self) -> None:
          row = select_row(
              action="registration.view",
              target="3",
              placeholder="Roles",
              options=[
                  discord.SelectOption(label="Tank", value="tank", description="Tank 3100", default=True),
                  discord.SelectOption(label="Support", value="support"),
              ],
          )

          view = card_view(DiscordCard(text="### Roles"), extra_rows=[row])

          container, rendered = view.to_components()
          self.assertEqual(container["type"], 17)
          (select,) = rendered["components"]
          self.assertEqual(select["type"], 3)
          self.assertEqual(parse_custom_id(select["custom_id"]), ("registration.view", "3"))
          self.assertEqual(
              [(option["value"], option["default"]) for option in select["options"]],
              [("tank", True), ("support", False)],
          )
  ```

- [ ] **Step 2: Запустить, ожидается FAIL.**
  ```
  cd backend && uv run pytest discord-service/tests/test_interactions.py -q
  ```
  Ожидается `ImportError: cannot import name 'select_row' from 'src.interactions.cards'` — сбор
  модуля падает целиком, ни один тест файла не стартует.

- [ ] **Step 3: Минимальная реализация.**

  **`src/interactions/actions.py`** — строка 19, импорт:

  ```python
  from collections.abc import Callable, Sequence
  ```

  Строки 31-47 — билдеры получают второй параметр:

  ```python
  def _invite(target: str, values: Sequence[str]) -> dict[str, Any]:
      # A body field, not a path parameter: the site sends it the same way
      # (``POST /registration-teams/invites/accept``), so the handler cannot tell.
      return {"payload": {"invite_id": int(target)}}


  def _tournament(target: str, values: Sequence[str]) -> dict[str, Any]:
      # ``{tournament_id}`` is a path parameter, which the gateway copies to the body by name.
      return {"tournament_id": int(target)}


  def _nothing(target: str, values: Sequence[str]) -> dict[str, Any]:
      return {}


  def _everything(target: str) -> bool:
      return target == "all"
  ```

  Строки 50-66 — `Action`, докстрока и тип `request`:

  ```python
  @dataclass(frozen=True, slots=True)
  class Action:
      """One button's platform call.

      ``subject`` is ``None`` for a button the bot answers alone (it only shows
      the next button, so it needs neither an account nor a call). ``request``
      turns the target -- and, for a select, the values Discord sent with the
      click -- into the RPC body next to ``identity``; ``accepts`` is checked
      before anything is called, so a malformed target is refused here rather
      than as a 422 from the service. A value the bot never minted is refused
      the same way: ``request`` raises ``ValueError`` and no RPC is made.
      ``settles`` names the card buttons that stop making sense once this
      succeeded -- they are taken off the DM it was clicked in (never off a
      channel post, which is everyone's).
      """

      subject: str | None
      request: Callable[[str, Sequence[str]], dict[str, Any]] = _nothing
      accepts: Callable[[str], bool] = str.isdigit
      settles: frozenset[str] = field(default_factory=frozenset)
  ```

  Строки 84-88 — лямбда «mute» получает второй параметр:

  ```python
      "notifications.mute": Action(
          "rpc.app.notification_preferences_update",
          # Every group, not the card's: the reader asked for Discord to go quiet.
          # In-app notifications are not affected, and settings turn DMs back on.
          lambda _all, _values: {"payload": {"discord_dm": dict.fromkeys(NOTIFICATION_GROUPS, False)}},
          accepts=_everything,
      ),
  ```

  **`src/interactions/cards.py`** — строки 11-20, импорты и `__all__`:

  ```python
  from __future__ import annotations

  from collections.abc import Sequence
  from typing import Any

  import discord

  from shared.schemas.events import DiscordActionButton, DiscordButton, DiscordCard
  from src.interactions.actions import custom_id, parse_custom_id

  __all__ = ("card_view", "select_row", "settle")
  ```

  Строки 51-64 — `card_view` принимает готовые ряды бота, и новый `select_row` под ним:

  ```python
  def card_view(card: DiscordCard, *, extra_rows: Sequence[discord.ui.ActionRow] = ()) -> discord.ui.LayoutView:
      text = discord.ui.TextDisplay(card.text)
      children: list[discord.ui.Item[Any]] = [
          discord.ui.Section(text, accessory=discord.ui.Thumbnail(card.thumbnail_url)) if card.thumbnail_url else text
      ]
      if card.details:
          children += [discord.ui.Separator(), discord.ui.TextDisplay(card.details)]
      if card.answers:
          children.append(discord.ui.ActionRow(*(_button(button) for button in card.answers)))
      view = discord.ui.LayoutView(timeout=None)
      view.add_item(discord.ui.Container(*children, accent_colour=card.accent_color))
      # Rows the bot built itself (a select) sit above the card's own buttons.
      for row in extra_rows:
          view.add_item(row)
      for row in card.rows:
          view.add_item(discord.ui.ActionRow(*(_button(button) for button in row)))
      return _detached(view)


  def select_row(
      *,
      action: str,
      target: str,
      placeholder: str,
      options: Sequence[discord.SelectOption],
  ) -> discord.ui.ActionRow:
      """A string select as a row of its own, answered by ``custom_id`` like a button.

      Discord allows nothing else beside a select in its action row, so the row
      is built here instead of being folded into ``DiscordCard.rows``: the card
      contract carries buttons only, and a select is something the bot builds
      for its own ephemeral replies -- never something a publisher can ask for.
      """
      return discord.ui.ActionRow(
          discord.ui.Select(custom_id=custom_id(action, target), placeholder=placeholder, options=list(options))
      )
  ```

  **`src/interactions/dispatcher.py`** — строка 17, импорт `Sequence`; строка 29 — `select_row`
  (понадобится в A6b, добавляем сразу, чтобы не трогать импорт дважды):

  ```python
  from collections.abc import Callable, Mapping, Sequence
  ```
  ```python
  from src.interactions.cards import card_view, select_row, settle
  ```

  Строки 78-107 — тело RPC строится до брокера:

  ```python
      async def perform(
          self, discord_user_id: int, action_name: str, target: str, values: Sequence[str] = ()
      ) -> Outcome:
          """Act as the account linked to ``discord_user_id``. ``target`` is already validated."""
          action = ACTIONS[action_name]
          if action.subject is None:
              # Answered by the bot alone: it only shows the next button, and that
              # button is where the account is checked.
              return Outcome("ok")
          try:
              request = action.request(target, tuple(values))
          except ValueError:
              # A component value the bot never minted: refused here, so a mangled
              # select costs neither an identity lookup nor a platform call.
              return Outcome("failed", code="bad_values")
          broker = self._broker()
          if broker is None:
              return Outcome("unavailable")
  ```

  и строка 107 (вызов действия) — использовать уже построенное тело:

  ```python
              reply = await request_rpc(
                  broker, {"identity": who.data, **request}, action.subject, timeout=self._timeout
              )
  ```

  Строки 158-166 — `handle` пробрасывает `values`:

  ```python
      async def handle(
          self, interaction: discord.Interaction, action_name: str, target: str, values: Sequence[str] = ()
      ) -> None:
          locale = copy.locale_of(interaction.locale)
          # Acknowledge first: Discord fails a click left unanswered for three
          # seconds, and two RPCs can take longer. For a button this is a silent
          # "update the message later", so nothing flashes in the channel.
          await interaction.response.defer()
          try:
              outcome = await self.perform(interaction.user.id, action_name, target, values)
  ```

  **`src/cogs/interactions.py`** — строки 28-46, `on_interaction` целиком:

  ```python
      @commands.Cog.listener()
      async def on_interaction(self, interaction: discord.Interaction) -> None:
          if interaction.type is not discord.InteractionType.component:
              return
          data = interaction.data or {}
          value = data.get("custom_id")
          if not is_ours(value):
              return
          parsed = parse_custom_id(value)
          try:
              if parsed is None:
                  # Ours, but an action since retired or a mangled target: answer
                  # rather than let Discord show "This interaction failed".
                  locale = copy.locale_of(interaction.locale)
                  await interaction.response.send_message(copy.text(locale, "expired_button"), ephemeral=True)
                  return
              # A select sends what was picked; a button sends nothing.
              values = tuple(str(item) for item in data.get("values") or ())
              await self._dispatcher.handle(interaction, *parsed, values)
          except discord.HTTPException as exc:
              # Typically a click that reached us after Discord's 3-second window:
              # nothing ran, and the clicker can press again.
              logger.warning(f"Could not answer Discord button {value}: {exc!r}")
  ```

- [ ] **Step 4: Запустить, ожидается PASS.**
  ```
  cd backend && uv run pytest discord-service/tests/test_interactions.py -q
  ```
  Весь файл зелёный: новый `SelectComponentTests` плюс прежние 12 тестов — в частности
  `test_the_action_runs_with_the_identity_identity_service_returned` (кнопка без значений по-прежнему
  шлёт `{"identity": …, "payload": {"invite_id": 42}}`) и
  `test_muting_switches_every_group_off_and_answers_in_place`.

- [ ] **Step 5: Коммит.**
  ```
  git add backend/discord-service/src/interactions/actions.py backend/discord-service/src/interactions/cards.py backend/discord-service/src/interactions/dispatcher.py backend/discord-service/src/cogs/interactions.py backend/discord-service/tests/test_interactions.py
  git commit -m "refactor(discord): thread component values through card actions"
  ```

---

### Task A6b: пять действий микса, разбор селекта и эфемерный ответ

**Files:**
- Modify `backend/shared/schemas/events.py` (32-39)
- Modify `backend/discord-service/src/interactions/actions.py` (после A6a: импорты, билдеры, `ACTIONS`)
- Modify `backend/discord-service/src/interactions/copy.py` (16, 25-58, 139-143, конец файла)
- Modify `backend/discord-service/src/interactions/dispatcher.py` (после A6a: `reply`, новые хелперы)
- Test `backend/discord-service/tests/test_interactions.py`

**Interfaces:**
- Consumes self-state wire dict (backend-задачи A1–A5, A7):
  `{custom_game_id, name, status, self_signup, self_role_edit, seat: null | {participation, roles: list[str] | null, is_flex, ranks: {tank|damage|support: int | null}}, unranked_roles: list[str], policy: {can_join, can_leave, can_edit_roles, join_blocker, edit_blocker}}`
- Consumes конверт отказа `{"code": "forbidden"|"conflict"|"not_found", "message": "<blocker>"}`
- Produces RPC-тела: `{"custom_game_id": int}` (join/leave/roles),
  `{"custom_game_id": int, "payload": {"roles": list[str] | None}}` (roles_set),
  `{"custom_game_id": int, "payload": {"is_flex": bool}}` (flex)
- Produces `copy.mix_text(locale: Locale, state: Mapping[str, Any]) -> str`
- Produces `copy.mix_role_options(locale: Locale, state: Mapping[str, Any]) -> list[discord.SelectOption]`
- Produces `copy.mix_blocker_text(locale: Locale, code: str) -> str`,
  `copy.MIX_BLOCKERS: frozenset[str]`, `copy.LINK_BLOCKERS: frozenset[str]`
- Produces `DiscordAction` += `mix.join` `mix.leave` `mix.roles` `mix.roles_set` `mix.flex`

- [ ] **Step 1: Написать падающий тест.**
  В `tests/test_interactions.py` дополнить импорт (строка 28):

  ```python
  from src.interactions.dispatcher import IDENTITY_SUBJECT, ActionDispatcher, Outcome  # noqa: E402
  ```

  Добавить фабрику состояния рядом с `_invite_card()` (после строки 69):

  ```python
  def _mix_state(**overrides: Any) -> dict[str, Any]:
      """The ``self_*`` wire answer: a seated player who may reorder their roles."""
      state: dict[str, Any] = {
          "custom_game_id": 42,
          "name": "Пятничный микс",
          "status": "balanced",
          "self_signup": "pool",
          "self_role_edit": True,
          "seat": {
              "participation": "pool",
              "roles": ["tank", "support"],
              "is_flex": False,
              "ranks": {"tank": 3100, "damage": None, "support": None},
          },
          "unranked_roles": ["support"],
          "policy": {
              "can_join": False,
              "can_leave": True,
              "can_edit_roles": True,
              "join_blocker": "already_joined",
              "edit_blocker": None,
          },
      }
      state.update(overrides)
      return state
  ```

  И класс в конец файла:

  ```python
  class MixSelfSignupTests(IsolatedAsyncioTestCase):
      """The five mix buttons: what the pick becomes on the wire, and what the clicker gets back."""

      async def test_a_chosen_role_order_reaches_the_platform_in_that_order(self) -> None:
          rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.self_update": rpc_ok(_mix_state())})
          cog = InteractionsCog(MagicMock(action_dispatcher=_dispatcher()))
          click = _interaction(ephemeral=True)
          click.type = discord.InteractionType.component
          click.data = {"custom_id": "owt:mix.roles_set:42", "values": ["tank,support"]}

          with patch.object(dispatcher_module, "request_rpc", rpc):
              await cog.on_interaction(click)

          subject, body = rpc.calls[-1]
          self.assertEqual(subject, "rpc.balancer.custom.self_update")
          self.assertEqual(body["custom_game_id"], 42)
          self.assertEqual(body["payload"], {"roles": ["tank", "support"]})

      async def test_the_all_option_asks_for_every_ranked_role(self) -> None:
          rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.self_update": rpc_ok(_mix_state())})

          with patch.object(dispatcher_module, "request_rpc", rpc):
              outcome = await _dispatcher().perform(4242, "mix.roles_set", "42", ("all",))

          self.assertEqual(outcome.status, "ok")
          self.assertEqual(rpc.calls[-1][1]["payload"], {"roles": None})

      async def test_a_value_the_bot_never_minted_is_refused_before_any_call(self) -> None:
          rpc = _Rpc({})
          dispatcher = _dispatcher()

          with patch.object(dispatcher_module, "request_rpc", rpc):
              outcome = await dispatcher.perform(4242, "mix.roles_set", "42", ("tank,healer",))

          self.assertEqual((outcome.status, outcome.code), ("failed", "bad_values"))
          self.assertEqual(rpc.calls, [])
          self.assertIn("разобрать выбор ролей", _reply_text(dispatcher.reply(outcome, "mix.roles_set", "ru")))

      async def test_the_flex_button_carries_the_value_it_sets(self) -> None:
          self.assertEqual(parse_custom_id("owt:mix.flex:42-off"), ("mix.flex", "42-off"))
          self.assertIsNone(parse_custom_id("owt:mix.flex:42"))
          rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.balancer.custom.self_update": rpc_ok(_mix_state())})

          with patch.object(dispatcher_module, "request_rpc", rpc):
              outcome = await _dispatcher().perform(4242, "mix.flex", "42-off")

          self.assertEqual(outcome.status, "ok")
          body = rpc.calls[-1][1]
          self.assertEqual((body["custom_game_id"], body["payload"]), (42, {"is_flex": False}))

      async def test_the_reply_offers_the_role_select_only_while_roles_are_editable(self) -> None:
          dispatcher = _dispatcher()

          editable = dispatcher.reply(Outcome("ok", _mix_state()), "mix.roles", "ru")

          container, selects, buttons = editable.to_components()
          (select,) = selects["components"]
          options = select["options"]
          self.assertEqual(select["custom_id"], "owt:mix.roles_set:42")
          self.assertEqual(len(options), 16)
          self.assertEqual([option["value"] for option in options if option["default"]], ["tank,support"])
          by_value = {option["value"]: option for option in options}
          self.assertEqual(by_value["tank,support"]["label"], "Танк → Саппорт")
          self.assertEqual(by_value["tank,support"]["description"], "Танк 3100 · Саппорт без ранга")
          self.assertEqual(by_value["all"]["label"], "Все роли с рангом")
          self.assertEqual(
              [button["custom_id"] for button in buttons["components"]],
              ["owt:mix.flex:42-on", "owt:mix.leave:42"],
          )
          text = container["components"][0]["content"]
          self.assertIn("Роли:** Танк → Саппорт", text)
          self.assertIn("Нет ранга: Саппорт", text)

          locked = dispatcher.reply(
              Outcome(
                  "ok",
                  _mix_state(
                      self_role_edit=False,
                      policy={
                          "can_join": False,
                          "can_leave": True,
                          "can_edit_roles": False,
                          "join_blocker": "already_joined",
                          "edit_blocker": "role_edit_off",
                      },
                  ),
              ),
              "mix.roles",
              "ru",
          )

          _container, only_row = locked.to_components()
          self.assertEqual([item["type"] for item in only_row["components"]], [2])
          self.assertIn("Танк → Саппорт", _reply_text(locked))
          self.assertIn("не разрешил игрокам менять роли", _reply_text(locked))

      async def test_a_missing_battlenet_link_is_named_and_points_at_the_profile(self) -> None:
          rpc = _Rpc(
              {
                  IDENTITY_SUBJECT: rpc_ok(IDENTITY),
                  "rpc.balancer.custom.self_join": rpc_error("forbidden", "battlenet_not_linked"),
              }
          )
          dispatcher = _dispatcher()

          with patch.object(dispatcher_module, "request_rpc", rpc):
              outcome = await dispatcher.perform(4242, "mix.join", "42")

          self.assertEqual((outcome.status, outcome.message), ("failed", "battlenet_not_linked"))
          view = dispatcher.reply(outcome, "mix.join", "ru")
          _container, row = view.to_components()
          self.assertIn("Battle.net", _reply_text(view))
          self.assertEqual([button["url"] for button in row["components"]], [f"{SITE}/?settings=profile"])

      async def test_a_closed_signup_is_worded_without_a_profile_link(self) -> None:
          rpc = _Rpc(
              {
                  IDENTITY_SUBJECT: rpc_ok(IDENTITY),
                  "rpc.balancer.custom.self_join": rpc_error("conflict", "signup_closed"),
              }
          )
          dispatcher = _dispatcher()

          with patch.object(dispatcher_module, "request_rpc", rpc):
              outcome = await dispatcher.perform(4242, "mix.join", "42")

          view = dispatcher.reply(outcome, "mix.join", "ru")
          self.assertEqual(len(view.to_components()), 1)
          self.assertIn("Запись на этот микс закрыта", _reply_text(view))
  ```

  Существующий `test_every_action_the_card_contract_allows_is_one_the_bot_answers`
  (`tests/test_interactions.py:130-131`) не трогаем: он сторожит Step 3 — пять записей в `ACTIONS`
  держат равенство только вместе с правкой `DiscordAction`, забыть одну сторону нельзя.

- [ ] **Step 2: Запустить, ожидается FAIL.**
  ```
  cd backend && uv run pytest discord-service/tests/test_interactions.py -q
  ```
  Файл собирается (`Outcome` уже экспортирован — `dispatcher.py:31`), падают ровно семь новых
  тестов:
  - `test_a_chosen_role_order_…` — `parse_custom_id` не знает `mix.roles_set`, ког отвечает
    «expired_button», RPC не было: `IndexError: list index out of range` на `rpc.calls[-1]`;
  - `test_the_all_option_…`, `test_a_value_the_bot_never_minted_…` — `KeyError: 'mix.roles_set'`
    из `ACTIONS[action_name]` в `perform`;
  - `test_the_flex_button_…` — `AssertionError: None != ('mix.flex', '42-off')`;
  - `test_the_reply_offers_the_role_select_…` — `KeyError: 'mix.roles'` из `copy.success_text`;
  - `test_a_missing_battlenet_link_…`, `test_a_closed_signup_…` — `KeyError: 'mix.join'`.

  Существующее равенство `ACTIONS`/`DiscordAction` на этом шаге ещё зелёное: обе стороны пока
  без mix-записей.

- [ ] **Step 3: Минимальная реализация.**

  **`backend/shared/schemas/events.py`**, строки 29-39:

  ```python
  #: The actions discord-service answers itself (``src/interactions/actions.py``
  #: says what each one calls). A literal rather than a string so a producer
  #: cannot put a button on a card that the bot could only answer "unknown".
  DiscordAction = Literal[
      "invite.accept",
      "invite.decline",
      "check_in",
      "registration.view",
      "notifications.menu",
      "notifications.mute",
      "mix.join",
      "mix.leave",
      "mix.roles",
      "mix.roles_set",
      "mix.flex",
  ]
  ```

  **`src/interactions/actions.py`** — импорт рядом со строкой 23:

  ```python
  from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
  from shared.services.notifications import NOTIFICATION_GROUPS
  ```

  Новые билдеры после `_everything` (после строки 47 исходного файла):

  ```python
  def _parse_roles(values: Sequence[str]) -> list[str] | None:
      """The role order a select carried; ``None`` for "every role I have a rank in".

      Discord does not keep the order the options were clicked in, so the order
      rides the value itself (``tank,support``). A value naming something that is
      not one of the three roles, or naming one twice, is not one the bot minted:
      it is refused here rather than sent on to be answered with a 422.
      """
      value = (values[0] if values else "").strip()
      if value == "all":
          return None
      roles = [item.strip().lower() for item in value.split(",") if item.strip()]
      if not roles or len(set(roles)) != len(roles) or any(role not in REGISTRATION_ROLE_CODES for role in roles):
          raise ValueError(f"not a role order this bot minted: {value!r}")
      return roles


  def _mix(target: str, values: Sequence[str]) -> dict[str, Any]:
      # ``{game_id}`` is a path parameter, which the gateway copies to the body
      # by name; the bot knows no workspace, so the mix row supplies it.
      return {"custom_game_id": int(target)}


  def _mix_roles(target: str, values: Sequence[str]) -> dict[str, Any]:
      return {"custom_game_id": int(target), "payload": {"roles": _parse_roles(values)}}


  def _mix_flex(target: str, values: Sequence[str]) -> dict[str, Any]:
      # A button carries no values, so the wanted state rides the target: ``42-on``.
      game_id, _, wanted = target.rpartition("-")
      return {"custom_game_id": int(game_id), "payload": {"is_flex": wanted == "on"}}


  def _flex_target(target: str) -> bool:
      game_id, _, wanted = target.rpartition("-")
      return wanted in ("on", "off") and game_id.isdigit()
  ```

  Записи в `ACTIONS` (после `notifications.mute`, перед закрывающей скобкой на строке 89):

  ```python
      # Self-signup for a pickup mix. The gate is the mix's own policy, so a
      # stale card button answers "signup closed" rather than doing anything.
      "mix.join": Action("rpc.balancer.custom.self_join", _mix),
      "mix.leave": Action("rpc.balancer.custom.self_leave", _mix),
      "mix.roles": Action("rpc.balancer.custom.self_get", _mix),
      "mix.roles_set": Action("rpc.balancer.custom.self_update", _mix_roles),
      "mix.flex": Action("rpc.balancer.custom.self_update", _mix_flex, accepts=_flex_target),
  ```

  **`src/interactions/copy.py`** — импорты (строки 10-14) и `__all__` (строка 16):

  ```python
  from collections.abc import Mapping
  from itertools import permutations
  from typing import Any, Literal

  import discord
  from discord.utils import escape_markdown

  from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES

  __all__ = (
      "LINK_BLOCKERS",
      "MIX_BLOCKERS",
      "Locale",
      "error_text",
      "locale_of",
      "mix_blocker_text",
      "mix_role_options",
      "mix_text",
      "registration_text",
      "settle_note",
      "success_text",
      "text",
  )
  ```

  Новые ключи в `_TEXT` (`copy.py:25-58`) — в `ru` рядом с `"mute_all"`:

  ```python
          "mute_all": "Отключить все",
          "mix_join": "Записаться",
          "mix_leave": "Выписаться",
          "mix_flex_on": "Флекс: включить",
          "mix_flex_off": "Флекс: выключить",
          "mix_roles_placeholder": "Порядок ролей",
          "open_profile": "Открыть профиль",
  ```

  и в `en`:

  ```python
          "mute_all": "Turn all off",
          "mix_join": "Join",
          "mix_leave": "Leave",
          "mix_flex_on": "Flex: turn on",
          "mix_flex_off": "Flex: turn off",
          "mix_roles_placeholder": "Role order",
          "open_profile": "Open profile",
  ```

  Новые блоки после `_CARD` (после строки 172) и перед `def text(...)`:

  ```python
  _MIX: dict[Locale, dict[str, str]] = {
      "ru": {
          "heading": "Микс «{name}»",
          "seat_pool": "Вы записаны — в пуле.",
          "seat_benched": "Вы на скамейке — хост переведёт в пул.",
          "seat_must_play": "Вы в составе — хост поставил вас играть.",
          "no_seat": "Вы не записаны на этот микс.",
          "roles": "Роли",
          "all_ranked": "все, по которым есть ранг",
          "all_ranked_option": "Все роли с рангом",
          "no_roles": "не выбраны",
          "no_rank": "без ранга",
          "flex": "Флекс",
          "flex_on": "вкл",
          "flex_off": "выкл",
          "unranked": "Нет ранга: {roles} — хост проставит",
      },
      "en": {
          "heading": "Mix “{name}”",
          "seat_pool": "You're signed up — in the pool.",
          "seat_benched": "You're on the bench — the host moves people into the pool.",
          "seat_must_play": "You're in — the host put you on the floor.",
          "no_seat": "You're not signed up for this mix.",
          "roles": "Roles",
          "all_ranked": "every role you have a rank in",
          "all_ranked_option": "Every ranked role",
          "no_roles": "none picked",
          "no_rank": "no rank",
          "flex": "Flex",
          "flex_on": "on",
          "flex_off": "off",
          "unranked": "No rank yet: {roles} — the host will fill it in",
      },
  }

  #: Why a mix refused, by the code ``mix_self_policy`` named. ``bad_values`` is
  #: the bot's own: a select value it never minted, refused before any call.
  _MIX_BLOCKERS: dict[Locale, dict[str, str]] = {
      "ru": {
          "mix_closed": "Микс уже завершён или отменён.",
          "discord_not_linked": "Этот Discord не привязан к аккаунту OWT — привяжите его в профиле.",
          "battlenet_not_linked": "К аккаунту не привязан Battle.net — привяжите его в профиле.",
          "player_not_linked": "К аккаунту не привязан игрок — привяжите Battle.net в профиле.",
          "self_join_denied": "Самозапись на миксы для вас закрыта.",
          "already_joined": "Вы уже записаны на этот микс.",
          "not_on_roster": "Вы не записаны на этот микс.",
          "signup_closed": "Запись на этот микс закрыта.",
          "roster_full": "В миксе уже 100 игроков — свободных мест нет.",
          "role_edit_off": "Хост не разрешил игрокам менять роли.",
          "bad_values": "Не удалось разобрать выбор ролей — откройте микс ещё раз.",
      },
      "en": {
          "mix_closed": "This mix is already finished or cancelled.",
          "discord_not_linked": "This Discord account isn't linked to an OWT account — link it in your profile.",
          "battlenet_not_linked": "No Battle.net account is linked to yours — link it in your profile.",
          "player_not_linked": "No player is linked to your account — link Battle.net in your profile.",
          "self_join_denied": "Signing yourself up for mixes is turned off for you.",
          "already_joined": "You're already signed up for this mix.",
          "not_on_roster": "You're not signed up for this mix.",
          "signup_closed": "Sign-up for this mix is closed.",
          "roster_full": "This mix already has 100 players — no seats left.",
          "role_edit_off": "The host hasn't let players change their roles.",
          "bad_values": "Couldn't read that role pick — open the mix again.",
      },
  }

  #: Every refusal the bot words itself; anything else is the service's message.
  MIX_BLOCKERS: frozenset[str] = frozenset(_MIX_BLOCKERS["ru"])
  #: The refusals a profile link can actually fix.
  LINK_BLOCKERS: frozenset[str] = frozenset({"discord_not_linked", "battlenet_not_linked", "player_not_linked"})

  #: Every ordered, non-empty pick of the three roles: 3 + 6 + 6 = 15, and with
  #: "every ranked role" that is 16 options against Discord's limit of 25.
  #: Discord does not report the order options were clicked in, so the order is
  #: the option.
  ROLE_ORDERS: tuple[tuple[str, ...], ...] = tuple(
      order
      for size in range(1, len(REGISTRATION_ROLE_CODES) + 1)
      for order in permutations(REGISTRATION_ROLE_CODES, size)
  )
  ```

  И функции в конец файла (после `registration_text`):

  ```python
  def mix_blocker_text(locale: Locale, code: str) -> str:
      return _MIX_BLOCKERS[locale][code]


  def mix_text(locale: Locale, state: Mapping[str, Any]) -> str:
      """The caller's own seat in a mix (the ``self_*`` answer) as a short card."""
      words = _MIX[locale]
      lines = [f"### {words['heading'].format(name=escape_markdown(str(state.get('name') or '')))}"]
      seat = state.get("seat")
      if not isinstance(seat, Mapping):
          lines.append(words["no_seat"])
      else:
          participation = str(seat.get("participation") or "pool")
          lines.append(words.get(f"seat_{participation}", words["seat_pool"]))
          roles = seat.get("roles")
          if roles is None:
              order = words["all_ranked"]
          elif not roles:
              order = words["no_roles"]
          else:
              order = " → ".join(_role(locale, role) for role in roles)
          lines.append(f"**{words['roles']}:** {order}")
          lines.append(f"**{words['flex']}:** {words['flex_on'] if seat.get('is_flex') else words['flex_off']}")

      unranked = [role for role in state.get("unranked_roles") or []]
      if unranked:
          named = ", ".join(_role(locale, role) for role in unranked)
          lines.append("-# " + words["unranked"].format(roles=named))

      policy = state.get("policy")
      blocker = policy.get("edit_blocker") if isinstance(policy, Mapping) else None
      if blocker == "role_edit_off":
          lines.append("-# " + _MIX_BLOCKERS[locale]["role_edit_off"])
      return "\n".join(lines)


  def mix_role_options(locale: Locale, state: Mapping[str, Any]) -> list[discord.SelectOption]:
      """The role select: every order, captioned with the host's ranks, current one marked."""
      words = _MIX[locale]
      seat = state.get("seat")
      seat = seat if isinstance(seat, Mapping) else {}
      raw_ranks = seat.get("ranks")
      ranks: Mapping[str, Any] = raw_ranks if isinstance(raw_ranks, Mapping) else {}
      chosen = seat.get("roles")
      current = ",".join(str(role) for role in chosen) if isinstance(chosen, list) else "all"

      options: list[discord.SelectOption] = []
      for order in ROLE_ORDERS:
          value = ",".join(order)
          options.append(
              discord.SelectOption(
                  label=" → ".join(_role(locale, role) for role in order),
                  value=value,
                  description=" · ".join(
                      f"{_role(locale, role)} {ranks[role] if ranks.get(role) is not None else words['no_rank']}"
                      for role in order
                  ),
                  default=value == current,
              )
          )
      options.append(
          discord.SelectOption(label=words["all_ranked_option"], value="all", default=current == "all")
      )
      return options
  ```

  **`src/interactions/dispatcher.py`** — модульный хелпер рядом с `_refusal_code`
  (после строки 63):

  ```python
  #: Every action of the pickup-mix self-signup; their replies are the seat, not a sentence.
  _MIX_PREFIX = "mix."


  def _mix_blocker(outcome: Outcome) -> str | None:
      """The mix refusal behind an envelope, or ``None`` for anything else.

      ``self_*`` raise ``HTTPException(detail="<code>")`` with a bare string, and
      ``shared.rpc.common.http_error`` puts a string detail in the envelope's
      human ``message`` -- so the code arrives there while ``code`` is only the
      status it was raised with. Both are read, so moving the code into
      ``details["fields"]`` later would still land here.
      """
      for candidate in (outcome.code, outcome.message):
          code = (candidate or "").strip()
          if code in copy.MIX_BLOCKERS:
              return code
      return None
  ```

  `reply` (строки 121-147) — две новые ветки:

  ```python
      def reply(self, outcome: Outcome, action_name: str, locale: copy.Locale) -> discord.ui.LayoutView:
          """What the clicker alone sees."""
          if outcome.status == "ok":
              if action_name == "notifications.menu":
                  mute_all = DiscordActionButton(
                      label=copy.text(locale, "mute_all"), action="notifications.mute", target="all", style="danger"
                  )
                  return self._card(_AMBER, copy.text(locale, "mute_prompt"), mute_all, self._settings_link(locale))
              if action_name == "notifications.mute":
                  return self._card(_GREEN, copy.success_text(locale, action_name), self._settings_link(locale))
              if action_name == "registration.view":
                  if not isinstance(outcome.data, Mapping):
                      return self._card(_AMBER, copy.text(locale, "not_registered"))
                  return self._card(_BLUE, copy.registration_text(locale, outcome.data))
              if action_name.startswith(_MIX_PREFIX):
                  return self._mix_card(outcome.data, locale)
              return self._card(_GREEN, copy.success_text(locale, action_name))
          if outcome.status == "not_linked":
              link = DiscordLinkButton(label=copy.text(locale, "link_discord"), url=f"{self._site}/?settings=profile")
              return self._card(_AMBER, copy.text(locale, "not_linked"), link)
          if outcome.status == "inactive":
              return self._card(_RED, copy.text(locale, "inactive"))
          if outcome.status == "unavailable":
              return self._card(_AMBER, copy.text(locale, "unavailable"))
          blocker = _mix_blocker(outcome) if action_name.startswith(_MIX_PREFIX) else None
          if blocker is not None:
              fix = (
                  [DiscordLinkButton(label=copy.text(locale, "open_profile"), url=f"{self._site}/?settings=profile")]
                  if blocker in copy.LINK_BLOCKERS
                  else []
              )
              return self._card(_AMBER, copy.mix_blocker_text(locale, blocker), *fix)
          # Both self-service tournament reads answer a plain 404 when the caller
          # has no registration there; that is the one "no" worth rewording.
          if outcome.code == "not_found" and action_name in ("check_in", "registration.view"):
              return self._card(_AMBER, copy.text(locale, "not_registered"))
          return self._card(_RED, copy.error_text(locale, outcome.code, outcome.message))
  ```

  И новый метод рядом с `_card` (после строки 156):

  ```python
      def _mix_card(self, state: Any, locale: copy.Locale) -> discord.ui.LayoutView:
          """The clicker's seat in a mix, with exactly the controls the policy allows.

          Every ``mix.*`` action answers with the same self-state, so one renderer
          serves the card button, the select and the flex toggle alike -- and the
          reply a click produces is the reply the next click is made from.
          """
          if not isinstance(state, Mapping):
              return self._card(_AMBER, copy.text(locale, "unavailable"))
          raw_policy = state.get("policy")
          policy: Mapping[str, Any] = raw_policy if isinstance(raw_policy, Mapping) else {}
          raw_seat = state.get("seat")
          seat: Mapping[str, Any] | None = raw_seat if isinstance(raw_seat, Mapping) else None
          target = str(state.get("custom_game_id"))

          buttons: list[DiscordButton] = []
          extra: list[discord.ui.ActionRow] = []
          if policy.get("can_edit_roles"):
              flex_on = bool(seat and seat.get("is_flex"))
              buttons.append(
                  DiscordActionButton(
                      label=copy.text(locale, "mix_flex_off" if flex_on else "mix_flex_on"),
                      action="mix.flex",
                      target=f"{target}-{'off' if flex_on else 'on'}",
                  )
              )
              extra.append(
                  select_row(
                      action="mix.roles_set",
                      target=target,
                      placeholder=copy.text(locale, "mix_roles_placeholder"),
                      options=copy.mix_role_options(locale, state),
                  )
              )
          if policy.get("can_join"):
              buttons.append(
                  DiscordActionButton(
                      label=copy.text(locale, "mix_join"), action="mix.join", target=target, style="success"
                  )
              )
          if policy.get("can_leave"):
              buttons.append(
                  DiscordActionButton(
                      label=copy.text(locale, "mix_leave"), action="mix.leave", target=target, style="danger"
                  )
              )
          card = DiscordCard(
              accent_color=_GREEN if seat else _BLUE,
              text=copy.mix_text(locale, state),
              rows=[buttons] if buttons else [],
          )
          return card_view(card, extra_rows=extra)
  ```

- [ ] **Step 4: Запустить, ожидается PASS.**
  ```
  cd backend && uv run pytest discord-service/tests/test_interactions.py -q
  ```
  Зелёные все 20 тестов файла (12 прежних + 1 из A6a + 7 новых), включая
  `test_every_action_the_card_contract_allows_is_one_the_bot_answers` (11 записей в `ACTIONS`
  против 11 значений `DiscordAction`) и прежние турнирные тесты.

  Плюс сосед, который рендерит карточку через тот же `card_view`
  (`tests/test_gateway_send_dm.py:137-166`):
  ```
  cd backend && uv run pytest discord-service/tests/test_gateway_send_dm.py -q
  ```
  Зелёный: у `card_view` изменилась только keyword-only часть сигнатуры.

- [ ] **Step 5: Коммит.**
  ```
  git add backend/shared/schemas/events.py backend/discord-service/src/interactions/actions.py backend/discord-service/src/interactions/copy.py backend/discord-service/src/interactions/dispatcher.py backend/discord-service/tests/test_interactions.py
  git commit -m "feat(discord): mix self-signup buttons and the role select"
  ```

---

### Task A6c: таблица действий в README

Механическая правка документации: тестов нет, поведение не меняется.

**Files:** Modify `backend/discord-service/README.md` (97-98, 105-111)

**Interfaces:** Consumes `ACTIONS` из A6b; ничего не производит.

- [ ] **Step 1: Правка.** Строки 97-98 — перечисление действий в пункте 3 списка заменить ссылкой
  на таблицу:

  ```markdown
  3. the action's own RPC with that identity (`src/interactions/actions.py` is the whole, fixed
     list — see the table below);
  ```

  Строки 105-111 (абзац про `🔕` и абзац про кэш) — вставить между ними таблицу и абзац про микс:

  ```markdown
  The DM card carries only a small `🔕` (`notifications.menu`, answered by the bot alone): it opens,
  for the reader alone, a prompt with «turn all off» (`notifications.mute:all` — every DM group false;
  in-app notifications stay) and a notification-settings link. Discord allows ephemeral messages only
  as an answer to a click, hence the trigger rather than a separate DM.

  | Action | RPC | Where the component lives |
  |---|---|---|
  | `invite.accept` / `invite.decline` | `rpc.tournament.regteam_accept` / `…regteam_decline` | team-invite DM card |
  | `check_in` | `rpc.tournament.reg_pub_check_in` | tournament DM card |
  | `registration.view` | `rpc.tournament.reg_pub_get_me` | tournament DM card |
  | `notifications.menu` | — (the bot alone) | every DM card |
  | `notifications.mute` | `rpc.app.notification_preferences_update` | the prompt `notifications.menu` opens |
  | `mix.join` | `rpc.balancer.custom.self_join` | mix sign-up post, ephemeral reply |
  | `mix.leave` | `rpc.balancer.custom.self_leave` | mix sign-up post, ephemeral reply |
  | `mix.roles` | `rpc.balancer.custom.self_get` | mix sign-up post |
  | `mix.roles_set` | `rpc.balancer.custom.self_update` | role select on the ephemeral reply |
  | `mix.flex` | `rpc.balancer.custom.self_update` | flex toggle on the ephemeral reply |

  **Mix self-signup.** A host opens sign-up for a pickup mix and balancer-service posts one card into
  the mix channel with «Join» / «My roles» / «Leave». Every `mix.*` action answers with the same
  self-state, rendered by `copy.mix_text` into an ephemeral reply that carries the controls the mix's
  policy allows: a role select, a flex toggle, and join/leave. That reply is where the next click
  happens, and it is replaced in place. The select is the only non-button component the bot sends —
  it is built by `cards.select_row` for these replies alone and is not part of the `DiscordCard`
  contract, so a publisher cannot ask for one. Its value carries the *order* (`tank,support`, or
  `all` for «every ranked role»), because Discord does not report the order options were clicked in;
  a value naming anything but the three roles is refused before any platform call. `mix.flex` carries
  the state it sets in its target (`42-on` / `42-off`). Refusals are worded from the mix's own
  blocker codes (`signup_closed`, `roster_full`, `role_edit_off`, …); the three link blockers
  (`discord_not_linked`, `battlenet_not_linked`, `player_not_linked`) add a profile link.

  No identity is cached, so an unlink or a deactivation bites on the next click. Every click logs one
  line with `action`, `target`, `status` and `code`.
  ```

- [ ] **Step 2: Коммит.**
  ```
  git add backend/discord-service/README.md
  git commit -m "docs(discord): document the mix self-signup actions"
  ```

---

### Task A7: `post_signup` — карточка записи в Discord

Зависимость: A6 добавляет `mix.join`/`mix.roles`/`mix.leave` в `DiscordAction`
(`backend/shared/schemas/events.py:32-39`). Без них `DiscordActionButton(action="mix.join", …)` не пройдёт валидацию
Literal — эту таску мержить после A6.

**Files:**
- Modify: `backend/balancer-service/src/core/config.py` (после 38), `docker-compose.production.yml` (после 376),
  `backend/balancer-service/src/domain/mix_discord.py` (1-29 docstring/`__all__`, хвост),
  `backend/balancer-service/src/services/custom_game.py` (после `set_self_service`),
  `backend/balancer-service/src/schemas/custom_game.py` (`__all__` + хвост),
  `backend/balancer-service/src/rpc/custom.py` (после `_post_discord`, 674),
  `gateway/internal/balancer/routes.go` (после блока `/me`), `backend/balancer-service/src/openapi_schemas.py`,
  `backend/balancer-service/src/openapi_docs.py`, `gateway/internal/openapi/schemas.json` (регенерация)
- Test: `backend/balancer-service/tests/test_mix_discord.py` (хвост),
  `backend/balancer-service/tests/test_custom_game.py` (после self-тестов A4),
  `gateway/internal/balancer/routes_test.go` (`TestMixSelfServiceRoutes`)

**Interfaces:**
- Produces: `Settings.public_site_url: str`;
  `signup_card(*, mix_name: str, host_name: str | None, board_url: str, custom_game_id: int) -> DiscordCard`;
  `CustomGameService.signup_post(session, *, workspace_id, custom_game_id, self_signup: str, actor_user_id, actor_is_superuser=False, board_url_base: str) -> tuple[int, DiscordCard]`;
  `CustomGamePostSignup{self_signup: Literal["pool","benched"]}`; subject `rpc.balancer.custom.post_signup`;
  route `POST …/custom-games/{game_id}/discord/signup`
- Consumes: `DiscordCard`, `DiscordActionButton`, `DiscordLinkButton`, `DiscordCommandEvent`
  (`backend/shared/schemas/events.py:42-159`), `DISCORD_COMMANDS_QUEUE`, `publish_message`,
  `CustomGameService.workspace_discord_channel_id` (`src/services/custom_game.py:896`),
  `DiscordAction` членов `mix.join`/`mix.roles`/`mix.leave` (A6)

- [ ] **Step 1: Write the failing test**

`backend/balancer-service/tests/test_mix_discord.py` — импорт и тесты в конец:

```python
from src.domain.mix_discord import signup_card  # noqa: E402
```

```python
def test_signup_card_names_the_mix_and_its_host() -> None:
    card = signup_card(
        mix_name="Friday Scrim", host_name="Foxx", board_url="https://owt.example/balancer/mix/42", custom_game_id=42
    )
    assert "Friday Scrim" in card.text
    assert "Foxx" in card.text
    assert "Discord" in (card.details or "") and "Battle.net" in (card.details or "")


def test_signup_card_escapes_a_mix_name_written_as_markdown() -> None:
    """Mix names are user input and the card is Discord markdown: an unescaped
    name reformats (or breaks) the whole post."""
    card = signup_card(
        mix_name="**Friday** _mix_", host_name=None, board_url="https://owt.example/balancer/mix/42", custom_game_id=42
    )
    assert "**Friday**" not in card.text
    assert r"\*\*Friday\*\*" in card.text


def test_signup_card_carries_the_three_actions_and_the_board_link() -> None:
    card = signup_card(
        mix_name="Friday Scrim", host_name="Foxx", board_url="https://owt.example/balancer/mix/42", custom_game_id=42
    )
    assert [button.action for button in card.answers] == ["mix.join", "mix.roles", "mix.leave"]
    assert {button.target for button in card.answers} == {"42"}
    assert [button.style for button in card.answers] == ["success", "secondary", "danger"]
    [[link]] = card.rows
    assert link.url == "https://owt.example/balancer/mix/42"


def test_signup_card_survives_a_mix_name_at_the_length_cap() -> None:
    """DiscordCard refuses past 4000 characters, and escaping can double a
    name's length -- a 255-character mix name must still produce a card."""
    card = signup_card(
        mix_name="*" * 255, host_name="Foxx", board_url="https://owt.example/balancer/mix/42", custom_game_id=42
    )
    assert len(card.text) < 4000
```

`backend/balancer-service/tests/test_custom_game.py` — после self-тестов A4:

```python
    async def test_signup_post_opens_the_window_and_builds_the_card(self) -> None:
        game = _game(name="Friday mix")
        self.games.get.return_value = game
        self.session.scalar = AsyncMock(return_value={"mix_discord_channel_id": "555"})
        self.load_hosts.return_value = {9: "Foxx"}

        channel_id, card = await self.service.signup_post(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            self_signup="benched",
            actor_user_id=9,
            board_url_base="https://owt.example",
        )

        self.assertEqual(channel_id, 555)
        self.assertEqual(game.self_signup, "benched")
        self.assertIn("Friday mix", card.text)
        [[link]] = card.rows
        self.assertEqual(link.url, "https://owt.example/balancer/mix/11")

    async def test_signup_post_without_a_workspace_channel_409(self) -> None:
        """Same refusal as posting a lineup: there is nowhere to post to."""
        game = _game()
        self.games.get.return_value = game
        self.session.scalar = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.signup_post(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                self_signup="pool",
                actor_user_id=9,
                board_url_base="https://owt.example",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Discord channel not configured")
        self.assertEqual(game.self_signup, "closed")

    async def test_signup_post_requires_the_host_403(self) -> None:
        self.games.get.return_value = _game()

        with self.assertRaises(HTTPException) as ctx:
            await self.service.signup_post(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                self_signup="pool",
                actor_user_id=8,
                board_url_base="https://owt.example",
            )
        self.assertEqual(ctx.exception.status_code, 403)
```

`gateway/internal/balancer/routes_test.go` — в `want` внутри `TestMixSelfServiceRoutes` добавить строку:

```go
		"POST /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/discord/signup": "rpc.balancer.custom.post_signup",
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd backend && uv run pytest balancer-service/tests/test_mix_discord.py balancer-service/tests/test_custom_game.py -q
cd ../gateway && go test ./internal/balancer/...
```

FAIL: `ImportError: cannot import name 'signup_card'`; `AttributeError: 'CustomGameService' object has no attribute 'signup_post'`;
Go: `missing mix self-service routes: map[POST .../discord/signup:...]`.

- [ ] **Step 3: Minimal implementation**

`backend/balancer-service/src/core/config.py` — после строки 38 (`access_token_service`):

```python
    # Absolute base of the public site, used to build the board link a mix's
    # Discord signup card carries (``PUBLIC_SITE_URL``, the same value
    # app-service and discord-service read). Platform zone only: a workspace's
    # own subdomain or custom domain is out of scope for this link.
    public_site_url: str = "http://localhost:3000"
```

`docker-compose.production.yml` — в `balancer-svc.environment`, после строки 376 (`AUTH_SERVICE_URL`):

```yaml
      # Same root value the frontend builds NEXT_PUBLIC_SITE_URL from: the mix
      # signup card's board button must land on the site people actually use.
      - PUBLIC_SITE_URL=${SITE_URL:-https://owt.craazzzyyfoxx.me}
```

(dev `docker-compose.yml` не трогаем — `balancer-svc` уже читает `backend/env/common.env`.)

`backend/balancer-service/src/domain/mix_discord.py` — дополнить `__all__` и добавить в конец файла:

```python
__all__ = ("build_lineup_embed", "signup_card")
```

```python
#: Everything Discord markdown gives a meaning to; a backslash before ASCII
#: punctuation is always consumed, so over-escaping is invisible to the reader.
#: Same rule app-service renders notification cards with.
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]<#-])")


def _escape(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def signup_card(*, mix_name: str, host_name: str | None, board_url: str, custom_game_id: int) -> DiscordCard:
    """The channel post that opens a mix for self-signup.

    Static by design: the bot does not edit channel posts, so a live counter of
    who signed up would need a stored ``message_id`` and an ``edit_message``
    path. The buttons therefore carry no state at all -- only the mix id -- and
    every answer is re-derived from the database at click time, which is also why
    a card outlives its mix gracefully (a closed mix answers ``mix_closed``).

    Russian, like every other channel-wide post: a channel has no per-reader
    locale, unlike the ephemeral replies the bot renders per user.
    """
    host = _escape(host_name) if host_name else "—"
    target = str(custom_game_id)
    return DiscordCard(
        accent_color=_COLOR,
        text=f"**Запись на микс «{_escape(mix_name)}»** · хост {host}",
        details="Нужны привязанные к аккаунту Discord и Battle.net.",
        answers=[
            DiscordActionButton(label="Записаться", action="mix.join", target=target, style="success"),
            DiscordActionButton(label="Мои роли", action="mix.roles", target=target),
            DiscordActionButton(label="Выписаться", action="mix.leave", target=target, style="danger"),
        ],
        rows=[[DiscordLinkButton(label="Доска микса", url=board_url)]],
    )
```

с импортами вверху модуля:

```python
import re

from shared.schemas.events import DiscordActionButton, DiscordCard, DiscordLinkButton
```

`backend/balancer-service/src/services/custom_game.py` — после `set_self_service`:

```python
    async def signup_post(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        self_signup: str,
        actor_user_id: int,
        actor_is_superuser: bool = False,
        board_url_base: str,
    ) -> tuple[int, DiscordCard]:
        """Open signup and build the card that announces it.

        The mode is written HERE rather than left to a separate call: a card in
        the channel whose buttons answer ``signup_closed`` is the one outcome
        nobody wants, and the column -- not the card -- is what admits a player.

        Publishing is the RPC layer's job (that is where the broker is), so this
        returns the channel and the payload, exactly like :meth:`discord_lineup`.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        # Resolved before the write: posting nowhere and silently opening signup
        # would leave the host believing the channel has a card.
        channel_id = await self.workspace_discord_channel_id(session, workspace_id)
        if channel_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Discord channel not configured")
        try:
            game.self_signup = MixSelfSignup(self_signup).value
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid self_signup"
            ) from exc
        host_names = await self.hosts(session, workspace_id, [game.host_user_id])
        card = signup_card(
            mix_name=game.name,
            host_name=host_names.get(game.host_user_id),
            board_url=f"{board_url_base.rstrip('/')}/balancer/mix/{game.id}",
            custom_game_id=game.id,
        )
        await session.flush()
        return channel_id, card
```

с импортами:

```python
from shared.schemas.events import DiscordCard
from src.domain.mix_discord import build_lineup_embed, signup_card
```

`backend/balancer-service/src/schemas/custom_game.py` — `__all__` += `"CustomGamePostSignup"`, и в конец:

```python
class CustomGamePostSignup(_Request):
    """Which signup mode the posted card opens. ``closed`` is not a choice here:
    posting a card that refuses every click is never the intent."""

    self_signup: Literal["pool", "benched"]
```

`backend/balancer-service/src/rpc/custom.py` — после `_post_discord` (строка 674):

```python
    @broker.subscriber("rpc.balancer.custom.post_signup")
    async def _post_signup(data: dict, msg: RabbitMessage) -> dict:
        """Open signup and post the card that announces it, in one click."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGamePostSignup, data)
            channel_id, card = await custom_game_service.signup_post(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                self_signup=body.self_signup,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
                board_url_base=config.public_site_url,
            )
            event = DiscordCommandEvent(action="post_message", channel_id=channel_id, card=card)
            await publish_message(broker, event.model_dump(), DISCORD_COMMANDS_QUEUE, logger=logger)
            # The signup mode is a fact about the mix, so the board refreshes;
            # delivery of the card itself is the bot's problem.
            await emit_pickup_mix_updated(session, workspace_id, change="member", actor_user_id=user.id)
            await session.commit()
            return {"status": "queued", "channel_id": str(channel_id)}

        return await c.envelope(logger, "custom.post_signup", op, session_factory=_SF)
```

с импортом конфига вверху модуля:

```python
from src.core.config import config
```

`gateway/internal/balancer/routes.go` — после блока `/me` из A5:

```go
	// One click: open signup AND post the card that announces it. A separate
	// "open" write would let a host post a card whose buttons refuse everybody.
	{Method: "POST", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/discord/signup", Queue: "rpc.balancer.custom.post_signup", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
```

`backend/balancer-service/src/openapi_schemas.py` — рядом с `post_discord` (строка 121):

```python
    "rpc.balancer.custom.post_signup": Op(request=custom_game.CustomGamePostSignup),
```

`backend/balancer-service/src/openapi_docs.py` — после блока `post_discord` (строка 337):

```python
    "rpc.balancer.custom.post_signup": {
        "summary": "Open custom game signup in Discord",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Opens self-signup in the given mode (into the pool or onto the bench) and queues a card "
            "with Join / My roles / Leave buttons to the workspace-wide mix channel. The card is "
            "static: every click re-reads the mix, so it refuses correctly once signup closes or the "
            "mix ends. 409 when the workspace has no mix channel configured."
        ),
    },
```

- [ ] **Step 4: Run, expected PASS**

```
cd backend
uv run pytest balancer-service/tests/test_mix_discord.py balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_contract.py -q
bash scripts/export_openapi_schemas.sh
uv run python scripts/check_rpc_docs.py
cd ../gateway && go test ./internal/balancer/...
```

- [ ] **Step 5: Commit**

```
git add backend/balancer-service/src/core/config.py backend/balancer-service/src/domain/mix_discord.py backend/balancer-service/src/services/custom_game.py backend/balancer-service/src/schemas/custom_game.py backend/balancer-service/src/rpc/custom.py backend/balancer-service/src/openapi_schemas.py backend/balancer-service/src/openapi_docs.py backend/balancer-service/tests/test_mix_discord.py backend/balancer-service/tests/test_custom_game.py gateway/internal/balancer/routes.go gateway/internal/balancer/routes_test.go gateway/internal/openapi/schemas.json docker-compose.production.yml
git commit -m "feat(mix): post a Discord signup card that opens the mix"
```

---

### Task A8: Сервисный слой самозаписи (типы, функции, ключ `me`)

**Files:**
- Modify: `frontend/src/services/custom-game.service.ts` (импорты `:1-3`; типы — вставка после `:172`;
  `CustomGame` `:100-139`; `customGameKeys` `:235-244`; тело `customGameService` — вставка перед `:504`)
- Test: `frontend/src/app/balancer/mix/pickup-self.contract.test.ts` (новый)

**Interfaces:**
- Consumes: `apiFetch(path, {method, body, query})` (`frontend/src/lib/api/fetch.ts:219`);
  `RoleCode` (`frontend/src/lib/roster/roles.ts:12`); wire-контракт `self_*` от backend-задачи A1–A5, A7.
- Produces:
  - `export type MixSelfSignup = "closed" | "pool" | "benched"`
  - `export type MixSelfBlocker` (10 кодов)
  - `export type MixSelfSeat = { participation: MixParticipation; roles: string[] | null; is_flex: boolean; ranks: Record<string, number | null> }`
  - `export type MixSelfPolicy = { can_join: boolean; can_leave: boolean; can_edit_roles: boolean; join_blocker: MixSelfBlocker | null; edit_blocker: MixSelfBlocker | null }`
  - `export type MixSelfState = { custom_game_id: number; name: string; status: CustomGameStatus; self_signup: MixSelfSignup; self_role_edit: boolean; seat: MixSelfSeat | null; unranked_roles: string[]; policy: MixSelfPolicy }`
  - `CustomGame.self_signup: MixSelfSignup`, `CustomGame.self_role_edit: boolean`
  - `customGameKeys.me(workspaceId: number, gameId: number)`
  - `customGameService.getMySeat/joinMix/leaveMix/updateMySeat/setSelfService/postSignup`

- [ ] **Step 1: Write the failing test** — `frontend/src/app/balancer/mix/pickup-self.contract.test.ts`

```ts
import { describe, expect, it } from "vitest";

import { RESOURCE_QUERY_KEYS } from "@/lib/realtime/resources";
import { customGameKeys } from "@/services/custom-game.service";

/**
 * The seat panel is refreshed by somebody ELSE's write -- another player
 * joining, the host benching them -- and it gets that for free only while its
 * query key stays UNDER the key `workspace.pickup_mix` drops
 * (`lib/realtime/resources.ts`). A key of its own (`["custom-game-me", …]`)
 * type-checks, renders and then silently stops updating until a reload, which
 * is exactly the failure a pickup board must not have.
 */
describe("the caller's own seat", () => {
  it("is dropped by the mix realtime resource", () => {
    const dropped = RESOURCE_QUERY_KEYS["workspace.pickup_mix"](7, {});
    const me = customGameKeys.me(7, 12);

    expect(
      dropped.some((key) => key.length <= me.length && key.every((part, index) => part === me[index])),
    ).toBe(true);
  });

  it("separates two mixes in the same workspace", () => {
    expect(customGameKeys.me(7, 12)).not.toEqual(customGameKeys.me(7, 13));
  });
});
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd frontend && bunx vitest run src/app/balancer/mix/pickup-self.contract.test.ts
```

Ожидаемо: `TypeError: customGameKeys.me is not a function` в обоих тестах.

- [ ] **Step 3: Minimal implementation**

3.1. `frontend/src/services/custom-game.service.ts`, шапка файла — заменить `:1-3`:

```ts
import { apiFetch } from "@/lib/api/fetch";
import { blobToBase64 } from "@/lib/image-capture";
import type { RoleCode } from "@/lib/roster/roles";
import type { RosterShape } from "@/lib/roster/shape";
```

3.2. Новые типы — вставить сразу после блока `CustomGamePlayerPatch` (`:167-172`), перед
`/** One row of a whole-lineup participation write. */`:

```ts
/**
 * Whether players may sign themselves up, and where they land when they do --
 * one column with exactly three states (`custom_game.self_signup`), so
 * "closed but benched" cannot be expressed at all.
 */
export type MixSelfSignup = "closed" | "pool" | "benched";

/**
 * Why a self-action is refused, exactly as `mix_self_policy` names it. The wire
 * carries the code, never a sentence: the site renders it per locale
 * (`mixes.self.blocker.*`) and the bot renders the same code its own way.
 */
export type MixSelfBlocker =
  | "mix_closed"
  | "discord_not_linked"
  | "battlenet_not_linked"
  | "player_not_linked"
  | "self_join_denied"
  | "already_joined"
  | "not_on_roster"
  | "signup_closed"
  | "roster_full"
  | "role_edit_off";

/** The caller's own roster row, or `null` when they are not in the lineup. */
export type MixSelfSeat = {
  participation: MixParticipation;
  /** `null` is the `all_ranked` mode -- every role this player has a rank for. */
  roles: string[] | null;
  is_flex: boolean;
  /** Effective rank per role; `null` where no layer answers for it. */
  ranks: Record<string, number | null>;
};

/** What the caller may do, and the first reason they may not. */
export type MixSelfPolicy = {
  can_join: boolean;
  can_leave: boolean;
  can_edit_roles: boolean;
  /** `null` exactly when `can_join`. */
  join_blocker: MixSelfBlocker | null;
  /** `null` exactly when `can_edit_roles`. */
  edit_blocker: MixSelfBlocker | null;
};

/**
 * The whole self surface of one mix in a single read (`GET …/me`).
 *
 * Kept apart from `CustomGame` on purpose: the mix board is public and its
 * detail is the same document for every viewer, while this answer is about the
 * caller -- their seat, their missing account links, their permission.
 */
export type MixSelfState = {
  custom_game_id: number;
  name: string;
  status: CustomGameStatus;
  self_signup: MixSelfSignup;
  self_role_edit: boolean;
  seat: MixSelfSeat | null;
  /** Roles this player would play that no rank layer answers for. */
  unranked_roles: string[];
  policy: MixSelfPolicy;
};
```

3.3. `CustomGame` — вставить после `matches_count` / `last_match_at` (`:134-137`), перед `players?:` (`:138`):

```ts
  /** Whether players may sign themselves up, and where a signup lands. */
  self_signup: MixSelfSignup;
  /** Whether a player on the roster may reorder their own roles and flex. */
  self_role_edit: boolean;
```

3.4. `customGameKeys` — вставить после `rotation` (`:241`), перед `stats` (`:242`):

```ts
  /**
   * The caller's own seat in one mix. Deliberately under `all`: the realtime
   * `workspace.pickup_mix` resource drops `customGameKeys.all(workspaceId)`
   * (`lib/realtime/resources.ts`), so another player's join refreshes this
   * read with no subscription of its own.
   */
  me: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "me"] as const,
```

3.5. Функции — вставить в `customGameService` после `postToDiscord` (`:503`), перед закрывающей `};` (`:504`):

```ts

  /** The caller's own standing in this mix: seat, blockers, what they may do. */
  getMySeat(workspaceId: number, gameId: number): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`).then((r) =>
      r.json(),
    );
  },

  /**
   * Signs the caller up. Idempotent: a caller already on the roster gets their
   * current state back rather than an error, so a second press never moves a
   * host's bench decision back into the pool.
   */
  joinMix(workspaceId: number, gameId: number): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, {
      method: "POST",
    }).then((r) => r.json());
  },

  /** Takes the caller out of the lineup. Allowed with no linked accounts at all. */
  leaveMix(workspaceId: number, gameId: number): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, {
      method: "DELETE",
    }).then((r) => r.json());
  },

  /**
   * The two fields a player owns on their own row. Same patch semantics as the
   * host's `updatePlayer` -- an omitted key is untouched, `roles: null` is the
   * `all_ranked` mode -- against a narrower server-side allow-list: anything
   * else (participation, ranks) is a 422.
   */
  updateMySeat(
    workspaceId: number,
    gameId: number,
    patch: { roles?: RoleCode[] | null; is_flex?: boolean },
  ): Promise<MixSelfState> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/me`, {
      method: "PATCH",
      body: patch,
    }).then((r) => r.json());
  },

  /** The host's two switches: who may sign up, and whether they may edit roles. */
  setSelfService(
    workspaceId: number,
    gameId: number,
    patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean },
  ): Promise<CustomGame> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/self-service`,
      { method: "PUT", body: patch },
    ).then((r) => r.json());
  },

  /**
   * Opens signup in the requested mode and queues the signup card for the
   * workspace's mix channel. Fire-and-forget like `postToDiscord`: the response
   * only says the message reached the bot's queue.
   */
  postSignup(
    workspaceId: number,
    gameId: number,
    selfSignup: "pool" | "benched",
  ): Promise<{ status: "queued"; channel_id: string }> {
    return apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/signup`,
      { method: "POST", body: { self_signup: selfSignup } },
    ).then((r) => r.json());
  },
```

- [ ] **Step 4: Run, expected PASS**

```
cd frontend && bunx vitest run src/app/balancer/mix/pickup-self.contract.test.ts
```

Ожидаемо: `2 passed`.

- [ ] **Step 5: Commit**

```
git add frontend/src/services/custom-game.service.ts frontend/src/app/balancer/mix/pickup-self.contract.test.ts
git commit -m "feat(mix): self-signup reads and writes in the mix service"
```

---

### Task A9: Контролы самозаписи у хоста в `PickupMixHeader`

**Files:**
- Modify: `frontend/src/app/balancer/mix/PickupMixHeader.tsx` (импорты `:1-12`, props `:14-26`,
  сигнатура `:46-55`, тело — вставка перед закрывающим `</div>` `:139`)
- Modify: `frontend/src/i18n/messages/en.json` (вставка после `:6182`, внутри `"mixes"`)
- Modify: `frontend/src/i18n/messages/ru.json` (вставка после `:6182`, внутри `"mixes"`)
- Test: `frontend/src/app/balancer/mix/PickupMixHeader.behavior.test.tsx` (фикстура `:31-48`, `mount` `:58-81`,
  новый `describe` в конец файла)
- Test: `frontend/src/i18n/messages.parity.test.ts` (новый `it` в `describe("interpolated message keys")`)

**Interfaces:**
- Consumes: `MixSelfSignup`, `CustomGame.self_signup`, `CustomGame.self_role_edit`,
  `CustomGame.settings.workspace_discord_channel_id` (A8); `Switch` (`@/components/ui/switch`);
  `Button` (`@/components/ui/button`); `useTranslations` (`next-intl`).
- Produces: новые пропсы `PickupMixHeader`:
  `onSetSelfService?: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void`,
  `savingSelfService?: boolean`,
  `onPostSignup?: (selfSignup: "pool" | "benched") => void`,
  `postingSignup?: boolean`.
  Ключи i18n `mixes.self.{signupLabel,signup.*,roleEdit,openInDiscord,noChannel}`.

- [ ] **Step 1: Write the failing test**

1.1. `frontend/src/app/balancer/mix/PickupMixHeader.behavior.test.tsx` — заменить фикстуру `:31-48` на:

```tsx
function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 12,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: "Host",
    name: "Thursday scrim",
    status: "balanced",
    balance_result: null,
    created_at: "2026-01-01T00:00:00Z",
    next_map_id: null,
    selected_variant_index: 0,
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: "555" },
    ...overrides,
  } as CustomGame;
}
```

1.2. Там же — заменить `mount` (`:58-81`) на версию, прокидывающую новые колбэки:

```tsx
const onSetSelfService = vi.fn();
const onPostSignup = vi.fn();

async function mount(
  currentGame: CustomGame | undefined,
  props: { canWrite?: boolean; gameLoading?: boolean } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    const root = createRoot(container);
    roots.push(root);
    root.render(
      <PickupMixHeader
        canWrite={props.canWrite ?? true}
        game={currentGame}
        gameLoading={props.gameLoading ?? false}
        onOpenPool={onOpenPool}
        onOpenAccess={onOpenAccess}
        onSetSelfService={onSetSelfService}
        onPostSignup={onPostSignup}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}
```

(константы `onSetSelfService`/`onPostSignup` объявить рядом с `onOpenPool`/`onOpenAccess` на `:28-29`.)

1.3. Там же — в `beforeEach` (`:96-104`) добавить два сброса:

```tsx
  onOpenPool.mockReset();
  onOpenAccess.mockReset();
  onSetSelfService.mockReset();
  onPostSignup.mockReset();
```

1.4. Там же — дописать в конец файла:

```tsx
// The host's self-service switches. `next-intl` is mocked to echo the key, so
// every label below is the message key rather than the rendered sentence.
describe("PickupMixHeader self-service", () => {
  it("writes the signup mode the host picked", async () => {
    const scope = await mount(game({ self_signup: "closed" }));

    await click(byName(scope, "signup.pool"));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_signup: "pool" });
  });

  it("marks the mode the mix is actually in", async () => {
    const scope = await mount(game({ self_signup: "benched" }));

    const checked = [...scope.querySelectorAll('[role="radio"]')]
      .filter((node) => node.getAttribute("aria-checked") === "true")
      .map((node) => node.textContent?.trim());

    expect(checked).toEqual(["signup.benched"]);
  });

  it("writes the role-edit switch on its own", async () => {
    const scope = await mount(game({ self_role_edit: false }));

    await click(scope.querySelector('[aria-label="roleEdit"]'));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_role_edit: true });
  });

  it("posts the signup card in the mode the mix is in", async () => {
    const scope = await mount(game({ self_signup: "benched" }));

    await click(byName(scope, "openInDiscord"));

    expect(onPostSignup).toHaveBeenCalledWith("benched");
  });

  it("falls a closed mix back to the pool when posting", async () => {
    const scope = await mount(game({ self_signup: "closed" }));

    await click(byName(scope, "openInDiscord"));

    expect(onPostSignup).toHaveBeenCalledWith("pool");
  });

  it("cannot post a signup card with no mix channel", async () => {
    const scope = await mount(
      game({ settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null } }),
    );

    const button = byName(scope, "openInDiscord");
    expect(button?.hasAttribute("disabled")).toBe(true);
    expect(button?.getAttribute("title")).toBe("noChannel");
  });

  it("shows a viewer who cannot write none of it", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(byName(scope, "signup.pool")).toBeNull();
    expect(byName(scope, "openInDiscord")).toBeNull();
    expect(scope.querySelector('[aria-label="roleEdit"]')).toBeNull();
  });
});
```

> `byName` (`:92-94`) ищет по `button`; radio-кнопки режима — тоже `<button role="radio">`, так что находятся им же.
> Свитч Radix рендерит `<button role="switch" aria-label>` — берём через `querySelector`.

1.5. `frontend/src/i18n/messages.parity.test.ts` — дописать внутрь `describe("interpolated message keys")`
(после теста про `team_formation`, перед закрывающей `});` блока):

```ts
  it("every mix self-signup mode has a mixes.self.signup label in both locales", () => {
    // The `custom_game.self_signup` CHECK constraint is the contract; the header
    // renders each mode as `t(`signup.${mode}`)`.
    const modes = ["closed", "pool", "benched"];
    for (const dict of [en, ru]) {
      const labels: Record<string, unknown> = dict.mixes.self.signup;
      expect(modes.filter((value) => !(value in labels))).toEqual([]);
    }
  });

  it("every mix self-service blocker has a mixes.self.blocker label in both locales", () => {
    // The full set `mix_self_policy` can return, in its own check order. The
    // seat panel renders whichever one comes back as `t(`blocker.${code}`)`, so
    // a code with no key ships as the raw dotted path.
    const blockers = [
      "mix_closed",
      "discord_not_linked",
      "battlenet_not_linked",
      "player_not_linked",
      "self_join_denied",
      "already_joined",
      "not_on_roster",
      "signup_closed",
      "roster_full",
      "role_edit_off",
    ];
    for (const dict of [en, ru]) {
      const labels: Record<string, unknown> = dict.mixes.self.blocker;
      expect(blockers.filter((value) => !(value in labels))).toEqual([]);
    }
  });
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd frontend && bunx vitest run src/app/balancer/mix/PickupMixHeader.behavior.test.tsx
cd frontend && bun test src/i18n/messages.parity.test.ts
```

Ожидаемо: vitest — 7 упавших в `PickupMixHeader self-service` (`Error: Expected a clickable node` из `click`,
т.к. `byName` возвращает `null`); bun — `TypeError: undefined is not an object (evaluating 'dict.mixes.self.signup')`
в обоих новых тестах.

- [ ] **Step 3: Minimal implementation**

3.1. `frontend/src/i18n/messages/en.json` — вставить после `:6182` (`}` закрывающая `"leaderboard"`), поставив
на `:6182` запятую:

```json
    "self": {
      "signupLabel": "Signup",
      "signup": {
        "closed": "Closed",
        "pool": "To the pool",
        "benched": "To the bench"
      },
      "roleEdit": "Players edit their own roles",
      "openInDiscord": "Open signup in Discord",
      "noChannel": "This community has no mix channel in Discord",
      "title": "Your seat",
      "join": "Join this mix",
      "leave": "Leave",
      "saveRoles": "Save roles",
      "seat": {
        "pool": "You are in the pool",
        "benched": "You are on the bench — the host moves you into the pool",
        "must_play": "You are guaranteed a seat",
        "none": "You are not in this mix"
      },
      "rolesAllRanked": "Every role you have a rank for",
      "unranked": "No rank yet: {roles}. The host will fill it in.",
      "fixLinks": "Open account settings",
      "blocker": {
        "mix_closed": "This mix is over.",
        "discord_not_linked": "Link your Discord account to join.",
        "battlenet_not_linked": "Link your Battle.net account to join.",
        "player_not_linked": "Your account is not linked to a player profile yet.",
        "self_join_denied": "An admin has closed self-signup for your account.",
        "already_joined": "You are already in this mix.",
        "not_on_roster": "Join the mix first.",
        "signup_closed": "The host has not opened signup.",
        "roster_full": "This mix is full.",
        "role_edit_off": "The host edits roles in this mix."
      }
    }
```

3.2. `frontend/src/i18n/messages/ru.json` — вставить после `:6182` тем же способом:

```json
    "self": {
      "signupLabel": "Запись",
      "signup": {
        "closed": "Закрыта",
        "pool": "В пул",
        "benched": "На скамейку"
      },
      "roleEdit": "Игроки меняют свои роли",
      "openInDiscord": "Открыть запись в Discord",
      "noChannel": "У сообщества не настроен канал миксов в Discord",
      "title": "Ваше место",
      "join": "Записаться",
      "leave": "Выписаться",
      "saveRoles": "Сохранить роли",
      "seat": {
        "pool": "Вы в пуле",
        "benched": "Вы на скамейке — хост переведёт в пул",
        "must_play": "Место за вами",
        "none": "Вас нет в этом миксе"
      },
      "rolesAllRanked": "Все роли, по которым есть ранг",
      "unranked": "Нет ранга: {roles}. Хост проставит.",
      "fixLinks": "Открыть настройки аккаунта",
      "blocker": {
        "mix_closed": "Микс завершён.",
        "discord_not_linked": "Привяжите Discord, чтобы записаться.",
        "battlenet_not_linked": "Привяжите Battle.net, чтобы записаться.",
        "player_not_linked": "К аккаунту ещё не привязан профиль игрока.",
        "self_join_denied": "Администратор закрыл самозапись для вашего аккаунта.",
        "already_joined": "Вы уже в этом миксе.",
        "not_on_roster": "Сначала запишитесь в микс.",
        "signup_closed": "Хост не открыл запись.",
        "roster_full": "Мест больше нет.",
        "role_edit_off": "Роли в этом миксе меняет хост."
      }
    }
```

3.3. `frontend/src/app/balancer/mix/PickupMixHeader.tsx` — заменить импорты `:1-12`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, Send, Trash2, UserCog, UserPlus } from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { CustomGame, MixSelfSignup } from "@/services/custom-game.service";

/** The three signup modes, in the order a host widens access. */
const SELF_SIGNUP_OPTIONS: readonly MixSelfSignup[] = ["closed", "pool", "benched"];
```

3.4. Там же — заменить тип пропсов `:14-26`:

```tsx
type PickupMixHeaderProps = {
  /** Host or co-host, and not-terminal -- gates every write action in this header. */
  canWrite: boolean;
  game: CustomGame | undefined;
  gameLoading: boolean;
  onOpenPool: () => void;
  onOpenAccess: () => void;
  /** Workspace admin (or superuser) -- gates the irreversible hard delete,
   * a stronger grant than the host-or-co-host `canWrite` above. */
  canDelete?: boolean;
  deleting?: boolean;
  onDeleteMix?: () => void;
  /** Omitted -- the self-service row is not offered at all. */
  onSetSelfService?: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) => void;
  savingSelfService?: boolean;
  /** Omitted -- no "open signup in Discord" button. */
  onPostSignup?: (selfSignup: "pool" | "benched") => void;
  postingSignup?: boolean;
};
```

3.5. Там же — заменить сигнатуру `:46-56` (и вернуть `const [deleteOpen, …]`, добавив `t`):

```tsx
export function PickupMixHeader({
  canWrite,
  game,
  gameLoading,
  onOpenPool,
  onOpenAccess,
  canDelete = false,
  deleting = false,
  onDeleteMix,
  onSetSelfService,
  savingSelfService = false,
  onPostSignup,
  postingSignup = false,
}: Readonly<PickupMixHeaderProps>) {
  const t = useTranslations("mixes.self");
  const [deleteOpen, setDeleteOpen] = useState(false);
  // The workspace's channel is the only target a mix has -- with none, the
  // signup card has nowhere to go. Unlike the matchup post (which simply is
  // not offered), this one stays visible and says why: a host who opens
  // signup expects the Discord button to be there, and "missing" reads as a
  // bug where "disabled, because there is no channel" reads as an answer.
  const hasChannel = game?.settings.workspace_discord_channel_id != null;
```

3.6. Там же — вставить второй ряд карточки: между блоком hard-delete (`:109-138`) и закрывающим `</div>`
(`:139`), то есть сразу после `) : null}` блока удаления:

```tsx
      {canWrite && game != null && onSetSelfService ? (
        <div className="flex w-full flex-wrap items-center gap-2.5 border-t border-[color:var(--aqt-border)] pt-3">
          <span className={EYEBROW_CLASS}>{t("signupLabel")}</span>

          <div role="radiogroup" aria-label={t("signupLabel")} className="flex items-center gap-1">
            {SELF_SIGNUP_OPTIONS.map((option) => {
              const selected = game.self_signup === option;
              return (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={savingSelfService}
                  onClick={() => onSetSelfService({ self_signup: option })}
                  className={cn(
                    "rounded-lg border px-2.5 py-1 text-caption font-semibold transition-colors",
                    selected
                      ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-teal)]"
                      : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-3)]",
                    "disabled:cursor-default disabled:opacity-60",
                  )}
                >
                  {t(`signup.${option}`)}
                </button>
              );
            })}
          </div>

          <span aria-hidden="true" className="h-5 w-px shrink-0 bg-[color:var(--aqt-border)]" />

          <div className="flex items-center gap-2">
            <Switch
              checked={game.self_role_edit}
              disabled={savingSelfService}
              aria-label={t("roleEdit")}
              onCheckedChange={(checked) => onSetSelfService({ self_role_edit: checked })}
            />
            <span className="text-caption text-[color:var(--aqt-fg-muted)]">{t("roleEdit")}</span>
          </div>

          {onPostSignup ? (
            <Button
              type="button"
              variant="outline"
              className="ml-auto h-9 shrink-0"
              disabled={!hasChannel || postingSignup}
              title={hasChannel ? undefined : t("noChannel")}
              // A closed mix has no mode to post yet, and the card's whole point
              // is to open signup -- so posting it from `closed` opens the pool,
              // the mode a host picks in every other case.
              onClick={() => onPostSignup(game.self_signup === "benched" ? "benched" : "pool")}
            >
              <Send className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("openInDiscord")}
            </Button>
          ) : null}
        </div>
      ) : null}
```

- [ ] **Step 4: Run, expected PASS**

```
cd frontend && bunx vitest run src/app/balancer/mix/PickupMixHeader.behavior.test.tsx
cd frontend && bun test src/i18n/messages.parity.test.ts
```

Ожидаемо: vitest — `13 passed` (6 старых + 7 новых); bun — `3 passed` (1 старый интерполяционный + 2 новых)
плюс тест паритета ключей.

- [ ] **Step 5: Commit**

```
git add frontend/src/app/balancer/mix/PickupMixHeader.tsx frontend/src/app/balancer/mix/PickupMixHeader.behavior.test.tsx frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json frontend/src/i18n/messages.parity.test.ts
git commit -m "feat(mix): host opens self-signup from the mix header"
```

---

### Task A10: `PickupRoleOrderEditor` + `PickupMySeatPanel` + проводка страницы

**Files:**
- Create: `frontend/src/app/balancer/mix/PickupRoleOrderEditor.tsx`
- Create: `frontend/src/app/balancer/mix/PickupMySeatPanel.tsx`
- Modify: `frontend/src/app/balancer/mix/PickupPlayerSheet.tsx` (импорты `:3-47`, `offRoles` `:157-159`,
  блок ролей `:270-384`, удалить `SortableRoleCard`/`RoleCardBody` `:473-637`)
- Modify: `frontend/src/app/balancer/mix/usePickupMix.ts` (импорты `:3-22`, сигнатура `:68`,
  вставка запроса после `:104`, вставка мутаций после `:371`, `return` `:373-397`)
- Modify: `frontend/src/app/balancer/mix/[gameId]/page.tsx` (импорты `:7-24`, `:56-57`, деструктуризация `:88-111`,
  `PickupMixHeader` `:210-223`, вставка панели после `:254`)
- Test: `frontend/src/app/balancer/mix/PickupMySeatPanel.behavior.test.tsx` (новый)
- Test: `frontend/src/app/balancer/mix/usePickupMix.behavior.test.tsx` (мок сервиса `:30-50`)
- Test (регресс, не меняем): `frontend/src/app/balancer/mix/PickupPlayerSheet.behavior.test.tsx`

**Interfaces:**
- Consumes: `resolveRoleOrder`, `toggleRole`, `LINEUP_ROLES` (`./pickup-lineup`);
  `SortableRows`/`SortableGrip`/`useSortableRow` (`@/components/kit/SortableRows`);
  `RoleRankControls`/`ROLE_RANK_ACCENTS`/`NEUTRAL_RANK_ACCENT` (`@/app/balancer/components/RoleRankControls`);
  `OW_REFERENCE_GRID` (`@/lib/divisions/grid`); `useAccountSettingsModalStore` (`@/stores/account-settings-modal.store`);
  `useAuthProfileStore` (`@/stores/auth-profile.store`); сервис из A8.
- Produces:
  - `export type PickupRoleRank = { rankValue: number | null; sourceLabel: string | null; onChange: ((next: number | null) => void) | null; onClear: (() => void) | null }`
  - `export function PickupRoleOrderEditor(props: { order; isFlex; disabled; label; onReorder; onToggle; onFlexChange; rankFor })`
  - `export function PickupMySeatPanel(props: { state: MixSelfState; saving: boolean; onJoin; onLeave; onSave })`
  - `usePickupMix(workspaceId, pickedGameId, options?: { seatEnabled?: boolean })` → `+ mySeatQuery, joinMix, leaveMix, updateMySeat, setSelfService, postSignup`

- [ ] **Step 1: Write the failing test** — `frontend/src/app/balancer/mix/PickupMySeatPanel.behavior.test.tsx`

```tsx
// @vitest-environment happy-dom
//
// The player's own corner of a mix board. Four things are load-bearing:
//
//  1. a blocker that only an account link can fix offers the link, because the
//     player cannot discover "go link Battle.net" from a refusal alone;
//  2. `can_edit_roles=false` shows the roles and edits nothing -- the host's
//     mix is the host's, and a disabled editor must not be a lie;
//  3. Save writes the drag order and the flex flag, and nothing else: ranks are
//     the host's book (`MIX_ORDER`), participation is the host's decision;
//  4. leaving is always offered to somebody on the roster, even while every
//     other action is blocked -- an unlinked account must still be able to go.
//
// `next-intl` is mocked to echo the key, so every label asserted below is the
// message key rather than the rendered sentence.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MixSelfSeat, MixSelfState } from "@/services/custom-game.service";

import { PickupMySeatPanel } from "./PickupMySeatPanel";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under bun/node, so the sortable wrapper and its hook render inertly here.
vi.mock("@/components/kit/SortableRows", () => ({
  SortableRows: ({
    items,
    children,
  }: {
    items: readonly unknown[];
    children: (item: unknown, index: number) => unknown;
  }) => <div>{items.map((item, index) => children(item, index))}</div>,
  useSortableRow: () => ({ ref: () => {}, style: {}, handleProps: {}, isDragging: false }),
  SortableGrip: () => null,
}));

const openSettings = vi.fn();
vi.mock("@/stores/account-settings-modal.store", () => ({
  useAccountSettingsModalStore: (selector: (state: { open: (tab?: string) => void }) => unknown) =>
    selector({ open: openSettings }),
}));

const onJoin = vi.fn();
const onLeave = vi.fn();
const onSave = vi.fn();

function seat(overrides: Partial<MixSelfSeat> = {}): MixSelfSeat {
  return {
    participation: "pool",
    roles: ["tank", "damage"],
    is_flex: false,
    ranks: { tank: 3300, damage: 2700, support: null },
    ...overrides,
  };
}

function state(overrides: Partial<MixSelfState> = {}): MixSelfState {
  return {
    custom_game_id: 12,
    name: "Thursday scrim",
    status: "balanced",
    self_signup: "pool",
    self_role_edit: true,
    seat: seat(),
    unranked_roles: [],
    policy: {
      can_join: false,
      can_leave: true,
      can_edit_roles: true,
      join_blocker: "already_joined",
      edit_blocker: null,
    },
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const roots: { unmount: () => void }[] = [];

async function mount(value: MixSelfState) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    const root = createRoot(container);
    roots.push(root);
    root.render(
      <PickupMySeatPanel
        state={value}
        saving={false}
        onJoin={onJoin}
        onLeave={onLeave}
        onSave={onSave}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function byName(scope: ParentNode, name: string) {
  return (
    [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null
  );
}

beforeEach(() => {
  while (roots.length > 0) {
    const root = roots.pop();
    act(() => root?.unmount());
  }
  document.body.innerHTML = "";
  openSettings.mockReset();
  onJoin.mockReset();
  onLeave.mockReset();
  onSave.mockReset();
});

describe("PickupMySeatPanel blockers", () => {
  it("offers account settings when only a link is missing", async () => {
    const scope = await mount(
      state({
        seat: null,
        policy: {
          can_join: false,
          can_leave: false,
          can_edit_roles: false,
          join_blocker: "battlenet_not_linked",
          edit_blocker: "battlenet_not_linked",
        },
      }),
    );

    expect(scope.textContent).toContain("blocker.battlenet_not_linked");
    await click(byName(scope, "fixLinks"));

    expect(openSettings).toHaveBeenCalledWith("profile");
  });

  it("offers no account settings for a blocker linking cannot fix", async () => {
    const scope = await mount(
      state({
        seat: null,
        policy: {
          can_join: false,
          can_leave: false,
          can_edit_roles: false,
          join_blocker: "signup_closed",
          edit_blocker: "not_on_roster",
        },
      }),
    );

    expect(scope.textContent).toContain("blocker.signup_closed");
    expect(byName(scope, "fixLinks")).toBeNull();
  });

  it("still lets an unlinked player on the roster leave", async () => {
    const scope = await mount(
      state({
        policy: {
          can_join: false,
          can_leave: true,
          can_edit_roles: false,
          join_blocker: "battlenet_not_linked",
          edit_blocker: "battlenet_not_linked",
        },
      }),
    );

    await click(byName(scope, "leave"));

    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("joins when the policy allows it", async () => {
    const scope = await mount(
      state({
        seat: null,
        policy: {
          can_join: true,
          can_leave: false,
          can_edit_roles: false,
          join_blocker: null,
          edit_blocker: "not_on_roster",
        },
      }),
    );

    await click(byName(scope, "join"));

    expect(onJoin).toHaveBeenCalledTimes(1);
  });
});

describe("PickupMySeatPanel roles", () => {
  it("edits nothing while the host keeps role editing to themselves", async () => {
    const scope = await mount(
      state({
        self_role_edit: false,
        policy: {
          can_join: false,
          can_leave: true,
          can_edit_roles: false,
          join_blocker: "already_joined",
          edit_blocker: "role_edit_off",
        },
      }),
    );

    // The roles are still readable -- the mix is theirs to read either way.
    expect(scope.textContent).toContain("Tank");
    expect(scope.textContent).toContain("blocker.role_edit_off");
    expect(byName(scope, "saveRoles")).toBeNull();
    expect([...scope.querySelectorAll('[role="switch"]')].every((node) => node.hasAttribute("disabled"))).toBe(
      true,
    );
  });

  it("writes only the role order and the flex flag", async () => {
    const scope = await mount(state());

    await click(scope.querySelector('[aria-label="Support for you"]'));
    await click(scope.querySelector('[aria-label="Full flex for you"]'));
    await click(byName(scope, "saveRoles"));

    expect(onSave).toHaveBeenCalledWith({ roles: ["tank", "damage", "support"], is_flex: true });
  });

  it("never edits a rank", async () => {
    const scope = await mount(state());

    expect(scope.querySelectorAll('input[inputmode="numeric"]')).toHaveLength(0);
    expect(scope.textContent).toContain("3300");
  });

  it("warns about a role no rank answers for", async () => {
    const scope = await mount(state({ unranked_roles: ["support"] }));

    expect(scope.textContent).toContain("unranked");
  });
});
```

- [ ] **Step 2: Run it, expected FAIL**

```
cd frontend && bunx vitest run src/app/balancer/mix/PickupMySeatPanel.behavior.test.tsx
```

Ожидаемо: `Error: Failed to load url ./PickupMySeatPanel` — файла ещё нет.

- [ ] **Step 3: Minimal implementation**

3.1. Создать `frontend/src/app/balancer/mix/PickupRoleOrderEditor.tsx` — дословный перенос флекс-блока
(`PickupPlayerSheet.tsx:275-341`), списка выключенных ролей (`:343-379`) и карточек `SortableRoleCard`/
`RoleCardBody` (`:473-637`), с одним новым слотом `rankFor`:

```tsx
"use client";

import {
  NEUTRAL_RANK_ACCENT,
  ROLE_RANK_ACCENTS,
  RoleRankControls,
} from "@/app/balancer/components/RoleRankControls";
import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Switch } from "@/components/ui/switch";
import { OW_REFERENCE_GRID } from "@/lib/divisions/grid";
import { ROLE_LABELS, getRoleIconName, type RoleCode } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";

import { LINEUP_ROLES } from "./pickup-lineup";

/**
 * One role's rank, as this editor should render it.
 *
 * `onChange === null` is the read-only case. A mix's ranks are the HOST's book
 * (`author_user_id = game.host_user_id`), so the host's sheet edits them from
 * here and a player's own panel only reads them -- the player owns `roles` and
 * `is_flex` and nothing else on their row.
 */
export type PickupRoleRank = {
  rankValue: number | null;
  /** Which layer the shown rank came from, badged beside it. */
  sourceLabel: string | null;
  onChange: ((next: number | null) => void) | null;
  /** Only offered when there is an own entry to drop. */
  onClear: (() => void) | null;
};

type PickupRoleOrderEditorProps = {
  /** The roles that are ON, in priority order -- position is what the balancer reads. */
  order: readonly RoleCode[];
  isFlex: boolean;
  disabled: boolean;
  /** Whose roles these are; every control's accessible name ends in it. */
  label: string;
  onReorder: (next: RoleCode[]) => void;
  onToggle: (role: RoleCode) => void;
  onFlexChange: (next: boolean) => void;
  rankFor: (role: RoleCode) => PickupRoleRank;
};

/**
 * Role priority and the flex flag, in one place for both callers.
 *
 * Priority is a drag list because the stored role order *is* the balancer's
 * priority (see `CustomGamePlayer.roles`): deriving it from a rank moved a
 * role's seat the moment any layer's number changed, with no click anyone
 * could point at. Dragging makes it what it always was on the wire.
 *
 * Off roles trail the on ones in canonical order: an unselected role has no
 * priority, so ranking them would imply one.
 */
export function PickupRoleOrderEditor({
  order,
  isFlex,
  disabled,
  label,
  onReorder,
  onToggle,
  onFlexChange,
  rankFor,
}: Readonly<PickupRoleOrderEditorProps>) {
  const offRoles = LINEUP_ROLES.filter((role) => !order.includes(role));

  return (
    <>
      <div
        className={cn(
          "flex items-center justify-between gap-3 rounded-lg border px-3 py-2",
          isFlex
            ? "border-emerald-400/20 bg-emerald-500/[0.08]"
            : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]",
        )}
      >
        <div className="min-w-0">
          <span className="text-xs font-medium text-[color:var(--aqt-fg)]">Full flex</span>
          {isFlex ? (
            <p className="mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">
              Every role is equally preferred — priority order stops mattering.
            </p>
          ) : (
            <p className="mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">
              Drag below to set who the balancer seats first.
            </p>
          )}
        </div>
        <Switch
          checked={isFlex}
          disabled={disabled}
          aria-label={`Full flex for ${label}`}
          onCheckedChange={onFlexChange}
        />
      </div>

      <SortableRows
        items={order}
        getId={(role) => role}
        onReorder={onReorder}
        className="space-y-2"
      >
        {(role, index) => (
          <SortableRoleCard
            key={role}
            id={role}
            role={role}
            label={label}
            priority={index + 1}
            isPrimary={index === 0}
            disabled={disabled}
            onToggle={() => onToggle(role)}
            rank={rankFor(role)}
          />
        )}
      </SortableRows>

      {offRoles.length === 0 ? null : (
        <ul className="space-y-2 pt-0.5">
          {offRoles.map((role) => (
            <li
              key={role}
              className="flex items-start gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-2.5 opacity-80"
            >
              <RoleCardBody
                role={role}
                label={label}
                isOn={false}
                isPrimary={false}
                disabled={disabled}
                onToggle={() => onToggle(role)}
                rank={rankFor(role)}
              />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** One role's card, wired to the drag list: grip, then the row's own content. */
function SortableRoleCard({
  id,
  role,
  label,
  priority,
  isPrimary,
  disabled,
  onToggle,
  rank,
}: Readonly<{
  id: string;
  role: RoleCode;
  label: string;
  /** The row's position in the drag list, 1-based — what the balancer reads as priority. */
  priority: number;
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rank: PickupRoleRank;
}>) {
  const { ref, style, handleProps } = useSortableRow(id, disabled);

  return (
    <li
      ref={ref}
      style={style}
      className={cn(
        "flex items-start gap-2.5 rounded-xl border bg-[color:var(--aqt-overlay-2)] p-2.5 transition-colors",
        "border-[color:var(--aqt-border-2)]",
        ROLE_RANK_ACCENTS[role]?.row,
      )}
    >
      <div className="flex flex-col items-center gap-1">
        <SortableGrip
          handleProps={handleProps}
          label={`Reorder ${ROLE_LABELS[role]} for ${label}`}
          disabled={disabled}
        />
        <span className="text-label font-semibold text-[color:var(--aqt-fg-dim)]">{`#${priority}`}</span>
      </div>
      <RoleCardBody
        role={role}
        label={label}
        isOn
        isPrimary={isPrimary}
        disabled={disabled}
        onToggle={onToggle}
        rank={rank}
      />
    </li>
  );
}

/**
 * One role's card: name, first-choice mark, on/off, and the rank.
 *
 * Where the rank is editable (`rank.onChange`), the field edits the *effective*
 * rank — what balance will actually use — rather than only this host's own
 * entry, because a host reads the number they see and expects to be able to
 * correct it. Where it is not, the same number is printed with its layer: a
 * player must be able to see why the balancer seats them where it does without
 * being handed a control that would 422.
 */
function RoleCardBody({
  role,
  label,
  isOn,
  isPrimary,
  disabled,
  onToggle,
  rank,
}: Readonly<{
  role: RoleCode;
  label: string;
  isOn: boolean;
  /** The top of the drag list — where the balancer will try to seat them first. */
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rank: PickupRoleRank;
}>) {
  const accent = ROLE_RANK_ACCENTS[role] ?? NEUTRAL_RANK_ACCENT;

  return (
    <div className="min-w-0 flex-1 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <PlayerRoleIcon role={getRoleIconName(role)} size={15} decorative />
          <span
            className={cn(
              "text-xs font-semibold",
              isOn ? accent.text : "text-[color:var(--aqt-fg-muted)]",
            )}
          >
            {ROLE_LABELS[role]}
          </span>
          {isPrimary ? (
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-px text-label font-bold uppercase tracking-label",
                accent.chip,
              )}
            >
              First
            </span>
          ) : null}
        </div>

        <div className="flex h-6 items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2">
          <Switch
            checked={isOn}
            disabled={disabled}
            aria-label={`${ROLE_LABELS[role]} for ${label}`}
            onCheckedChange={onToggle}
            className="h-4 w-7 [&>span]:size-3 [&>span]:data-[state=checked]:translate-x-3"
          />
          <span
            className={cn(
              "text-label font-semibold uppercase tracking-label",
              isOn ? accent.text : "text-[color:var(--aqt-fg-dim)]",
            )}
          >
            {isOn ? "Active" : "Off"}
          </span>
        </div>
      </div>

      {rank.onChange == null ? (
        <div className="flex h-8 items-center gap-2 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5">
          <span
            className={cn(
              "text-xs font-semibold tabular-nums",
              isOn ? accent.text : "text-[color:var(--aqt-fg-dim)]",
            )}
          >
            {rank.rankValue ?? "—"}
          </span>
          {rank.sourceLabel ? (
            <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {rank.sourceLabel}
            </span>
          ) : null}
        </div>
      ) : (
        <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_130px]">
          <RoleRankControls
            rankValue={rank.rankValue}
            sourceLabel={rank.sourceLabel}
            accent={accent}
            active={isOn}
            disabled={disabled}
            onClear={rank.onClear}
            onChange={rank.onChange}
            // The global OW grid: balancer-service resolves a mix's ranks
            // against the grid with `workspace_id=None`, so the value edited
            // here is on the OW scale and a workspace's tiers would mislabel it.
            grid={OW_REFERENCE_GRID}
          />
        </div>
      )}
    </div>
  );
}
```

3.2. `frontend/src/app/balancer/mix/PickupPlayerSheet.tsx` — заменить импорты `:3-47`:

```tsx
import { useState } from "react";
import { Pin, Save, UserMinus } from "lucide-react";

import { BattleTagCopyButton } from "@/app/balancer/components/BattleTagCopyControls";
import { PickupRoleOrderEditor } from "@/app/balancer/mix/PickupRoleOrderEditor";
import { splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import { CAPTION_CLASS, EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import RankHistory from "@/components/RankHistory";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { type RoleCode } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import {
  RANK_SOURCE_LABELS,
  type CustomGamePlayer,
  type CustomGamePlayerPatch,
  type MixParticipation,
  type MixMemberStats,
} from "@/services/custom-game.service";

import {
  LINEUP_ISSUE_MESSAGES,
  getLineupIssue,
  playerLabel,
  resolveRoleOrder,
  toggleRole,
} from "./pickup-lineup";
import { formatRecord, formatStreak } from "./pickup-stats";
```

3.3. Там же — удалить `offRoles` (`:157-159`), оставив комментарий-соседа:

```tsx
  // Reads the draft, not the server row: a role turned on (or a rank typed
  // for one) must clear this warning immediately, not once Save round-trips.
  const issue = row ? getLineupIssue(draftRow(row, draft)) : null;
  const disabled = !canEdit || saving;
```

3.4. Там же — заменить блок ролей `:275-379` (от `<div className={cn("flex items-center justify-between gap-3 …` —
флекс-карточка — до закрывающей `)}` списка выключенных ролей) на:

```tsx
              <PickupRoleOrderEditor
                order={draft.order}
                isFlex={draft.isFlex}
                disabled={disabled}
                label={label}
                onReorder={(nextOrder) => setDraft((current) => ({ ...current, order: nextOrder }))}
                onToggle={toggle}
                onFlexChange={(checked) => setDraft((current) => ({ ...current, isFlex: checked }))}
                rankFor={(role) => {
                  const field = stagedRankFor(row, draft, role);
                  return {
                    rankValue: field.rankValue,
                    sourceLabel: field.sourceLabel,
                    onChange: (next) =>
                      setDraft((current) => ({
                        ...current,
                        rankEdits: { ...current.rankEdits, [role]: next },
                      })),
                    onClear: field.hasOwnEntry
                      ? () =>
                          setDraft((current) => ({
                            ...current,
                            rankEdits: { ...current.rankEdits, [role]: null },
                          }))
                      : null,
                  };
                }}
              />
```

3.5. Там же — удалить функции `SortableRoleCard` (`:473-537`) и `RoleCardBody` (`:539-637`) целиком.
`draftRow` (`:438-449`) и `stagedRankFor` (`:451-471`) остаются.

3.6. `frontend/src/app/balancer/mix/PickupMySeatPanel.tsx` — новый файл:

```tsx
"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { LogIn, LogOut, Save } from "lucide-react";

import { PickupRoleOrderEditor } from "@/app/balancer/mix/PickupRoleOrderEditor";
import { CAPTION_CLASS, EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { Button } from "@/components/ui/button";
import { ROLE_LABELS, type RoleCode } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import {
  type MixSelfBlocker,
  type MixSelfSeat,
  type MixSelfState,
} from "@/services/custom-game.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";

import { resolveRoleOrder, toggleRole } from "./pickup-lineup";

/**
 * Blockers an account link fixes, and only those. Linking happens in account
 * settings, which is a modal on every page (`app/layout.tsx`), so the panel
 * opens it in place rather than navigating away from the board the player is
 * watching (the registration form does the same, `RegistrationSchemaForm`).
 */
const LINKABLE_BLOCKERS: Record<string, true> = {
  discord_not_linked: true,
  battlenet_not_linked: true,
  player_not_linked: true,
};

type PickupMySeatPanelProps = {
  state: MixSelfState;
  saving: boolean;
  onJoin: () => void;
  onLeave: () => void;
  onSave: (patch: { roles: RoleCode[] | null; is_flex: boolean }) => void;
};

/** Everything the panel edits before Save, kept apart from the server seat. */
type SeatDraft = { order: RoleCode[]; isFlex: boolean };

/** Ranks with no layer behind them are absent, which is what `resolveRoleOrder` reads. */
function rankedRoles(seat: MixSelfSeat): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [role, rank] of Object.entries(seat.ranks)) {
    if (rank != null) out[role] = rank;
  }
  return out;
}

function buildDraft(seat: MixSelfSeat | null): SeatDraft {
  if (seat == null) return { order: [], isFlex: false };
  return {
    order: resolveRoleOrder({ roles: seat.roles, ranks: rankedRoles(seat) }),
    isFlex: seat.is_flex,
  };
}

/** The server seat as one comparable string, so a refetch that changed nothing leaves a draft alone. */
function signatureOf(seat: MixSelfSeat | null): string {
  if (seat == null) return "none";
  return `${seat.participation}|${seat.roles?.join(",") ?? "all"}|${seat.is_flex}`;
}

/**
 * The player's own corner of a public mix board: where they stand, and the two
 * things they own -- being in the lineup at all, and the order their roles are
 * tried in.
 *
 * Presentational on purpose, like every other panel on this screen: the seat
 * read and its three writes live in `usePickupMix`, so the realtime echo that
 * refreshes the board refreshes this with it.
 *
 * Ranks are printed, never edited. A mix resolves ranks against the HOST's own
 * book (`author_user_id = game.host_user_id`), so a field here would write a
 * number the balance never reads -- the spec's "игрок правит только `roles` и
 * `is_flex`".
 */
export function PickupMySeatPanel({
  state,
  saving,
  onJoin,
  onLeave,
  onSave,
}: Readonly<PickupMySeatPanelProps>) {
  const t = useTranslations("mixes.self");
  const openAccountSettings = useAccountSettingsModalStore((store) => store.open);

  const signature = signatureOf(state.seat);
  const [draft, setDraft] = useState<SeatDraft>(() => buildDraft(state.seat));
  // Reset during render (not in an effect) when the server's own seat changes:
  // React's pattern for state derived from a prop that should reset when the
  // prop's identity changes. A background refetch that changed nothing leaves
  // an edit in progress alone, because the signature is the same string.
  const [seenSignature, setSeenSignature] = useState(signature);
  if (signature !== seenSignature) {
    setSeenSignature(signature);
    setDraft(buildDraft(state.seat));
  }

  const { policy, seat } = state;
  // Off the roster the only question is joining; on it, the edit gate is the
  // live one and the join gate ("already in") is just how they got here.
  const blocker: MixSelfBlocker | null =
    seat == null ? policy.join_blocker : (policy.edit_blocker ?? policy.join_blocker);
  // `already_joined` is not a refusal, it is the state the panel already shows.
  const shownBlocker = blocker === "already_joined" ? null : blocker;
  const canLink = shownBlocker != null && LINKABLE_BLOCKERS[shownBlocker] === true;
  const editable = policy.can_edit_roles && seat != null;
  const dirty =
    seat != null &&
    (draft.isFlex !== seat.is_flex ||
      draft.order.join(",") !== resolveRoleOrder({ roles: seat.roles, ranks: rankedRoles(seat) }).join(","));

  return (
    <div className={cn(PANEL_CLASS, "flex flex-col gap-3 px-4 py-3.5")}>
      <div className="flex flex-wrap items-center gap-2.5">
        <span className={EYEBROW_CLASS}>{t("title")}</span>
        <span className="text-caption font-semibold text-[color:var(--aqt-fg)]">
          {seat == null ? t("seat.none") : t(`seat.${seat.participation}`)}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {policy.can_join ? (
            <Button type="button" className="h-9 shrink-0" disabled={saving} onClick={onJoin}>
              <LogIn className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("join")}
            </Button>
          ) : null}
          {policy.can_leave ? (
            <Button
              type="button"
              variant="outline"
              className="h-9 shrink-0 text-[color:var(--aqt-fg-muted)] hover:border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)] hover:text-rose-200"
              disabled={saving}
              onClick={onLeave}
            >
              <LogOut className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("leave")}
            </Button>
          ) : null}
        </div>
      </div>

      {shownBlocker ? (
        <div className="flex flex-wrap items-center gap-2.5">
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t(`blocker.${shownBlocker}`)}
          </p>
          {canLink ? (
            <Button
              type="button"
              variant="outline"
              className="h-8 shrink-0"
              onClick={() => openAccountSettings("profile")}
            >
              {t("fixLinks")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {state.unranked_roles.length > 0 ? (
        <p className="text-caption text-amber-200">
          {t("unranked", {
            roles: state.unranked_roles.map((role) => ROLE_LABELS[role] ?? role).join(", "),
          })}
        </p>
      ) : null}

      {seat == null ? null : (
        <div className="space-y-2">
          {seat.roles == null ? (
            <p className={CAPTION_CLASS}>{t("rolesAllRanked")}</p>
          ) : null}
          <PickupRoleOrderEditor
            order={draft.order}
            isFlex={draft.isFlex}
            disabled={!editable || saving}
            label="you"
            onReorder={(order) => setDraft((current) => ({ ...current, order }))}
            onToggle={(role) =>
              setDraft((current) => ({ ...current, order: toggleRole(current.order, role) }))
            }
            onFlexChange={(isFlex) => setDraft((current) => ({ ...current, isFlex }))}
            rankFor={(role) => ({
              rankValue: seat.ranks[role] ?? null,
              sourceLabel: null,
              onChange: null,
              onClear: null,
            })}
          />
          {editable ? (
            <Button
              type="button"
              className="h-9"
              disabled={saving || !dirty}
              onClick={() => onSave({ roles: draft.order, is_flex: draft.isFlex })}
            >
              <Save className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("saveRoles")}
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}
```

3.7. `frontend/src/app/balancer/mix/usePickupMix.ts` — заменить импорт сервиса `:7-12`:

```tsx
import {
  customGameKeys,
  customGameService,
  type CustomGame,
  type CustomGamePlayerPatch,
  type MixSelfSignup,
  type MixSelfState,
} from "@/services/custom-game.service";
```

и добавить импорт `RoleCode` рядом с остальными (после строки `import { notify } …`, `:6`):

```tsx
import type { RoleCode } from "@/lib/roster/roles";
```

и тип входа рядом с `PickupSwapSeatsInput` (после `:47`):

```tsx
/** The two fields a player owns on their own row. `roles: null` is `all_ranked`. */
export type PickupMySeatInput = { roles: RoleCode[] | null; is_flex: boolean };
```

3.8. Там же — заменить сигнатуру `:68`:

```tsx
export function usePickupMix(
  workspaceId: number,
  pickedGameId: number | null,
  options: { seatEnabled?: boolean } = {},
) {
```

3.9. Там же — вставить после `rotationQuery` (`:104`), перед `useInvalidation` (`:106-109`):

```tsx
  /**
   * The caller's own standing in this mix. A separate read from the board on
   * purpose: the board is public and identical for every viewer, this answer is
   * about the caller. Off for a signed-out visitor -- the endpoint requires
   * auth and the panel has nothing to show them.
   */
  const mySeatQuery = useQuery({
    queryKey: customGameKeys.me(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.getMySeat(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null && options.seatEnabled === true,
  });
```

3.10. Там же — вставить мутации после `setAuthorRanks` (`:371`), перед `return` (`:373`):

```tsx
  /**
   * A self-write answers with the caller's state, not with the game, so the
   * seat is seeded from the response and the board is invalidated instead:
   * joining and leaving move the roster every viewer reads.
   */
  const applySeat = (state: MixSelfState) => {
    queryClient.setQueryData(customGameKeys.me(workspaceId, state.custom_game_id), state);
    void queryClient.invalidateQueries({
      queryKey: customGameKeys.one(workspaceId, state.custom_game_id),
    });
    void queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId), exact: true });
    void queryClient.invalidateQueries({
      queryKey: customGameKeys.rotation(workspaceId, state.custom_game_id),
    });
  };

  const joinMix = useMutation({
    mutationFn: () => customGameService.joinMix(workspaceId, selectedGameId as number),
    onSuccess: applySeat,
    onError: (error) => notify.apiError(error),
  });

  const leaveMix = useMutation({
    mutationFn: () => customGameService.leaveMix(workspaceId, selectedGameId as number),
    onSuccess: applySeat,
    onError: (error) => notify.apiError(error),
  });

  const updateMySeat = useMutation({
    mutationFn: (input: PickupMySeatInput) =>
      customGameService.updateMySeat(workspaceId, selectedGameId as number, input),
    onSuccess: (state) => {
      applySeat(state);
      notify.success("Roles saved");
    },
    onError: (error) => notify.apiError(error),
  });

  /** The host's switches. Returns the game, so the board is seeded like any other host write. */
  const setSelfService = useMutation({
    mutationFn: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) =>
      customGameService.setSelfService(workspaceId, selectedGameId as number, patch),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /**
   * Opens signup and hands the card to the bot. The mix's own `self_signup`
   * moves server-side, so the board is refetched; the message itself is
   * fire-and-forget, exactly like `postToDiscord`.
   */
  const postSignup = useMutation({
    mutationFn: (selfSignup: "pool" | "benched") =>
      customGameService.postSignup(workspaceId, selectedGameId as number, selfSignup),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: customGameKeys.one(workspaceId, selectedGameId ?? 0),
      });
      notify.success("Signup opened in Discord");
    },
    onError: (error) => notify.apiError(error),
  });
```

3.11. Там же — дополнить `return` (`:373-397`), добавив перед закрывающей `};`:

```tsx
    mySeatQuery,
    joinMix,
    leaveMix,
    updateMySeat,
    setSelfService,
    postSignup,
```

3.12. `frontend/src/app/balancer/mix/usePickupMix.behavior.test.tsx` — заменить мок сервиса `:30-50`
(иначе существующие тесты падают на отсутствующем `customGameKeys.me`):

```tsx
vi.mock("@/services/custom-game.service", () => ({
  customGameKeys: {
    all: (workspaceId: number) => ["custom-games", workspaceId],
    list: (workspaceId: number) => ["custom-games", workspaceId],
    one: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId],
    matches: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "matches"],
    rotation: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "rotation"],
    me: (workspaceId: number, gameId: number) => ["custom-games", workspaceId, gameId, "me"],
  },
  customGameService: {
    list: (...args: unknown[]) => listGames(...args),
    get: (...args: unknown[]) => getGame(...args),
    updateRoster: (...args: unknown[]) => updateRoster(...args),
    updatePlayer: (...args: unknown[]) => updatePlayer(...args),
    listMatches: (...args: unknown[]) => listMatches(...args),
    setParticipation: (...args: unknown[]) => setParticipation(...args),
    rotation: (...args: unknown[]) => rotation(...args),
    undoMatch: (...args: unknown[]) => undoMatch(...args),
    postToDiscord: (...args: unknown[]) => postToDiscord(...args),
    setVariantIndex: (...args: unknown[]) => setVariantIndex(...args),
    getMySeat: (...args: unknown[]) => getMySeat(...args),
    joinMix: (...args: unknown[]) => joinMix(...args),
    leaveMix: (...args: unknown[]) => leaveMix(...args),
    updateMySeat: (...args: unknown[]) => updateMySeat(...args),
    setSelfService: (...args: unknown[]) => setSelfService(...args),
    postSignup: (...args: unknown[]) => postSignup(...args),
  },
}));
```

и объявить недостающие спаи рядом с остальными (`:19-28`):

```tsx
const getMySeat = vi.fn();
const joinMix = vi.fn();
const leaveMix = vi.fn();
const updateMySeat = vi.fn();
const setSelfService = vi.fn();
const postSignup = vi.fn();
```

3.13. `frontend/src/app/balancer/mix/[gameId]/page.tsx` — добавить импорт панели после `:10`:

```tsx
import { PickupMySeatPanel } from "@/app/balancer/mix/PickupMySeatPanel";
```

3.14. Там же — заменить `:57` (чтение профиля), добавив признак входа:

```tsx
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  // The board is public (`config/auth.ts`), so the seat read is the one thing
  // here that needs an actual session: without one `GET …/me` 401s and the
  // panel has nothing to say.
  const isSignedIn = useAuthProfileStore((state) => state.status === "authenticated");
```

3.15. Там же — заменить вызов хука `:88-111`: добавить в деструктуризацию новые поля и третий аргумент:

```tsx
  const {
    selectedGameId,
    gamesQuery,
    gameQuery,
    matchesQuery,
    rotationQuery,
    mySeatQuery,
    setRoster,
    patchPlayer,
    applyRotationHints,
    balance,
    recordOutcome,
    undoMatch,
    setNextMap,
    setVariantIndex,
    closeMix,
    hardDeleteMix,
    setAuthorRanks,
    setTeamNames,
    postToDiscord,
    transferHost,
    addCoHost,
    removeCoHost,
    swapSeats,
    joinMix,
    leaveMix,
    updateMySeat,
    setSelfService,
    postSignup,
  } = usePickupMix(workspaceId ?? 0, pickedGameId, { seatEnabled: isSignedIn });
```

3.16. Там же — заменить рендер заголовка `:210-223`, добавив четыре пропса:

```tsx
            <PickupMixHeader
              canWrite={canWrite}
              game={game}
              gameLoading={gameQuery.isLoading}
              onOpenPool={() => setIsPoolOpen(true)}
              onOpenAccess={() => setIsAccessOpen(true)}
              canDelete={isAdminHere}
              deleting={hardDeleteMix.isPending}
              onDeleteMix={() =>
                hardDeleteMix.mutate(undefined, {
                  onSuccess: () => router.push("/balancer/mix"),
                })
              }
              onSetSelfService={(patch) => setSelfService.mutate(patch)}
              savingSelfService={setSelfService.isPending}
              onPostSignup={(selfSignup) => postSignup.mutate(selfSignup)}
              postingSignup={postSignup.isPending}
            />
```

3.17. Там же — вставить панель игрока сразу после `<PickupTeamsPanel … />` (`:254`), внутри той же колонки:

```tsx
            {/* Visible when the mix invites signups, or when this viewer is
                already in it -- a closed mix a player is not in has nothing to
                tell them, and the board stays as public as it was. */}
            {mySeatQuery.data != null &&
            (mySeatQuery.data.self_signup !== "closed" || mySeatQuery.data.seat != null) ? (
              <PickupMySeatPanel
                state={mySeatQuery.data}
                saving={joinMix.isPending || leaveMix.isPending || updateMySeat.isPending}
                onJoin={() => joinMix.mutate()}
                onLeave={() => leaveMix.mutate()}
                onSave={(patch) => updateMySeat.mutate(patch)}
              />
            ) : null}
```

- [ ] **Step 4: Run, expected PASS**

```
cd frontend && bunx vitest run src/app/balancer/mix/PickupMySeatPanel.behavior.test.tsx src/app/balancer/mix/PickupPlayerSheet.behavior.test.tsx src/app/balancer/mix/usePickupMix.behavior.test.tsx
```

Ожидаемо: 9 passed в `PickupMySeatPanel`, весь существующий `PickupPlayerSheet` (ranks / priority / bench /
Cancel / remove / mix record) зелёный без правок — перенос дословный, — и `usePickupMix` зелёный с дополненным моком.

Затем типизация тронутых модулей (`noUnusedLocals` ловит забытые импорты в `PickupPlayerSheet`):

```
cd frontend && bun run typecheck
```

И пара «файл ↔ раннер» для двух новых vitest-файлов (A8 и A10):

```
cd frontend && bun run test:split
```

Ожидаемо: `… test files, split cleanly: N vitest, M bun:test.` — оба новых файла в vitest-половине
(они попадают под `src/app/balancer/mix/**` в `vitest.config.ts:92-93`).


- [ ] **Step 5: Commit**

```
git add frontend/src/app/balancer/mix/PickupRoleOrderEditor.tsx frontend/src/app/balancer/mix/PickupMySeatPanel.tsx frontend/src/app/balancer/mix/PickupMySeatPanel.behavior.test.tsx frontend/src/app/balancer/mix/PickupPlayerSheet.tsx frontend/src/app/balancer/mix/usePickupMix.ts frontend/src/app/balancer/mix/usePickupMix.behavior.test.tsx "frontend/src/app/balancer/mix/[gameId]/page.tsx"
git commit -m "feat(mix): a player takes their own seat and role order on the board"
```

---

### Task A11: Документация и финальный сквозной смоук

**Files:**
- Modify: `frontend/src/app/(site)/docs/_content/ru/players/mixes.mdx` (`:16-20`, `:71`)
- Modify: `frontend/src/app/(site)/docs/_content/en/players/mixes.mdx` (`:16-20`, `:71`)
- Modify: `docs/business-logic-inventory.md` (`:237-243`)

**Interfaces:** Consumes — поведение, зафиксированное в A1–A10. Produces — только текст.

Тестовых шагов нет: правки чисто текстовые (механический шаг по формату плана). Ниже — точные блоки.

- [ ] **Step 1: ru — раздел «Запись на микс»**

`frontend/src/app/(site)/docs/_content/ru/players/mixes.mdx`, заменить `:16-20` (раздел «Как попасть в микс»)
на:

```mdx
## Как попасть в микс

Есть два пути, и какой работает — решает ведущий.

**Ведущий добавляет вас сам.** Он собирает состав из списка участников сообщества, так что нужно быть в этом
сообществе и попросить его вас добавить.

**Вы записываетесь сами.** Если ведущий открыл запись, появляется блок **Ваше место** на странице микса и
карточка записи в Discord-канале сообщества. Кнопка **Записаться** есть в обоих местах и делает одно и то же.

Для самозаписи к аккаунту должны быть привязаны **и Discord, и Battle.net** — привязки делаются в настройках
аккаунта, вкладка **Профиль**. Пока чего-то не хватает, кнопка объясняет, чего именно, и ведёт прямо в настройки.

Ведущий выбирает, куда попадают записавшиеся: сразу **в пул** (участвуют в ближайшей раздаче) или **на скамейку**
(ведущий сам переводит в пул). Выписаться можно в любой момент — даже если привязки отвалились.

Ваши роли и ранг берутся из данных сообщества, так что отдельную заявку заполнять не нужно.

### Свои роли

Если ведущий включил **Игроки меняют свои роли**, в блоке **Ваше место** (и по кнопке **Мои роли** в Discord)
можно перетаскиванием задать порядок ролей и включить **Full flex**. Порядок — это приоритет: первая роль та, на
которую вас попытаются посадить в первую очередь; флекс означает, что все ваши роли одинаково удобны.

Ранги здесь только показываются: их ведёт ведущий в своей книге рангов. Роль без ранга выбрать можно — будет
предупреждение «Нет ранга», и ведущий его проставит.

Правка ролей действует со **следующего** баланса: уже показанный расклад — снимок, он не пересчитывается сам.
```

- [ ] **Step 2: ru — таблица «Если что-то не получается»**

Там же, заменить строку `:71`:

```mdx
| Вас нет в составе | Если запись открыта — нажмите **Записаться**; иначе попросите ведущего добавить вас |
```

и дописать под ней две строки:

```mdx
| Кнопка «Записаться» не работает | Проверьте, что привязаны и Discord, и Battle.net (настройки аккаунта → Профиль) |
| Свои роли не меняются | Ведущий не включил «Игроки меняют свои роли» — роли правит он |
```

- [ ] **Step 3: en — те же два места**

`frontend/src/app/(site)/docs/_content/en/players/mixes.mdx`, заменить `:16-20`:

```mdx
## Getting into a mix

There are two ways in, and the host decides which one is open.

**The host adds you.** They build the lineup from the community's member list, so you need to be in that
community and ask them to add you.

**You sign yourself up.** When the host opens signup, a **Your seat** block appears on the mix page and a signup
card appears in the community's Discord channel. The **Join** button is in both places and does the same thing.

Signing yourself up needs **both Discord and Battle.net** linked to your account — you link them in account
settings, on the **Profile** tab. Until then the button says which link is missing and takes you straight there.

The host chooses where a signup lands: straight **into the pool** (in the next split) or **on the bench** (the
host moves you into the pool themselves). You can leave at any time — even with a link since removed.

Your roles and rank come from the community's own data, so there is no entry form to fill in.

### Your own roles

If the host turned on **Players edit their own roles**, the **Your seat** block (and the **My roles** button in
Discord) lets you drag your roles into the order you want and switch on **Full flex**. The order is the priority:
the first role is the one the balancer tries to seat you in first, and flex means every role of yours is equally
comfortable.

Ranks are shown here, never edited: they are the host's own book. You may pick a role you have no rank for — it
comes with a "no rank" warning, and the host fills it in.

A role change applies from the **next** balance: the split already on screen is a snapshot and is not recomputed.
```

- [ ] **Step 4: en — таблица Troubleshooting**

Там же, заменить строку `:71`:

```mdx
| You are not in the lineup | If signup is open, press **Join** — otherwise ask the host to add you |
```

и дописать под ней две строки:

```mdx
| Join does nothing | Check that both Discord and Battle.net are linked (account settings → Profile) |
| You cannot change your roles | The host has not turned on "Players edit their own roles" — they edit them |
```

- [ ] **Step 5: `docs/business-logic-inventory.md`, §Mix**

Заменить `:237-243`:

```md
### Mix / custom game

`MixStatus`: draft / balanced / completed / cancelled. Participation: `must_play` / `pool` / `benched`.

Rotation (`mix_rotation.py`): longest sit-out streak → shortest played streak → fewest games → input order. `must_play` always seated. No history, or the whole pool fits → all `NEUTRAL` (do not invent fairness).

Self-signup (`custom_game.self_signup` = `closed` | `pool` | `benched`, `self_role_edit`): one policy,
`mix_self_service.mix_self_policy`, gates Discord and the board alike. Check order is the reason order —
`mix_closed` → `discord_not_linked` → `battlenet_not_linked` → `player_not_linked` → `self_join_denied` →
`already_joined`/`not_on_roster` → `signup_closed` → `roster_full` → `role_edit_off`. Both Discord **and**
Battle.net must be linked (`account_links.missing_account_links`); capability `custom_game.self_join` is
allow-by-default, an admin cuts one account with a deny. `already_joined` is not an error: `self_join` is
idempotent and a host's bench decision survives a second press. `can_leave` ignores every link. A signup is an
ordinary `custom_game_player` row — no separate application table. A player writes `roles` and `is_flex` only;
ranks stay the host's book, participation the host's decision, and an edit applies from the next balance
(`balance_result_json` is a snapshot).

Caps: 8 teams, 16 co-hosts, 100 roster rows for a self-signup (`roster_full`). Host role required (`custom_game.*`).
```

- [ ] **Step 6: Commit**

```
git add "frontend/src/app/(site)/docs/_content/ru/players/mixes.mdx" "frontend/src/app/(site)/docs/_content/en/players/mixes.mdx" docs/business-logic-inventory.md
git commit -m "docs(mix): self-signup in the players guide and the logic inventory"
```

- [ ] **Step 7: Финальный сквозной смоук (ручной, из раздела Verification спеки)**

Не автоматизируется: требуется локальный стек, тестовая Discord-гильдия и два аккаунта с разными привязками.

Подготовка:

```
cd backend && alembic upgrade head          # ожидается head mixself01 (down_revision varcap01)
docker compose up -d                        # PUBLIC_SITE_URL должен быть проставлен для balancer-service
cd frontend && bun run dev
```

Прогон, по шагам, с ожидаемым наблюдением:

1. Хост открывает `/balancer/mix/<id>`, в шапке жмёт **Запись → В пул**.
   Ожидание: кнопка режима подсвечена, `GET …/custom-games/<id>` отдаёт `self_signup: "pool"`.
2. Хост жмёт **Открыть запись в Discord**.
   Ожидание: тост «Signup opened in Discord»; в канале `workspace_discord_channel_id` появляется карточка
   «Запись на микс «…»» с кнопками **Записаться / Мои роли / Выписаться** и ссылкой **Доска микса**, ведущей на
   `PUBLIC_SITE_URL/balancer/mix/<id>`. Без канала кнопка заблокирована с подсказкой про канал.
3. Аккаунт **без Battle.net** жмёт **Записаться** в Discord.
   Ожидание: эфемерный ответ с текстом блокера `battlenet_not_linked` и link-кнопкой на `/?settings=profile`;
   строки в ростере не появилось.
4. Тот же аккаунт открывает доску, видит блок **Ваше место** с тем же блокером и кнопкой **Открыть настройки
   аккаунта** → открывается модалка настроек на вкладке «Профиль». Привязывает Battle.net.
5. Аккаунт **с обеими привязками** жмёт **Записаться** в Discord.
   Ожидание: в открытой у хоста вкладке доски строка игрока появляется **без перезагрузки** (realtime
   `pickup_mix.updated` → инвалидация `["custom-games", ws]`), участие — `pool`.
6. Хост включает свитч **Игроки меняют свои роли**. Игрок в Discord жмёт **Мои роли**, выбирает в select
   `tank,support`.
   Ожидание: эфемерный ответ «Роли: Танк → Сапорт»; на доске у хоста та же пара в том же порядке; в листе
   игрока (`PickupPlayerSheet`) порядок ролей совпадает.
7. Игрок на доске в блоке **Ваше место** перетаскивает `support` наверх, включает **Full flex**, жмёт
   **Сохранить роли**.
   Ожидание: тост «Roles saved», лист хоста показывает новый порядок и флекс; ранги в панели игрока — только
   текст, полей ввода нет.
8. Хост выключает запись (**Запись → Закрыта**), игрок жмёт **Записаться** со старой карточки в Discord.
   Ожидание: блокер `signup_closed`; карточка остаётся, решает колонка, а не карточка.
9. Игрок жмёт **Выписаться**.
   Ожидание: строка уходит из ростера в реальном времени; показанный баланс остаётся снимком до перебаланса.

---

## Self-review

| Раздел спеки | Задачи |
|---|---|
| Data model (`mixself01`, `MixSelfSignup`, клон, деплой no-op) | A1 |
| Admission: `missing_account_links` | A2 |
| Admission: `mix_self_policy`, порядок кодов, `can_leave` | A3 |
| Admission: capability `custom_game.self_join` | A1 (каталог), A4 (проверка) |
| Service logic: `_apply_player_patch`, `self_*`, `set_self_service`, идемпотентность, гонка IntegrityError | A4 |
| RPC и маршруты, openapi/RPC-доки | A5, A7 |
| `post_signup`, `signup_card`, `public_site_url` | A7 |
| Discord: действия, select на 16 опций, флекс, эфемерный ответ, блокеры со ссылкой на профиль, README | A6a, A6b, A6c |
| Frontend: сервис/типы/`customGameKeys.me` | A8 |
| Frontend: контролы хоста | A9 |
| Frontend: `PickupRoleOrderEditor`, `PickupMySeatPanel`, i18n ru/en | A10 |
| Docs: players/mixes.mdx ru/en, business-logic-inventory §Mix, README бота, ERD | A11, A6c, A1 |
| Verification: таблица политики | A3 |
| Verification: сервисные тесты `self_join`/`self_update`/`self_leave` | A4 |
| Verification: тесты бота (равенство ACTIONS/DiscordAction, select → roles, мусор → отказ до RPC) | A6a, A6b |
| Verification: behavior-тест `PickupMySeatPanel` | A10 |
| Verification: сквозной смоук | A11 Step 7 |

Согласованность имён: `mix_self_policy`/`MixSelfPolicy`/`MAX_ROSTER` (A3) → A4; `_apply_player_patch(session, row, patch, allowed)` (A4) → A5; self-state провод (A4) → A6b (`copy.mix_text`) и A8 (`MixSelfState`); `DiscordAction` `mix.*` (A6b) → A7 (`signup_card`); `customGameKeys.me` (A8) → A10.
