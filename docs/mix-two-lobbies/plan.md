# Два лобби в одном миксе — Implementation Plan
**Status:** design approved

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Один микс ведёт до двух лобби одновременно: у каждого свои команды, карта, результат и темп; хост может перемешать оба разом поровну по силе и закрепить игрока за лобби.

**Architecture:** Новая `balancer.custom_game_lobby` забирает у `custom_game` четыре «матчевые» колонки, документ баланса лобби остаётся прежнего вида (2 команды). Членство в лобби выводится из выбранного варианта (`seated_member_ids`), хранятся только `lobby_pin` и `casual.match_busy_player` для честной ротации. Общий перебаланс — чистый `split_into_lobbies` + прежний точный `mix_balancer` в каждом лобби.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic (hand-written), FastStream RPC, pytest через `uv`; Go gateway; Next.js, TanStack Query, next-intl, `@dnd-kit`, vitest + bun:test.

**Spec:** [`design.md`](./design.md) — прочитать первым; каждая задача опирается на него.

## Global Constraints

- **Выполняется после [самозаписи](../mix-self-signup-discord/plan.md).** Все блоки ниже отребейзены на дерево после A1–A11 (см. «Rebased on plan A» в Deviations). Номера строк там, где они по дереву до A, — ищите по символу.
- Маршрутизация по коду из `.claude/CLAUDE.md`: graft/CodeGraph первыми, `grep/glob/read` — запасной путь.
- Backend-тесты — по пакету, из `backend/`: `uv run pytest balancer-service/tests/<file>.py -q`. Lint: `uv run bash scripts/lint.sh`.
- Gateway: `cd gateway && go test ./internal/balancer/...`.
- Frontend: одиночный vitest-файл — `bunx vitest run <path>`, bun:test-файл — `bun test <path>`. Финальные гейты: `bun run typecheck && bun run lint && bun run lint:zones && bun run test:split && bun run test:vitest && bun run test:bun`. Никогда `next build` для проверки.
- Модель/провод меняются ⇒ `cd backend && uv run python scripts/export_erd.py`, `bash scripts/export_openapi_schemas.sh`, `uv run python scripts/check_rpc_docs.py`.
- Миграция `mixlobby01`, `down_revision = "mixself01"`. Все шесть шагов схемы из спеки — в ней одной, с downgrade.
- Потолок — два лобби: `CHECK (lobby_index BETWEEN 0 AND 1)`, `CHECK (lobby_count BETWEEN 1 AND 2)`, `CHECK (lobby_pin BETWEEN 0 AND 1)`.
- `lobby_index` во всех per-lobby запросах по умолчанию `0`: однолобби-микс ведёт себя ровно как сегодня.
- Глобальный индекс названия команды = `lobby_index * 2 + team` (A: 0–1, B: 2–3).
- Коды: 404 `lobby_not_found`; 409 `seat_conflict`; 422 `single_lobby`, `not_enough_for_two_lobbies`, `too_many_pinned`, `too_many_must_play`, `roles_infeasible`, `empty_lineup`; `lobby_pin` при `lobby_count = 1` → 422.
- Clean cutover: верхнеуровневые `balance_result`/`selected_variant_index`/`next_map_id` удаляются из провода в B1, фронт переходит на `lobbies[]` в B2 — без алиасов.
- Коммит после каждой задачи, conventional commits (`feat(balancer): …`, `feat(mix): …`, `docs(mix): …`).

## Порядок выполнения

```
B1 → B2 → B3 → B4 → B5 → B6 → B7 → B8 → B9 → B10 → B11
```

- B2 сразу за B1: B1 меняет провод, до B2 доска микса не рендерит баланс.
- B7 (чистый модуль деления) не зависит от B6 и может идти параллельно ему; B8 требует обоих.
- Фронт B9–B10 опирается на провод B3/B4 и `scope` из B6/B8.
- Финальные backend-гейты (после B8): `cd backend && bash scripts/export_openapi_schemas.sh --check && uv run python scripts/check_rpc_docs.py && uv run python scripts/export_erd.py --check`.

---

## Deviations from spec и проверенные факты

### Модель, операции лобби, ротация (B1, B3–B5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести всё, что относится к одному матчу, из `balancer.custom_game` в дочернюю строку `balancer.custom_game_lobby`, и научить микс вести два таких лобби одновременно — свои команды, карта, результат и темп у каждого.

**Architecture:** Новая таблица `custom_game_lobby` (PK `(custom_game_id, lobby_index)`, CHECK `0..1`) забирает `balance_result_json`, `balance_result_version`, `selected_variant_index`, `next_map_id` и добавляет `balanced_at`. Однолобби-микс — это обычная строка `lobby_index = 0`, поэтому путь кода один. Членство игрока в лобби не хранится: оно выводится из выбранного варианта документа лобби (`seated_member_ids`). Хранятся только пин (`custom_game_player.lobby_pin`) и, для честной ротации, кто играл в соседнем лобби в момент записи матча (`casual.match_busy_player`).

**Tech Stack:** Alembic (схемы `balancer`, `casual`), SQLAlchemy 2 (`shared/models`, `shared/repository`), balancer-service (`src/services`, `src/domain`, `src/rpc`, `src/schemas`), Go gateway (таблица маршрутов), pytest/unittest.

**Spec:** `docs/mix-two-lobbies/design.md`

**Порядок:** план B выполняется **после** плана A (`docs/mix-self-signup-discord/plan.md`, задачи A1–A7, самозапись на микс). Всё ниже уже отребейзено на пост-A дерево.

#### Rebased on plan A

Что изменилось относительно первой редакции этого плана, чтобы исполнитель, накладывающий B поверх A, ничего не потерял:

| Что трогает A | Как это учтено в B |
|---|---|
| A1 добавляет `CustomGame.self_signup`/`self_role_edit` и CHECK `ck_custom_game_self_signup` | B1 удаляет из модели **только** четыре перенесённые колонки; блок `__table_args__` показан в пост-A виде (два CHECK'а + новый `ck_custom_game_lobby_count`) |
| A1 добавляет `self_role_edit=...` в конструктор `models.CustomGame(...)` внутри `create()` | B1 туда не лезет (добавляет строку после `games.create`), B3 переписывает конструктор целиком и **сохраняет** `self_role_edit` |
| A1 добавляет в `_dump_game` поля `self_signup`/`self_role_edit` сразу после `next_map_id` | B1 удаляет только записи `selected_variant_index` и `next_map_id` (с их комментариями); два поля A остаются на месте |
| A1 добавляет `"self_signup"`/`"self_role_edit"` в тестовую фикстуру `_game()` и в `SimpleNamespace` из `test_custom_public_reads.py` | B1 показывает обе фикстуры в пост-A виде (дефолты A сохранены), а проверки `item["self_signup"]`/`item["self_role_edit"]` из A1 остаются |
| A4 выносит мутацию строки ростера в `_reject_unknown(patch, allowed)` + `_apply_player_patch(session, row, patch, allowed)` и добавляет `_SELF_PATCH_FIELDS` | B3 кладёт ветку `lobby_pin` **внутрь** `_apply_player_patch` и расширяет его сигнатуру keyword-only параметром `lobby_count: int = 1`; показаны оба изменённых call-site A (`update_player`, `self_update`) |
| A4 добавляет `lobby_pin` **не** в self-путь | `_SELF_PATCH_FIELDS` остаётся `frozenset({"roles", "is_flex"})`; пин ставит только хост, а `_reject_unknown` отвечает 422 на self-попытку без единой новой проверки |
| A4 вставляет ~20 self-тестов и блок моков в `setUp` `test_custom_game.py`, A1 — два поля в `_game()` | все номера строк в тестовых файлах устарели: B1/B3/B4 адресуют правки **именем теста и точным заменяемым выражением**, а не номером строки |
| A5 вставляет пять self-субъектов в `src/rpc/custom.py` после `_set_participation` | B3 вставляет `_set_lobby_count` **после** A5-блока (после `_set_self_service`), перед `_balance` |
| A5 добавляет пять маршрутов `…/me` + `…/self-service` после строки `discord/post`, A7 — `…/discord/signup` | B3/B4 адресуют маршруты по паттерну (`…/balance`, `…/rotation`), а не по номеру строки |
| A5/A7 добавляют записи в `openapi_schemas.OPERATIONS` и `openapi_docs.DOCS` | B3/B4 адресуют свои записи по ключу-субъекту (`"rpc.balancer.custom.…"`), порядок внутри словаря значения не имеет |
| A7 добавляет `signup_card` в `src/domain/mix_discord.py` (и правит его docstring/`__all__`) | B4 меняет только `build_lineup_embed`; `__all__` и `signup_card` не трогаются |
| A7 вставляет `_post_signup` после `_post_discord` в `src/rpc/custom.py` | B4 правит тело `_post_discord` (добавляет `lobby_index=body.lobby_index`), вставок рядом не делает |
| A1 добавляет два теста в `shared/tests/test_custom_game_models.py` | B1 переписывает только `test_known_settings_are_not_stored_in_one_config_bag` и добавляет свои; тесты A остаются |

Номера строк в исходных файлах (`src/services/custom_game.py`, `src/rpc/custom.py`, `shared/models/*`, `routes.go`) в тексте ниже — **из дерева до плана A**; они оставлены как ориентир, но каждый шаг дополнительно назван символом (функция/метод/ключ словаря), и якорем служит именно символ.

---

#### Deviations from spec

Проверено по коду; спецификация в этих местах либо умалчивает, либо расходится с тем, что в репозитории есть на самом деле.

1. **Репозиторий лобби — обычный класс, не `BaseRepository`.** `BaseRepository.get`/`list` обращаются к `self.model.id` (`backend/shared/repository/base.py:61,88`), а у `CustomGameLobby` составной PK и колонки `id` нет. Поэтому `CustomGameLobbyRepository` пишется как `CustomGameCoHostRepository`/`CustomGameTeamNameRepository` (`backend/shared/repository/custom_game.py:51,117`) — простой класс со своими `create`/`delete`.
2. **`down_revision` миграции — `mixself01`, а не `varcap01`.** Спецификация (строка 267) говорит «какая придёт второй — перевешивает `down_revision`»; по решению сессии первым идёт план самозаписи, поэтому `mixlobby01.down_revision = "mixself01"`. Текущая единственная голова цепочки — `varcap01` (проверено: ни одна ревизия в `backend/migrations/versions/` не ссылается на неё как на `down_revision`).
3. **`CustomGameRepository.WITHOUT_BALANCE_RESULT` исчезает, а не переписывается.** Сейчас это `defer(models.CustomGame.balance_result_json, raiseload=True)` (`backend/shared/repository/custom_game.py:18`), применяемый в `list_for_workspace` (:28) и в двух вызовах `service.get(..., options=...)` (`backend/balancer-service/src/services/custom_game.py:1405,1507`). После переноса у `custom_game` тяжёлой колонки нет вовсе: константа переезжает на `CustomGameLobbyRepository` и применяется только в групповом чтении лобби для списка миксов, а оба `options=` удаляются.
4. **Заголовок эмбеда.** Сегодня заголовок английский: `f"{mix_name} — Match {match_number}"` (`backend/balancer-service/src/domain/mix_discord.py:134`), как и «Map:»/«Points per win:». Русское «Лобби A · игра N» из спецификации добавляется отдельным сегментом **только при `lobby_count == 2`**; при одном лобби заголовок побайтово прежний, и существующие тесты `tests/test_mix_discord.py` остаются зелёными.
5. **`casual.match_busy_player` читается через relationship, а не отдельным запросом.** `CasualMatchRepository.list_for_custom_game` уже делает `selectinload(teams).selectinload(players)` (`backend/shared/repository/casual.py:31`); busy-строки подгружаются тем же способом, поэтому `_rotation_histories` не получает ни одного нового обращения к базе.
6. **`newest_id_for_game` удаляется.** Спецификация пишет «`newest_id_for_game` → `newest_id_for_lobby`»; единственный вызов — `custom_game.py:1360`, поэтому старый метод вырезается целиком (clean cutover), а не остаётся рядом.
7. **`usable_count` в ротации.** Сегодня `usable_count = (len(roster) // players_per_team) * players_per_team` (`custom_game.py:1517`) и может дать больше двух команд. Спецификация просит «места одного лобби», поэтому зажим `min(..., 2 * players_per_team)` применяется **только при `lobby_count == 2`** — вывод однолобби-микса не меняется ни на строку.
8. **Маршрут ротации получает `AllQuery: true`.** `?lobby_index=` иначе до воркера не доедет: строка `gateway/internal/balancer/routes.go:101` сейчас не форвардит query вообще.
9. **`docs/schema.sql` и `docs/schema.dbml`** содержат четыре переносимые колонки (`docs/schema.sql:650-653`). CI их не проверяет, но они закоммичены, поэтому перегенерируются `uv run python scripts/export_db_schema.py` в том же коммите, что и модели.
10. **Нумерация задач.** B2, B6, B7, B8 — соседние слайсы (алгоритм деления пула и scope-баланс, фронтенд). Здесь только B1, B3, B4, B5.
11. **Пересечение с планом самозаписи.** План A уже вынес мутацию строки ростера в `_reject_unknown(patch, allowed)` + `_apply_player_patch(session, row, patch, allowed)` и завёл `_SELF_PATCH_FIELDS = frozenset({"roles", "is_flex"})`. B3 не добавляет второй путь записи: ветка `lobby_pin` живёт внутри `_apply_player_patch`, а проверка «микс ведёт одно лобби → 422» приходит туда новым keyword-only параметром `lobby_count`. См. таблицу «Rebased on plan A» выше.

#### Global Constraints

- Потолок — 2 лобби: CHECK `lobby_index BETWEEN 0 AND 1`, `lobby_count BETWEEN 1 AND 2`, `lobby_pin BETWEEN 0 AND 1`.
- Однолобби-микс после всей серии ведёт себя ровно как сегодня: тот же баланс, та же запись, та же отмена, та же ротация, тот же эмбед.
- Инвариант: у микса ровно `lobby_count` строк лобби. `create` вставляет их, `set_lobby_count` добавляет/удаляет строку 1.
- Форма документа баланса не меняется: у каждого лобби свой документ прежнего вида (`lobby_document`, 2 команды на вариант).
- Названия команд: глобальный индекс = `lobby_index * 2 + team` в существующей `CustomGameTeamName` (`team_index` уже `0..7`).
- Верхнеуровневые `balance_result`, `selected_variant_index`, `next_map_id` из wire удаляются (clean cutover), без алиасов.
- Коды ошибок ровно такие: `lobby_not_found` (404), `seat_conflict` (409), `single_lobby` (422).
- Команды (из `backend/`): `uv run pytest balancer-service/tests/<file>.py -q`, `uv run pytest shared/tests/<file>.py -q`. Гейты: `bash scripts/export_openapi_schemas.sh`, `uv run python scripts/check_rpc_docs.py`, `uv run python scripts/export_erd.py`, `uv run python scripts/export_db_schema.py`.

#### File structure

| Файл | Ответственность |
|---|---|
| `backend/migrations/versions/mixlobby01_custom_game_lobby.py` | шесть шагов схемы + перенос данных в строку лобби 0 и обратно |
| `backend/shared/models/custom_game.py` | `CustomGameLobby`; `CustomGame.lobby_count`; `CustomGamePlayer.lobby_pin`; четыре колонки уходят |
| `backend/shared/models/casual.py` | `CasualMatch.lobby_index`; `CasualMatchBusyPlayer` + relationship |
| `backend/shared/repository/custom_game.py` | `CustomGameLobbyRepository` |
| `backend/shared/repository/casual.py` | `newest_id_for_lobby`, `activity_for_lobbies`, `set_busy_players`, eager-load busy |
| `backend/balancer-service/src/domain/mix_lobbies.py` | чистое `seated_member_ids` |
| `backend/balancer-service/src/services/custom_game.py` | `self.lobbies`, `_lobby`, per-lobby операции, `set_lobby_count` |
| `backend/balancer-service/src/rpc/custom.py` | дампы лобби/ростера, новые субъекты |
| `backend/balancer-service/src/schemas/custom_game.py` | `lobby_index` в телах, `CustomGameLobbyCountPatch` |
| `backend/balancer-service/src/domain/mix_discord.py` | сегмент «Лобби A» в заголовке |
| `gateway/internal/balancer/routes.go` | `PUT …/lobbies`, `AllQuery` у ротации |

### Баланс и деление (B6–B8)

**Спек:** `docs/mix-two-lobbies/design.md` §Balance, §«Одно лобби», §«Оба лобби», §Edge cases, §Verification.

**Что делают три задачи:** B6 — `balance()` распадается на `_solve_lobby` + выбор кандидатов одного лобби (исключая тех, кто сидит в соседнем или закреплён за ним); B7 — чистый модуль деления пула `mix_lobby_split.py`; B8 — `scope: "all"`: делим пул на две равные половины и решаем каждую прежним движком.

**Опора на предыдущие фазы (задачи B1–B5) — считается уже сделанным:**

- `models.CustomGameLobby` (таблица `balancer.custom_game_lobby`), репозиторий `CustomGameLobbyRepository` (`backend/shared/repository/custom_game.py`, реэкспорт из `shared.repository`), атрибут сервиса `self.lobbies` с `list_for_game/get/create/delete`.
- `CustomGameService._lobby(session, game, lobby_index) -> models.CustomGameLobby` (404 `lobby_not_found`).
- `CustomGame.lobby_count: int` (1..2), `CustomGamePlayer.lobby_pin: int | None` (0..1).
- `src/domain/mix_lobbies.py::seated_member_ids(balance_result_json, variant_index) -> frozenset[int]`.
- B1 уже механически перенёс чтения/записи `balance_result_json / balance_result_version / selected_variant_index / next_map_id` с `game` на `lobby = await self._lobby(session, game, 0)`; в `tests/test_custom_game.py` появились модульный хелпер `_lobby(lobby_index=0, **overrides)`, словарь `self.lobby_rows` и фейк `self.lobbies` в `setUp`.

---

#### Deviations from spec

1. **Тело запроса до сервиса не доходит.** Маршрут `POST …/custom-games/{game_id}/balance` (`gateway/internal/balancer/routes.go:96`) объявлен **без** `Body: true`, поэтому gateway не кладёт в RPC `data["payload"]` вообще. Спек пишет «`rpc.balancer.custom.balance` получает тело», но сегодня получать его нечем. B6 добавляет флаг; пустое тело при этом безопасно — `edge/dispatch.go:145-152` декодирует его в `{}` и терпит `io.EOF`, а `shared/rpc/common.py:84-86` (`payload`) возвращает `{}`, если ключа нет. Значит «пустое тело = умолчания» выполняется без отдельной ветки в хендлере.
2. **Порядок задач и литерал `scope`.** B7 (модуль деления) выходит после B6, поэтому B6 вводит `CustomGameBalanceRequest` c `scope: Literal["lobby"] = "lobby"` и сигнатурой сервиса `balance(..., lobby_index=0, ...)`; B8 расширяет литерал до `Literal["lobby", "all"]` и добавляет параметр `scope` и ветку. Ни в одном промежуточном коммите нет принимаемого, но не реализованного значения — `scope: "all"` до B8 отбивается схемой (422 ValidationError). Итоговая сигнатура совпадает с контрактом: `balance(session, *, workspace_id, custom_game_id, scope="lobby", lobby_index=0, actor_user_id, actor_is_superuser=False)`.
3. **Бенч перелива — только для однолобби-микса.** `_apply_balance_result` (`custom_game.py:159-168`) переводит в `BENCHED` тех, кого движок вытеснил. При `lobby_count == 2` это вредно: по §Derived state невлезший игрок — «ждёт», а `BENCHED`-строка выпадает из кандидатов *обоих* лобби, и хост должен разбенчивать вручную. Поэтому вызов остаётся только при `game.lobby_count < 2`. Спек этого не оговаривает.
4. **Пустой список кандидатов** (все не-benched сидят в соседнем лобби или закреплены за ним) → 422 `empty_lineup`, тот же код, что и у пустого лайнапа. Спек кода не называет.
5. **`host_config` читается в `_solve_lobby`.** Контракт фиксирует `_solve_lobby(session, game, lobby, lineup)` без маски, поэтому при `scope: "all"` строка `balancer.user_config` читается трижды (раз на маску для деления и по разу на лобби) вместо одного. Это один индексный чтение-по-PK; существующий тест `test_balance_feeds_the_hosts_stored_preferences_to_the_solver` (`assert_awaited_once_with`) продолжает проходить, потому что он идёт по умолчанию `scope="lobby"`, где чтение ровно одно.
6. **`SplitCandidate` не несёт `is_flex`.** Во-первых, его нет в контракте полей; во-вторых, флекс в движке меняет только штраф за офф-роль (`result_serializer.py:139-146 _is_off_role`), а не то, какой слот игрок может занять. Рёбра двудольного графа — «есть ранг на эту роль», как и написано в спеке.
7. **Слот `flex` в маске.** `resolve_roster_shape` умеет отдать маску вида `{"flex": 6}` (`shared/domain/roster_shape.py:40-41`, тест `test_balance_uses_the_workspace_default_when_the_host_has_no_shape`). Ранга с именем `flex` не бывает ни у кого, поэтому буквальное правило «ребро = есть ранг на эту роль» сделало бы любой all-flex воркспейс вечным `roles_infeasible`. В модуле слот `FLEX_SLOT_CODE` принимает любого играбельного кандидата.
8. **`must_play` сверх `2 * seats` при `scope: "all"`** — новый код `too_many_must_play` (спек его не называет, у неё излишек просто уходил бы в `waiting`). Пин обещает место, а мест на два лобби ровно `2 * seats`: молча отправить часть обещанных ждать нельзя, поэтому шаг 1 деления отбивает такой пул целиком (422 `too_many_must_play`, сервис уже маппит `LobbySplitError.code` в `detail`). Для `scope: "lobby"` всё как раньше — лишние `must_play` дают ValueError движка → 422 с его текстом.
9. **Порядок `waiting`** — входной порядок кандидатов (спек его не фиксирует).
10. **`strength`.** Для `EXPLICIT`-строки — ранг первой роли из её порядка, у которой ранг вообще нашёлся (`classes` строится ровно в этом порядке, `custom_game.py:742-752`); для `ALL_RANKED` — максимум. Спек говорит то же словами «рейтинг роли с высшим приоритетом (all_ranked → максимум)».
11. **Номера строк** ниже — по дереву **до** B1–B5; после их миграций сдвинутся, ориентируйтесь на имена методов.

### Frontend и доки (B2, B9–B11)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести экран микса на пер-лобби модель: чтение `lobbies[]`, вкладки «Лобби A / B», пер-лобби вызовы сервиса, переключатель числа лобби, пины, чипы истории и документация.

**Architecture:** `CustomGame` теряет верхнеуровневые `balance_result` / `selected_variant_index` / `next_map_id` и получает `lobby_count` + `lobbies: CustomGameLobby[]`. B2 — чистая подстановка `lobbies[0]` без изменения UI. B9 добавляет `activeLobby` (состояние `usePickupMix`), новый `PickupLobbyTabs.tsx` и `lobbyIndex` во все пер-лобби вызовы. B10 — шапка (число лобби, «перемешать оба»), бейдж лобби в составе, пин в листе игрока, чип A/B в истории, чип «2 лобби» в списке. Каждая новая строка экрана идёт через `useTranslations("mixes.lobbies")` с ru/en значениями. B11 — документация.

**Tech Stack:** Next.js 16 (App Router, client components), React 19, TanStack Query 5, next-intl 4, Tailwind 4, vitest 4 + happy-dom, bun как пакет-менеджер (`frontend/bun.lock`).

**Spec:** `docs/mix-two-lobbies/design.md` (разделы Wire shape, Frontend, Phases 4–5, Verification).

#### Rebased on plan A

Этот план применяется **после** `docs/mix-self-signup-discord/plan.md` (A8–A11), поэтому все блоки ниже написаны против
пост-A дерева, а не против сегодняшнего:

| Что трогает A | Что это значит для B |
|---|---|
| A8: `custom-game.service.ts` — типы `MixSelf*`, `CustomGame.self_signup`/`self_role_edit`, `customGameKeys.me` (после `rotation`), шесть функций `getMySeat…postSignup` (после `postToDiscord`), импорт `RoleCode` | B2 переписывает тип `CustomGame` **вместе с** двумя полями A; B9 правит `rotation`-ключ и `postToDiscord`, не задевая соседей; все фикстуры `CustomGame` в тестах несут `self_signup`/`self_role_edit` |
| A9: `PickupMixHeader` — `useTranslations("mixes.self")` под именем `t`, четыре новых пропса, второй ряд карточки после блока удаления, импорт `Send`/`Switch` | B10 берёт переводчик под именем `tl` (имя `t` занято), добавляет свои пропсы к пост-A типу и ставит контролы лобби в **первый** ряд, перед блоком удаления; импорт `lucide-react` мержится |
| A10: `PickupPlayerSheet` — `SortableRoleCard`/`RoleCardBody` вынесены в `PickupRoleOrderEditor.tsx`, импорты заменены, блок ролей заменён на `<PickupRoleOrderEditor …>` | B10 вставляет секцию пина в пост-A лист: якорь — закрывающий `</section>` блока Status; `useTranslations` добавляется в пост-A блок импортов |
| A10: `usePickupMix` — третий аргумент `options: { seatEnabled?: boolean }`, `mySeatQuery` после `rotationQuery`, пять мутаций, шесть имён в `return`; в behavior-тесте расширен мок сервиса и добавлен `customGameKeys.me` | B9 сохраняет третий аргумент и все имена A в `return`, вставляет `activeLobby` перед `rotationQuery`, и дополняет **пост-A** мок (`rotation` становится трёхаргументным) |
| A10: `[gameId]/page.tsx` — импорт `PickupMySeatPanel`, `isSignedIn`, расширенная деструктуризация, четыре пропса у заголовка, панель после `<PickupTeamsPanel …>` | B9/B10 достраивают ту же деструктуризацию и те же JSX-блоки, ничего из A не удаляя; блок `PickupMySeatPanel` остаётся ровно там, где его поставил A |
| A9: `mixes.self` — последний блок объекта `mixes` (после `leaderboard`) в `ru.json`/`en.json`; A9 дописал два `it` в `messages.parity.test.ts` | B ставит `mixes.lobbies` сразу после `mixes.self` и **дополняет** тот же `describe("interpolated message keys")`, а не заводит свой |
| A11: `docs/business-logic-inventory.md` §Mix переписан (абзац Self-signup + строка Caps), `players/mixes.mdx` ru/en — разделы «Как попасть в микс» / «Getting into a mix» и таблица Troubleshooting | B11 выдаёт **слитую** секцию §Mix (абзац A дословно) и вставляет свои абзацы внутрь пост-A разделов mdx |

Номера строк в блоках ниже, где они остались, относятся к файлам, которых A не трогает. Там, где A переписывает
тот же кусок, якорь — имя символа или соседняя строка кода, а не номер.

#### Global Constraints

- Потолок — 2 лобби (`lobby_index ∈ {0,1}`), CHECK на бэкенде; UI нигде не предполагает N лобби.
- Глобальный индекс команды = `lobby_index * 2 + team` (A: 0–1, B: 2–3) в существующей `CustomGameTeamName`.
- Форма документа баланса не меняется: у каждого лобби свой документ прежнего вида, `parseVariants` не трогаем.
- Палитра `TEAM_ACCENTS` (2 цвета) остаётся: на экране всегда одно лобби.
- Верхнеуровневые `balance_result` / `selected_variant_index` / `next_map_id` удаляются полностью (clean cutover, без алиасов).
- `balance_result`, `players`, `lineup_recorded`, `matches_count` лобби и `current_lobby` приходят только в детальном ответе (`custom.get`); в `list` их нет.
- Все тесты каталога `frontend/src/app/balancer/mix/**` собираются vitest (`frontend/vitest.config.ts:92-93`), запуск — `bunx vitest run <путь>` из `frontend/`.
- Ветка бэкенда (B1, B3–B8) ставится раньше: задачи ниже предполагают, что сервер уже отдаёт `lobbies[]` и принимает `lobby_index`. Фронтовые задачи плана A (A8–A11) тоже уже применены — см. раздел «Rebased on plan A» выше.

---

#### Deviations from spec

1. **На экране микса i18n неоднороден.** `PickupTeamsPanel.tsx`, `PickupLobbyPanel.tsx`, `PickupMixHeader.tsx`, `PickupPlayerSheet.tsx`, `PickupResultControls.tsx` сегодня содержат только жёстко зашитые английские литералы («Balance teams», «Next map», «Must play»); `useTranslations("mixes.*")` читают лишь список и его спутники — `page.tsx:34`, `PickupMixList.tsx:33`, `PickupCreateMixDialog`, `PickupLeaderboard`. Существующие литералы мы **не трогаем** (это не наша задача), но **каждая новая** строка задач B9/B10 идёт через `useTranslations("mixes.lobbies")` с ru/en значениями — ровно как сестринский план A заводит `mixes.self`. Буквы лобби `A`/`B` остаются константами компонентов: это глифы, одинаковые в обеих локалях, как номер команды.
2. **В `docs/glossary.md` нет ни одного «микс»-термина** (`grep` по `Mix|mix` — 0 совпадений), и файл написан по-английски. Термин добавляется как **Mix lobby** в таблицу «Rosters, registration, balancing» на языке файла, с русской передачей «лобби микса» внутри определения. `frontend/src/i18n/GLOSSARY.md` миксовой лексики тоже не содержит — новая секция там не заводится.
3. **`docs/database_erd.md` и `frontend/src/app/(site)/docs/schema.generated.json` перегенерируются задачей B1** командой `uv run python scripts/export_erd.py` из `backend/`. В B11 только проверка (`--check`), файлы руками не правятся.
4. **`customGameKeys.rotation` получает третий аргумент** (`lobbyIndex`). Контракт задания его не фиксирует, но `custom.rotation` per-lobby — без лобби в ключе кэш отдал бы очередь чужого лобби. Изменение целиком внутри фронтенда.
5. **Фикстуры `game()` в тестах уже не полны по типу** (`PickupMixHeader.behavior.test.tsx:31-48` не задаёт `roster_shape`/`players`, `PickupLobbyPanel.behavior.test.tsx:90-103` не задаёт `role_selection_mode`/`is_flex`). Мы не чиним это попутно: добавляем только новые обязательные поля (`lobby_count`, `lobbies`, `lobby_index` у матча).

---

#### File structure

| Файл | Ответственность |
|---|---|
| `frontend/src/services/custom-game.service.ts` | Типы провода (`CustomGameLobby`, `lobby_count`, `lobbies`, `current_lobby`, `lobby_pin`, `lobby_index`), пер-лобби подписи вызовов, `setLobbyCount`, ключ `rotation` |
| `frontend/src/app/balancer/mix/usePickupMix.ts` | `activeLobby` + все мутации с `lobbyIndex` |
| `frontend/src/app/balancer/mix/[gameId]/page.tsx` | Проводка: вкладки, активное лобби, число лобби, пин |
| `frontend/src/app/balancer/mix/PickupLobbyTabs.tsx` (новый) | Вкладки «Лобби A / B» со статусом |
| `frontend/src/app/balancer/mix/PickupTeamsPanel.tsx` | Матчап одного лобби: пейджер, карта, результат, DnD, Discord, история |
| `frontend/src/app/balancer/mix/PickupMixHeader.tsx` | Число лобби и «перемешать оба» |
| `frontend/src/app/balancer/mix/PickupLobbyPanel.tsx` | Бейдж лобби в строке состава, спрос ролей × `lobby_count` |
| `frontend/src/app/balancer/mix/PickupPlayerSheet.tsx` | Пин игрока к лобби |
| `frontend/src/app/balancer/mix/PickupMixList.tsx` | Чип «2 лобби» в карточке списка |
| `frontend/src/app/balancer/mix/pickup-lineup.ts` | `ROLE_DEMAND` наружу, `summarizeRoleSupply(rows, lobbyCount)`, `teamNamesByIndex(settings, lobbyIndex)`, `PickupRecordOutcomeInput.lobbyIndex` |
| `frontend/src/i18n/messages/{ru,en}.json`, `frontend/src/i18n/messages.parity.test.ts` | Поддерево `mixes.lobbies.*` (ru + en) и покрытие его ICU-аргументов |
| `docs/business-logic-inventory.md`, `docs/glossary.md`, `frontend/src/app/(site)/docs/_content/{ru,en}/{players,organizers}/mixes.mdx` | Документация |

---

## Tasks

### Task B1: Лобби как строка таблицы — миграция и механический перенос на лобби 0

**Files:**
- Create: `backend/migrations/versions/mixlobby01_custom_game_lobby.py`
- Create: `backend/balancer-service/src/domain/mix_lobbies.py`
- Modify: `backend/shared/models/custom_game.py` — шапка (импорты, `__all__`), `CustomGame.__table_args__`, блок колонок `CustomGame` (четыре уходят, `self_signup`/`self_role_edit` из A1 остаются), `CustomGamePlayer.__table_args__` + `lobby_pin`, новая модель в конец файла
- Modify: `backend/shared/models/casual.py` — шапка (импорты, `__all__`), `CasualMatch` (`lobby_index`, relationship), `CasualMatchBusyPlayer` в конец файла
- Modify: `backend/shared/repository/custom_game.py` — `CustomGameRepository` (константа уходит), `CustomGameLobbyRepository` в конец файла
- Modify: `backend/shared/repository/casual.py` — `CasualMatchRepository.list_for_custom_game` (eager-load busy)
- Modify: `backend/shared/repository/__init__.py` — блок `from .custom_game import (...)` и `__all__`
- Modify: `backend/balancer-service/src/services/custom_game.py` — импорты, `CustomGameService.__init__`, новый `_lobby`, `create`, `balance`, `set_next_map`, `set_variant_index`, `discord_lineup`, `swap_seats`, `record_outcome`, `list_matches`, `rotation`
- Modify: `backend/balancer-service/src/rpc/custom.py` — новый `_dump_lobby`, `_dump_game`, `_with_roster`, обработчик `custom.list`, обработчик `custom.delete`
- Test: `backend/balancer-service/tests/test_custom_game.py`, `backend/balancer-service/tests/test_custom_game_flow.py`, `backend/balancer-service/tests/test_custom_public_reads.py`, `backend/shared/tests/test_custom_game_models.py`

**Interfaces:**
- Produces:
  - `models.CustomGameLobby(custom_game_id: int, lobby_index: int, selected_variant_index: int, balance_result_json: dict | None, balance_result_version: int, next_map_id: int | None, balanced_at: datetime | None)`
  - `models.CustomGame.lobby_count: int` (1..2, default 1), `models.CustomGamePlayer.lobby_pin: int | None` (0..1)
  - `models.CasualMatch.lobby_index: int`, `models.CasualMatch.busy_players: list[CasualMatchBusyPlayer]`, `models.CasualMatchBusyPlayer(match_id: int, workspace_member_id: int)`
  - `shared.repository.CustomGameLobbyRepository` с `list_for_game(session, custom_game_id) -> Sequence[CustomGameLobby]`, `list_for_games(session, custom_game_ids) -> dict[int, list[CustomGameLobby]]`, `get(session, custom_game_id, lobby_index) -> CustomGameLobby | None`, `create(session, lobby) -> CustomGameLobby`, `delete(session, lobby) -> None`, атрибут класса `WITHOUT_BALANCE_RESULT`
  - `CustomGameService.lobbies: CustomGameLobbyRepository`, `async CustomGameService._lobby(session, game, lobby_index: int) -> models.CustomGameLobby` (404 `lobby_not_found`)
  - wire: в каждом дампе микса `lobby_count: int` и `lobbies: [{lobby_index, selected_variant_index, next_map_id, balanced_at}]`; в детальном ответе у каждого лобби дополнительно `balance_result`; верхнеуровневых `balance_result`/`selected_variant_index`/`next_map_id` больше нет
- Consumes: ничего (первая задача серии).

- [ ] **Step 1: Write the failing test**

В `backend/balancer-service/tests/test_custom_game.py` заменить фикстуру `_game` (пост-A она несёт ещё `self_signup`/`self_role_edit` из A1) на неё же без четырёх перенесённых колонок, плюс новый помощник `_lobby`:

```python
def _game(**overrides) -> SimpleNamespace:
    fields = {
        "id": 11,
        "workspace_id": 1,
        "host_user_id": 9,
        "name": "Scrim",
        "status": "draft",
        "lobby_count": 1,
        "self_signup": "closed",
        "self_role_edit": False,
    }
    fields.update(overrides)
    return _row(**fields)


def _lobby(lobby_index: int = 0, **overrides) -> SimpleNamespace:
    """One ``balancer.custom_game_lobby`` row: everything one match is about."""
    fields = {
        "custom_game_id": 11,
        "lobby_index": lobby_index,
        "selected_variant_index": 0,
        "balance_result_json": None,
        "balance_result_version": 1,
        "next_map_id": None,
        "balanced_at": None,
    }
    fields.update(overrides)
    return _row(**fields)
```

В `_roster_row` (модульный помощник над классом тестов) добавить поле пина — оно понадобится в B3 и B4, а строка ростера обязана иметь его уже сейчас:

```python
    fields = {
        "id": row_id,
        "custom_game_id": 11,
        "workspace_member_id": member_id,
        "sort_order": sort_order,
        "participation": MixParticipation.POOL,
        "is_flex": False,
        "roles": None,
        "lobby_pin": None,
        "created_at": None,
    }
```

В `setUp`, сразу после блока `self.team_names = MagicMock()` / `self.team_names.set = AsyncMock()` и перед `self.host_prefs = MagicMock()`, добавить хранилище лобби (блок self-service моков, который A4 вставил ниже — после `self.roster.delete = AsyncMock()`, — не трогается):

```python
        # ``balancer.custom_game_lobby`` as a dict keyed by lobby_index: a fresh
        # mix has exactly one row, and a test that needs lobby B assigns
        # ``self.lobby_rows[1] = _lobby(1, ...)``.
        self.lobby_rows: dict[int, SimpleNamespace] = {0: _lobby(0)}
        self.lobbies = MagicMock()
        self.lobbies.list_for_game = AsyncMock(
            side_effect=lambda _s, _gid: [self.lobby_rows[index] for index in sorted(self.lobby_rows)]
        )
        self.lobbies.get = AsyncMock(side_effect=lambda _s, _gid, index: self.lobby_rows.get(index))
        self.lobbies.create = AsyncMock(side_effect=lambda _s, row: self.lobby_rows.setdefault(row.lobby_index, row))
        self.lobbies.delete = AsyncMock(side_effect=lambda _s, row: self.lobby_rows.pop(row.lobby_index, None))
```

и передать его в конструктор `CustomGameService(...)` — строка `co_hosts=self.co_hosts,` получает соседа (пять kwargs плана A — `players=`, `workspace_members=`, `load_missing_links=`, `enroll_member=`, `grant_player_role=` — остаются как есть):

```python
            co_hosts=self.co_hosts,
            lobbies=self.lobbies,
```

Новый тест — сразу после `test_balance_calls_run_balance_and_stores_result`:

```python
    async def test_balance_stores_the_document_on_lobby_zero(self) -> None:
        """The matchup is a fact about a lobby, not about the mix.

        A single-lobby mix is simply lobby 0, so the document, the pager and the
        moment it was balanced land on that row -- the mix itself keeps only the
        status.
        """
        game = _game()
        payload = {"variants": [{"teams": [{"roster": {"tank": [{"uuid": "7"}]}}]}]}
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)
        self.run_balance.return_value = payload

        out = await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        lobby = self.lobby_rows[0]
        self.assertIs(lobby.balance_result_json, payload)
        self.assertEqual(lobby.selected_variant_index, 0)
        self.assertIsNotNone(lobby.balanced_at)
        self.assertEqual(out.status, "balanced")
```

Существующие тесты, которые держали эти колонки на миксе, переезжают на строку лобби. Полный список — по имени теста (номера строк после плана A уже не совпадают: A1 добавил два поля в `_game()`, A4 — импорт, помощник `_auth`, блок моков в `setUp` и ~20 self-тестов после `test_set_participation_terminal_409`). Self-тесты плана A четырёх колонок не касаются и правок не требуют.

| Тест | Было | Стало |
|---|---|---|
| `test_create_clones_a_previous_mix` | `source = _game(id=5, status="completed", next_map_id=42, balance_result_json={"variants": []})` | `source = _game(id=5, status="completed")` |
| `test_create_clones_a_previous_mix` (хвост) | `self.assertIsNone(game.balance_result_json)` / `self.assertIsNone(game.next_map_id)` | `created = self.lobbies.create.await_args.args[1]` / `self.assertEqual(created.lobby_index, 0)` / `self.assertIsNone(created.balance_result_json)` / `self.assertIsNone(created.next_map_id)` |
| `test_balance_calls_run_balance_and_stores_result` | `self.assertIs(out.balance_result_json, payload)` | `self.assertIs(self.lobby_rows[0].balance_result_json, payload)` |
| `test_update_player_keeps_stored_balance` | `game = _game(status="balanced", balance_result_json={"variants": []})` … `self.assertEqual(game.balance_result_json, {"variants": []})` | `game = _game(status="balanced")` + следующей строкой `self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": []})` … `self.assertEqual(self.lobby_rows[0].balance_result_json, {"variants": []})` |
| `test_update_roster_keeps_stored_balance` | то же выражение | то же преобразование |
| `test_record_outcome_snapshots_a_casual_match_and_stays_open`, `test_record_outcome_redeems_the_pin_of_whoever_played`, `test_record_outcome_writes_the_selected_map`, `test_record_outcome_draw_scores_zero_zero`, `test_record_outcome_without_a_host_points_knob_never_adjusts_ranks`, `test_record_outcome_applies_the_hosts_points_with_fallback_to_balance_rating`, `test_record_outcome_skips_points_delta_on_a_draw`, `test_record_outcome_freezes_the_points_it_applied`, `test_record_outcome_freezes_nothing_on_a_draw` | `self.games.get.return_value = _game(status="balanced", balance_result_json=lobby_document(result["variants"]))` | `self.games.get.return_value = _game(status="balanced")` + `self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]))` |
| `test_record_outcome_takes_the_next_map_and_clears_it`, `test_record_outcome_explicit_map_beats_the_next_map` | `game = _game(status="balanced", balance_result_json=lobby_document(result["variants"]), next_map_id=42)` … `self.assertIsNone(game.next_map_id)` | `game = _game(status="balanced")` + `lobby = self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]), next_map_id=42)` … `self.assertIsNone(lobby.next_map_id)` |
| `test_record_outcome_unknown_map_404` | `_row(id=11, workspace_id=1, host_user_id=9, name="Scrim", status="balanced", config_json=None, balance_result_json={"variants": [{"teams": []}]})` | `_row(id=11, workspace_id=1, host_user_id=9, name="Scrim", status="balanced", lobby_count=1)` + `self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [{"teams": []}]})` |
| `test_set_next_map_stores_a_catalogue_map` | `self.assertEqual(game.next_map_id, 42)` | `self.assertEqual(self.lobby_rows[0].next_map_id, 42)` |
| `test_set_variant_index_pages_the_mix_for_every_viewer` | `_game(status="balanced", balance_result_json=lobby_document(result["variants"]))` … `self.assertEqual(game.selected_variant_index, 2)` | `_game(status="balanced")` + `self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]))` … `self.assertEqual(self.lobby_rows[0].selected_variant_index, 2)` |
| `test_set_variant_index_past_the_stored_options_404` | `_game(status="balanced", balance_result_json=lobby_document(result["variants"]))` | `_game(status="balanced")` + `self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]))` |
| `test_discord_lineup_without_a_workspace_channel_409`, `test_discord_lineup_posts_to_the_workspace_channel`, `test_discord_lineup_unknown_variant_404` | `_game(balance_result_json={"variants": [{"teams": []}]})` | `_game()` + `self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [{"teams": []}]})` |
| `test_discord_lineup_describes_the_next_match_of_this_mix` | `_game(next_map_id=42, balance_result_json=lobby_document(result["variants"]))` | `_game()` + `self.lobby_rows[0] = _lobby(0, next_map_id=42, balance_result_json=lobby_document(result["variants"]))` |
| `test_set_team_names_touches_no_other_setting` | `game = _game(next_map_id=42)` … `self.assertEqual(game.next_map_id, 42)` | `game = _game()` + `self.lobby_rows[0] = _lobby(0, next_map_id=42)` … `self.assertEqual(self.lobby_rows[0].next_map_id, 42)` |
| `test_swap_seats_swaps_players_and_recomputes_stats`, `test_swap_seats_clears_every_engine_scored_metric`, `test_swap_seats_rejects_different_roles`, `test_swap_seats_rejects_an_unknown_player`, `test_swap_seats_rejects_an_out_of_range_variant`, `test_swap_seats_requires_the_host` | `_game(balance_result_json=self._two_team_result())` | `_game()` + `self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())` |
| `test_swap_seats_upgrades_a_document_stored_in_the_old_form` | `_game(balance_result_json={"variants": [self._two_team_payload()]})` | `_game()` + `self.lobby_rows[0] = _lobby(0, balance_result_json={"variants": [self._two_team_payload()]})` |
| `test_swap_seats_rejects_the_same_team`, `test_swap_seats_counts_off_role_after_the_move` | `_game(balance_result_json=result)` | `_game()` + `self.lobby_rows[0] = _lobby(0, balance_result_json=result)` |
| `test_swap_seats_terminal_409` | `_game(status=status, balance_result_json=self._two_team_result())` | `_game(status=status)` + `self.lobby_rows[0] = _lobby(0, balance_result_json=self._two_team_result())` |
| `test_swap_seats_swaps_players_and_recomputes_stats`, `test_swap_seats_upgrades_a_document_stored_in_the_old_form`, `test_swap_seats_clears_every_engine_scored_metric`, `test_swap_seats_counts_off_role_after_the_move` (проверки) | `game.balance_result_json[...]` / `stored = game.balance_result_json` | `self.lobby_rows[0].balance_result_json[...]` / `stored = self.lobby_rows[0].balance_result_json` |

В `backend/balancer-service/tests/test_custom_game_flow.py` добавить фейк лобби — после класса `_TeamNames` (строка 105):

```python
class _Lobbies:
    """``balancer.custom_game_lobby`` as a dict keyed by (game id, lobby index)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, int], Any] = {}

    async def list_for_game(self, _session: Any, game_id: int) -> list[Any]:
        return [row for (gid, _index), row in sorted(self.rows.items()) if gid == game_id]

    async def get(self, _session: Any, game_id: int, lobby_index: int) -> Any:
        return self.rows.get((game_id, lobby_index))

    async def create(self, _session: Any, row: Any) -> Any:
        self.rows[(row.custom_game_id, row.lobby_index)] = row
        return row

    async def delete(self, _session: Any, row: Any) -> None:
        self.rows.pop((row.custom_game_id, row.lobby_index), None)
```

и в `setUp` (строка 220 `self.casual = _CasualStore()`) добавить `self.lobbies = _Lobbies()`, а в конструктор сервиса (строка 247 `co_hosts=self.co_hosts,`) — `lobbies=self.lobbies,`.

В `backend/balancer-service/tests/test_custom_public_reads.py` переписать `test_list_rows_leave_the_solver_document_out` (A1 уже добавил в его фикстуру `self_signup`/`self_role_edit` и две проверки — они сохраняются):

```python
    async def test_list_rows_leave_the_solver_document_out(self) -> None:
        """The list never touches a lobby's ``balance_result_json``: the column is
        deferred with ``raiseload`` there, and it is megabytes per balanced mix.
        The lobby row below has no such attribute, so any read of it fails the call."""
        row = SimpleNamespace(
            id=3,
            workspace_id=7,
            host_user_id=5,
            name="Friday mix",
            status="balanced",
            lobby_count=1,
            self_signup="pool",
            self_role_edit=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        lobby = SimpleNamespace(
            custom_game_id=3, lobby_index=0, selected_variant_index=2, next_map_id=None, balanced_at=None
        )
        service = MagicMock()
        service.list = AsyncMock(return_value=[row])
        service.hosts = AsyncMock(return_value={5: "Host"})
        service.casual_matches.activity_for_games = AsyncMock(return_value={})
        service.team_names.mapping_for_games = AsyncMock(return_value={3: {1: "Ravens"}})
        service.lobbies.list_for_games = AsyncMock(return_value={3: [lobby]})
        service.workspace_discord_channel_id = AsyncMock(return_value=None)
        service.host_prefs.points_per_win_by_user = AsyncMock(return_value={5: 25})

        with patch.object(custom, "custom_game_service", service):
            listed = await self._call("rpc.balancer.custom.list", {"workspace_id": 7})

        self.assertTrue(listed["ok"], listed)
        [item] = listed["data"]
        self.assertNotIn("balance_result", item)
        self.assertNotIn("selected_variant_index", item)
        self.assertEqual({"1": "Ravens"}, item["settings"]["team_names"])
        self.assertEqual(25, item["settings"]["points_per_win"])
        # From plan A, unchanged by the lobby cutover.
        self.assertEqual("pool", item["self_signup"])
        self.assertIs(True, item["self_role_edit"])
        self.assertEqual(1, item["lobby_count"])
        self.assertEqual(
            [{"lobby_index": 0, "selected_variant_index": 2, "next_map_id": None, "balanced_at": None}],
            item["lobbies"],
        )
```

и в `test_listing_and_scoring_a_workspace_mixes_needs_no_identity` добавить строку рядом с остальными заглушками:

```python
        service.lobbies.list_for_games = AsyncMock(return_value={})
```

В `backend/shared/tests/test_custom_game_models.py` переписать `TestCustomGameModel.test_known_settings_are_not_stored_in_one_config_bag` (два теста A1 — `test_self_signup_has_exactly_three_modes` и `test_self_service_switches_are_columns_with_a_closed_default` — остаются как есть) и добавить тесты новых таблиц:

```python
    def test_known_settings_are_not_stored_in_one_config_bag(self):
        columns = models.CustomGame.__table__.columns
        # The solver document is the lobby's, not the mix's: two lobbies of one
        # mix hold two independent matchups.
        assert "balance_result_json" not in columns
        assert "selected_variant_index" not in columns
        assert "next_map_id" not in columns
        assert "config_json" not in columns
        assert "result_json" not in columns
        assert "outcome_json" not in columns
        assert "co_host_user_ids" not in columns

    def test_everything_about_one_match_lives_on_the_lobby(self):
        columns = models.CustomGameLobby.__table__.columns
        assert {
            "custom_game_id",
            "lobby_index",
            "balance_result_json",
            "balance_result_version",
            "selected_variant_index",
            "next_map_id",
            "balanced_at",
        } <= set(columns.keys())
        assert [column.name for column in models.CustomGameLobby.__table__.primary_key] == [
            "custom_game_id",
            "lobby_index",
        ]

    def test_a_match_records_which_lobby_played_it(self):
        assert "lobby_index" in models.CasualMatch.__table__.columns
        busy = models.CasualMatchBusyPlayer.__table__
        assert busy.schema == "casual"
        assert [column.name for column in busy.primary_key] == ["match_id", "workspace_member_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_custom_game.py -q
uv run pytest shared/tests/test_custom_game_models.py -q
```
Expected: FAIL — `TypeError: CustomGameService.__init__() got an unexpected keyword argument 'lobbies'` в `test_custom_game.py`; `AttributeError: module 'shared.models' has no attribute 'CustomGameLobby'` в `test_custom_game_models.py`.

- [ ] **Step 3: Write minimal implementation**

**3.1 `backend/shared/models/custom_game.py`.** Шапка файла (импорты + `__all__`):

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = (
    "CustomGame",
    "CustomGameCoHost",
    "CustomGameLobby",
    "CustomGamePlayer",
    "CustomGamePlayerRole",
    "CustomGameTeamName",
)
```

`CustomGame.__table_args__` — пост-A здесь уже два CHECK'а (`ck_custom_game_status` и `ck_custom_game_self_signup` из A1); добавляется третий:

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
        CheckConstraint("lobby_count BETWEEN 1 AND 2", name="ck_custom_game_lobby_count"),
        # (no per-mix points_per_win check: the knob is the host's, see above)
        {"schema": "balancer"},
    )
```

Четыре колонки `CustomGame` — от комментария `# The map the next recorded match is played on` до `balance_result_version` включительно — заменяются одной. Колонки `self_signup`/`self_role_edit`, которые A1 добавил **после** `balance_result_version`, остаются нетронутыми и оказываются следом за `lobby_count`:

```python
    # How many lobbies this mix runs at once. There are exactly this many
    # ``custom_game_lobby`` rows: everything about one played match -- the
    # matchup, the pager, the rolled map -- is a fact about a lobby, not about
    # the mix, so two lobbies never fight over one column.
    lobby_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
```

`CustomGamePlayer.__table_args__` получает ещё один CHECK (после `ck_custom_game_player_role_selection_mode`):

```python
        CheckConstraint("lobby_pin BETWEEN 0 AND 1", name="ck_custom_game_player_lobby_pin"),
```

и колонку после `is_flex`:

```python
    # The host's "this one plays in A": honoured by the next balance, not a
    # live seat. ``None`` means the solver places them wherever they fit.
    lobby_pin: Mapped[int | None] = mapped_column(Integer(), nullable=True)
```

Новая модель — после класса `CustomGameCoHost`:

```python
class CustomGameLobby(db.Base):
    """One of a mix's lobbies: its own matchup, pager, map and clock.

    A mix with one lobby is simply row ``lobby_index = 0``, so there is one code
    path for one and for two. Membership is NOT stored: who is in a lobby right
    now is derived from the seats of its selected variant, which keeps the
    matchup the single source of truth instead of a column to re-sync after
    every balance and every swap.

    ``balanced_at`` says when this lobby last got a matchup, and is the half of
    "the lineup on screen was never recorded" the mix cannot answer from the
    match history alone.
    """

    __tablename__ = "custom_game_lobby"
    __table_args__ = (
        CheckConstraint("lobby_index BETWEEN 0 AND 1", name="ck_custom_game_lobby_index"),
        {"schema": "balancer"},
    )

    custom_game_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), primary_key=True
    )
    lobby_index: Mapped[int] = mapped_column(Integer(), primary_key=True)
    # Which stored balance option this lobby is showing. Host-driven: the pager
    # is the host's, and every other viewer renders whatever it points at.
    selected_variant_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    balance_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    balance_result_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
    # The map this lobby's next match is played on -- rolled ahead of the lobby
    # loading in, consumed and cleared by ``record_outcome``.
    next_map_id: Mapped[int | None] = mapped_column(ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True)
    balanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**3.2 `backend/shared/models/casual.py`.** Шапка (строки 1–8):

```python
from __future__ import annotations

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums

__all__ = ("CasualMatch", "CasualMatchBusyPlayer", "CasualTeam", "CasualPlayer")
```

`CasualMatch` (строки 14–32):

```python
    __tablename__ = "match"
    __table_args__ = (
        CheckConstraint("lobby_index BETWEEN 0 AND 1", name="ck_casual_match_lobby_index"),
        {"schema": "casual"},
    )

    custom_game_id: Mapped[int] = mapped_column(ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), index=True)
    # Which lobby of the mix played it. Every pre-two-lobby match is lobby 0,
    # which is also what a one-lobby mix keeps writing.
    lobby_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    map_id: Mapped[int | None] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    # How far this match actually moved both teams' ranks when it was recorded.
    # Undo rolls back this stored amount, never the mix's current
    # ``points_per_win``: the knob may have changed since. NULL for a draw or a
    # match recorded with points off.
    points_per_win_applied: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    teams: Mapped[list[CasualTeam]] = relationship(
        back_populates="match",
        passive_deletes=True,
        order_by="CasualTeam.id",
    )
    busy_players: Mapped[list[CasualMatchBusyPlayer]] = relationship(
        back_populates="match",
        passive_deletes=True,
    )
```

Новая модель — в конец файла:

```python
class CasualMatchBusyPlayer(db.Base):
    """Who was playing the mix's OTHER lobby while this match was recorded.

    Rotation fairness only: a member listed here neither played this match nor
    sat it out -- they were in the other lobby -- so counting it either way
    would either fake a rest or fake a game. Empty for every one-lobby mix,
    which is exactly why nothing needs backfilling.
    """

    __tablename__ = "match_busy_player"
    __table_args__ = ({"schema": "casual"},)

    match_id: Mapped[int] = mapped_column(ForeignKey("casual.match.id", ondelete="CASCADE"), primary_key=True)
    workspace_member_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="CASCADE"), primary_key=True
    )

    match: Mapped[CasualMatch] = relationship(back_populates="busy_players")
```

**3.3 `backend/shared/repository/custom_game.py`.** Строки 13–31 — константа уходит:

```python
class CustomGameRepository(BaseRepository[models.CustomGame]):
    def __init__(self) -> None:
        super().__init__(models.CustomGame)

    async def list_for_workspace(self, session: AsyncSession, workspace_id: int) -> Sequence[models.CustomGame]:
        """Every mix of the workspace, newest first."""
        result = await session.scalars(
            self.select().where(self.model.workspace_id == workspace_id).order_by(self.model.id.desc())
        )
        return result.all()
```

В конец файла — новый репозиторий:

```python
class CustomGameLobbyRepository:
    """The per-lobby half of a mix, keyed by ``(custom_game_id, lobby_index)``.

    Not a ``BaseRepository``: the row has a composite primary key and no ``id``
    column, which every generic lookup there is written against.
    """

    #: Leaves the solver document in the database. It is the one heavy column a
    #: lobby has -- an entry per balance option, megabytes once balanced -- and
    #: only the detail read and the writes that edit it look at it. ``raiseload``
    #: turns a stray read into an error instead of an implicit async lazy load.
    WITHOUT_BALANCE_RESULT = (defer(models.CustomGameLobby.balance_result_json, raiseload=True),)

    async def list_for_game(self, session: AsyncSession, custom_game_id: int) -> Sequence[models.CustomGameLobby]:
        """Both lobbies of one mix in board order, documents loaded."""
        result = await session.scalars(
            sa.select(models.CustomGameLobby)
            .where(models.CustomGameLobby.custom_game_id == custom_game_id)
            .order_by(models.CustomGameLobby.lobby_index)
        )
        return result.all()

    async def list_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, list[models.CustomGameLobby]]:
        """``custom_game_id -> [lobby, ...]`` for a whole mix list in one query,
        without the solver documents -- no list row renders one."""
        if not custom_game_ids:
            return {}
        result = await session.scalars(
            sa.select(models.CustomGameLobby)
            .where(models.CustomGameLobby.custom_game_id.in_(custom_game_ids))
            .options(*self.WITHOUT_BALANCE_RESULT)
            .order_by(models.CustomGameLobby.custom_game_id, models.CustomGameLobby.lobby_index)
        )
        grouped: dict[int, list[models.CustomGameLobby]] = {}
        for row in result.all():
            grouped.setdefault(row.custom_game_id, []).append(row)
        return grouped

    async def get(
        self, session: AsyncSession, custom_game_id: int, lobby_index: int
    ) -> models.CustomGameLobby | None:
        return await session.get(models.CustomGameLobby, (custom_game_id, lobby_index))

    async def create(self, session: AsyncSession, lobby: models.CustomGameLobby) -> models.CustomGameLobby:
        session.add(lobby)
        await session.flush()
        return lobby

    async def delete(self, session: AsyncSession, lobby: models.CustomGameLobby) -> None:
        await session.delete(lobby)
        await session.flush()
```

**3.4 `backend/shared/repository/casual.py`** — `list_for_custom_game` подгружает busy-строки (строки 28–34):

```python
        result = await session.scalars(
            self.select()
            .where(self.model.custom_game_id == custom_game_id)
            .options(
                selectinload(self.model.teams).selectinload(models.CasualTeam.players),
                # The rotation reader asks "was this member in the other lobby
                # then"; one eager load answers it for the whole history.
                selectinload(self.model.busy_players),
            )
            .order_by(self.model.id.desc())
        )
        return result.all()
```

**3.5 `backend/shared/repository/__init__.py`** — строки 154–160 и `__all__` (строки 301–305):

```python
from .custom_game import (
    CustomGameCoHostRepository,
    CustomGameLobbyRepository,
    CustomGamePlayerRepository,
    CustomGamePlayerRoleRepository,
    CustomGameRepository,
    CustomGameTeamNameRepository,
)
```

```python
    "CustomGameCoHostRepository",
    "CustomGameLobbyRepository",
    "CustomGamePlayerRepository",
    "CustomGamePlayerRoleRepository",
    "CustomGameRepository",
    "CustomGameTeamNameRepository",
```

**3.6 `backend/balancer-service/src/domain/mix_lobbies.py`** (новый):

```python
"""Who is actually seated in a lobby right now.

Membership in a lobby is not stored: it is the seats of that lobby's selected
balance option. One pure function answers it for every caller -- the balance
candidate filter, the pager's conflict check, the busy rows a recorded match
freezes, and the ``current_lobby`` badge on the board.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.domain.balancer.result_serializer import as_lobby_document

__all__ = ("seated_member_ids",)


def seated_member_ids(balance_result_json: Mapping[str, Any] | None, variant_index: int) -> frozenset[int]:
    """Workspace member ids seated in ``variant_index`` of one lobby's document.

    Empty for a lobby that was never balanced and for an index past the stored
    options: both mean "nobody is playing this lobby", which is what every
    caller wants to hear. A seat uuid IS the member id -- the same mapping
    ``record_outcome`` freezes into ``casual.player`` -- and a uuid that is not
    one is skipped rather than failing the read.
    """
    document = as_lobby_document(balance_result_json)
    variants = document.get("variants") if isinstance(document, Mapping) else None
    if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
        return frozenset()
    variant = variants[variant_index]
    teams = variant.get("teams") if isinstance(variant, Mapping) else None
    if not isinstance(teams, list):
        return frozenset()
    seated: set[int] = set()
    for team in teams:
        roster = team.get("roster") if isinstance(team, Mapping) else None
        if not isinstance(roster, Mapping):
            continue
        for seats in roster.values():
            if not isinstance(seats, list):
                continue
            for uuid in seats:
                try:
                    seated.add(int(uuid))
                except (TypeError, ValueError):
                    continue
    return frozenset(seated)
```

**3.7 `backend/balancer-service/src/services/custom_game.py`.** Импорты — строка `from datetime import datetime` и блок `from shared.repository import (...)` (пост-A он уже включает `UserRepository`/`WorkspaceMemberRepository`, добавленные A4 — их не трогаем, только вписываем `CustomGameLobbyRepository` в алфавитный порядок):

```python
from datetime import UTC, datetime
```

```python
from shared.repository import (
    CasualMatchRepository,
    CasualPlayerRepository,
    CasualTeamRepository,
    CustomGameCoHostRepository,
    CustomGameLobbyRepository,
    CustomGamePlayerRepository,
    CustomGamePlayerRoleRepository,
    CustomGameRepository,
    CustomGameTeamNameRepository,
    MapRepository,
    UserBalancerConfigRepository,
)
```

Конструктор `CustomGameService.__init__` — строка `co_hosts: CustomGameCoHostRepository = CustomGameCoHostRepository(),` и присваивание `self.co_hosts = co_hosts` получают соседей (kwargs плана A `players=`/`workspace_members=`/`load_missing_links=`/`enroll_member=`/`grant_player_role=` и их присваивания остаются):

```python
        co_hosts: CustomGameCoHostRepository = CustomGameCoHostRepository(),
        lobbies: CustomGameLobbyRepository = CustomGameLobbyRepository(),
```

```python
        self.co_hosts = co_hosts
        self.lobbies = lobbies
```

Новый помощник — сразу после метода `_writable`:

```python
    async def _lobby(
        self, session: AsyncSession, game: models.CustomGame, lobby_index: int
    ) -> models.CustomGameLobby:
        """One lobby row of this mix -- where every per-match fact lives.

        A mix has exactly ``lobby_count`` rows (``create`` opens them,
        ``set_lobby_count`` adds and removes the second), so a miss is a caller
        naming a lobby the mix does not run, not a row to conjure up.
        """
        lobby = await self.lobbies.get(session, game.id, lobby_index)
        if lobby is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lobby_not_found")
        return lobby
```

`create` — сразу после `await self.games.create(session, game)` (конструктор `models.CustomGame(...)` выше, с `self_role_edit=` из A1, в B1 не трогается):

```python
        await self.games.create(session, game)
        # The invariant every per-match read relies on: a mix always has its
        # lobbies. A clone copies the pool and the setup, never a played
        # session, so the fresh lobby starts empty.
        await self.lobbies.create(session, models.CustomGameLobby(custom_game_id=game.id, lobby_index=0))
```

`balance` — хвост метода, начиная с `game.balance_result_json = result`:

```python
        lobby = await self._lobby(session, game, 0)
        lobby.balance_result_json = result
        # A fresh search renumbers every option, so whatever the host had paged
        # to describes nothing now -- back to the best one.
        lobby.selected_variant_index = 0
        lobby.balanced_at = datetime.now(UTC)
        _apply_balance_result(roster, result)
        game.status = MixStatus.BALANCED
```

`set_next_map` — строка `game.next_map_id = map_id`:

```python
        lobby = await self._lobby(session, game, 0)
        lobby.next_map_id = map_id
```

`set_variant_index` — блок от `result = as_lobby_document(game.balance_result_json)` до `game.selected_variant_index = variant_index`:

```python
        lobby = await self._lobby(session, game, 0)
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        lobby.selected_variant_index = variant_index
```

`discord_lineup` — строка `result = as_lobby_document(game.balance_result_json)` и блок `next_map`:

```python
        lobby = await self._lobby(session, game, 0)
        result = as_lobby_document(lobby.balance_result_json)
```

```python
        next_map: tuple[str, str | None] | None = None
        if lobby.next_map_id is not None:
            # The gamemode is eager-loaded: an async session raises on an
            # unawaited lazy load, and the embed names the mode next to the map.
            row = await session.scalar(
                sa.select(models.Map)
                .options(selectinload(models.Map.gamemode))
                .where(models.Map.id == lobby.next_map_id)
            )
```

`swap_seats` — строка `result = copy.deepcopy(as_lobby_document(game.balance_result_json))` и запись `game.balance_result_json = result`:

```python
        lobby = await self._lobby(session, game, 0)
        result = copy.deepcopy(as_lobby_document(lobby.balance_result_json))
```

```python
        lobby.balance_result_json = result
```

`record_outcome` — блок от `if map_id is None:` до `result = as_lobby_document(...) or {}` и строка `game.next_map_id = None`:

```python
        lobby = await self._lobby(session, game, 0)
        if map_id is None:
            map_id = lobby.next_map_id
        elif await self.maps.get(session, map_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

        result = as_lobby_document(lobby.balance_result_json) or {}
```

```python
        lobby.next_map_id = None
```

`list_matches` и `rotation` теряют аргумент `options=CustomGameRepository.WITHOUT_BALANCE_RESULT` в вызове `self.get(...)`:

```python
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
```

**3.8 `backend/balancer-service/src/rpc/custom.py`.** Новый дамп лобби — перед функцией `_dump_game`:

```python
def _dump_lobby(lobby: Any, *, balance_result: bool) -> dict[str, Any]:
    """One lobby: its pager, its rolled map and when it was last balanced.

    ``balance_result`` is detail-only -- the solver document grows with every
    stored option and no list row renders it.
    """
    out: dict[str, Any] = {
        "lobby_index": lobby.lobby_index,
        "selected_variant_index": lobby.selected_variant_index,
        "next_map_id": lobby.next_map_id,
        "balanced_at": lobby.balanced_at.isoformat() if lobby.balanced_at else None,
    }
    if balance_result:
        out["balance_result"] = as_lobby_document(lobby.balance_result_json)
    return out
```

`_dump_game` получает параметр (после `activity: tuple[int, Any] | None = None,` в сигнатуре):

```python
    lobbies: list[Any] | None = None,
```

и две записи словаря — `"selected_variant_index": game.selected_variant_index,` и `"next_map_id": game.next_map_id,` вместе с их комментариями — заменяются на. **Идущие следом `"self_signup": game.self_signup,` и `"self_role_edit": game.self_role_edit,` (A1) остаются на месте:**

```python
        # How many lobbies this mix runs, and what each of them is showing: the
        # matchup, the pager and the rolled map are per-lobby facts now.
        "lobby_count": game.lobby_count,
        "lobbies": [_dump_lobby(lobby, balance_result=roster is not None) for lobby in (lobbies or [])],
```

Строка `out["balance_result"] = as_lobby_document(game.balance_result_json)` внутри `if roster is not None:` удаляется — документ уехал внутрь `lobbies`.

`_with_roster` — после строки `activity = (await custom_game_service.casual_matches.activity_for_games(...)).get(game.id)`:

```python
    lobbies = list(await custom_game_service.lobbies.list_for_game(session, game.id))
```

и оба вызова `_dump_game` в этой функции (ветка пустого ростера и основная) получают `lobbies=lobbies,`.

`_list` — после строки `team_names = await custom_game_service.team_names.mapping_for_games(session, game_ids)`:

```python
            lobbies_by_game = await custom_game_service.lobbies.list_for_games(session, game_ids)
```

и вызов `_dump_game` внутри списочной сборки получает `lobbies=lobbies_by_game.get(row.id, []),`.

Хендлер `custom.delete` (единственный `_dump_game` без ростера вне `_with_roster`) — добавить туда же:

```python
            return _dump_game(
                game,
                await _game_settings(
                    session,
                    game,
                    await custom_game_service.workspace_discord_channel_id(session, workspace_id),
                    await custom_game_service.host_points_per_win(session, game.host_user_id),
                ),
                lobbies=(await custom_game_service.lobbies.list_for_games(session, [game.id])).get(game.id, []),
                activity=(await custom_game_service.casual_matches.activity_for_games(session, [game.id])).get(game.id),
            )
```

**3.9 Миграция `backend/migrations/versions/mixlobby01_custom_game_lobby.py`:**

```python
"""Move everything about one played match onto ``balancer.custom_game_lobby``.

Revision ID: mixlobby01
Revises: mixself01
Create Date: 2026-09-26 00:00:00.000000

A mix runs up to two lobbies at once, each with its own matchup, pager, map and
pace. The four columns that described "the" match therefore stop being the
mix's: every existing mix becomes a mix with exactly one lobby, row
``lobby_index = 0``, carrying what it already had. ``balanced_at`` is seeded
from ``updated_at`` where a balance exists, so "the lineup on screen was never
recorded" answers sensibly from the first day rather than after the next
balance.

``casual.match`` gains the lobby that played it (0 for every historical row) and
``casual.match_busy_player`` records who was in the OTHER lobby at that moment,
which rotation must count as neither played nor sat out. Empty for every mix
that ran before this, which is exactly today's behaviour -- no backfill.

``downgrade()`` copies lobby 0 back and drops the rest; a second lobby's balance
is lost, because there is nowhere on ``custom_game`` to put it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mixlobby01"
down_revision: str | Sequence[str] | None = "mixself01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. The lobby table, and a row per existing mix holding its four columns.
    op.create_table(
        "custom_game_lobby",
        sa.Column("custom_game_id", sa.BigInteger(), nullable=False),
        sa.Column("lobby_index", sa.Integer(), nullable=False),
        sa.Column("selected_variant_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("balance_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("balance_result_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_map_id", sa.Integer(), nullable=True),
        sa.Column("balanced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("lobby_index BETWEEN 0 AND 1", name="ck_custom_game_lobby_index"),
        sa.ForeignKeyConstraint(["custom_game_id"], ["balancer.custom_game.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["next_map_id"], ["overwatch.map.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("custom_game_id", "lobby_index"),
        schema="balancer",
    )
    op.execute(
        """
        INSERT INTO balancer.custom_game_lobby (
            custom_game_id, lobby_index, selected_variant_index,
            balance_result_json, balance_result_version, next_map_id, balanced_at
        )
        SELECT
            id, 0, selected_variant_index,
            balance_result_json, balance_result_version, next_map_id,
            CASE WHEN balance_result_json IS NULL THEN NULL ELSE COALESCE(updated_at, created_at) END
        FROM balancer.custom_game
        """
    )

    # 2. The mix keeps none of them.
    op.drop_column("custom_game", "balance_result_version", schema="balancer")
    op.drop_column("custom_game", "balance_result_json", schema="balancer")
    op.drop_column("custom_game", "selected_variant_index", schema="balancer")
    op.drop_column("custom_game", "next_map_id", schema="balancer")

    # 3. How many lobbies the mix runs.
    op.add_column(
        "custom_game",
        sa.Column("lobby_count", sa.Integer(), server_default="1", nullable=False),
        schema="balancer",
    )
    op.create_check_constraint(
        "ck_custom_game_lobby_count", "custom_game", "lobby_count BETWEEN 1 AND 2", schema="balancer"
    )

    # 4. The host's "this one plays in A".
    op.add_column("custom_game_player", sa.Column("lobby_pin", sa.Integer(), nullable=True), schema="balancer")
    op.create_check_constraint(
        "ck_custom_game_player_lobby_pin", "custom_game_player", "lobby_pin BETWEEN 0 AND 1", schema="balancer"
    )

    # 5. Which lobby played a recorded match.
    op.add_column(
        "match",
        sa.Column("lobby_index", sa.Integer(), server_default="0", nullable=False),
        schema="casual",
    )
    op.create_check_constraint(
        "ck_casual_match_lobby_index", "match", "lobby_index BETWEEN 0 AND 1", schema="casual"
    )

    # 6. Who was in the other lobby when it was recorded.
    op.create_table(
        "match_busy_player",
        sa.Column("match_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["casual.match.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id", "workspace_member_id"),
        schema="casual",
    )


def downgrade() -> None:
    op.drop_table("match_busy_player", schema="casual")
    op.drop_constraint("ck_casual_match_lobby_index", "match", schema="casual", type_="check")
    op.drop_column("match", "lobby_index", schema="casual")

    op.drop_constraint("ck_custom_game_player_lobby_pin", "custom_game_player", schema="balancer", type_="check")
    op.drop_column("custom_game_player", "lobby_pin", schema="balancer")

    op.drop_constraint("ck_custom_game_lobby_count", "custom_game", schema="balancer", type_="check")
    op.drop_column("custom_game", "lobby_count", schema="balancer")

    op.add_column(
        "custom_game",
        sa.Column("next_map_id", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_custom_game_next_map",
        "custom_game",
        "map",
        ["next_map_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="overwatch",
        ondelete="SET NULL",
    )
    op.add_column(
        "custom_game",
        sa.Column("selected_variant_index", sa.Integer(), server_default="0", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("balance_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("balance_result_version", sa.Integer(), server_default="1", nullable=False),
        schema="balancer",
    )
    # Lobby 0 is the one a single-lobby mix always was; a second lobby's balance
    # has nowhere to go back to.
    op.execute(
        """
        UPDATE balancer.custom_game AS game
        SET selected_variant_index = lobby.selected_variant_index,
            balance_result_json = lobby.balance_result_json,
            balance_result_version = lobby.balance_result_version,
            next_map_id = lobby.next_map_id
        FROM balancer.custom_game_lobby AS lobby
        WHERE lobby.custom_game_id = game.id AND lobby.lobby_index = 0
        """
    )
    op.drop_table("custom_game_lobby", schema="balancer")
```

- [ ] **Step 4: Run test to verify it passes**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_flow.py balancer-service/tests/test_custom_public_reads.py -q
uv run pytest shared/tests/test_custom_game_models.py -q
```
Expected: PASS. Затем перегенерировать артефакты схемы и манифест:
```
uv run python scripts/export_erd.py
uv run python scripts/export_db_schema.py
bash scripts/export_openapi_schemas.sh
```
и проверить гейты:
```
uv run python scripts/export_erd.py --check
bash scripts/export_openapi_schemas.sh --check
uv run python scripts/check_rpc_docs.py
```
Expected: все три завершаются с кодом 0.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/mixlobby01_custom_game_lobby.py \
        backend/shared/models/custom_game.py backend/shared/models/casual.py \
        backend/shared/repository/custom_game.py backend/shared/repository/casual.py \
        backend/shared/repository/__init__.py \
        backend/balancer-service/src/domain/mix_lobbies.py \
        backend/balancer-service/src/services/custom_game.py \
        backend/balancer-service/src/rpc/custom.py \
        backend/balancer-service/tests/test_custom_game.py \
        backend/balancer-service/tests/test_custom_game_flow.py \
        backend/balancer-service/tests/test_custom_public_reads.py \
        backend/shared/tests/test_custom_game_models.py \
        docs/database_erd.md docs/schema.sql docs/schema.dbml \
        frontend/src/app/\(site\)/docs/schema.generated.json
git commit -m "feat(balancer): a mix's matchup, pager and map move onto a lobby row"
```

---

### Task B2: Перевод чтения микса на `lobbies[0]`

Механическая подстановка: всё, что сегодня читается из `game.balance_result` / `game.selected_variant_index` / `game.next_map_id`, читается из `game.lobbies[0]`. Видимых изменений в UI нет.

**Files:**
- Modify: `frontend/src/services/custom-game.service.ts` — тип `CustomGame` целиком (пост-A он уже несёт `self_signup` / `self_role_edit`, добавленные A8; якорь — `export type CustomGame = {`)
- Modify: `frontend/src/app/balancer/mix/PickupTeamsPanel.tsx:132-166` (чтение документа), `:460-566` (`NextMapStrip`) — A этот файл не трогает, номера актуальны
- Modify: `frontend/src/app/balancer/mix/usePickupMix.ts` — `onMutate` мутации `setVariantIndex` (A10 вставляет свои блоки выше и ниже; якорь — `const setVariantIndex = useMutation({`)
- Modify: `frontend/src/app/balancer/mix/[gameId]/page.tsx` — проп `variantIndex` у `<PickupTeamsPanel …>` (якорь — строка `variantIndex={game?.selected_variant_index ?? 0}`)
- Test: `frontend/src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx` (фикстура + 8 переопределений), `PickupMixHeader.behavior.test.tsx` (фикстура `game()`, переписанная A9), `PickupMixList.behavior.test.tsx:18-39`, `PickupCreateMixDialog.behavior.test.tsx:24-46`, `usePickupMix.behavior.test.tsx` (фикстура `game()` и утверждение пейджера; мок сервиса там переписан A10 и здесь не трогается)

**Interfaces:**
- Consumes: провод `custom.get` / `custom.list` из задачи B1 — `{id, lobby_count, lobbies: [{lobby_index, balance_result?, selected_variant_index, next_map_id, balanced_at, lineup_recorded?, matches_count?}], …}`.
- Produces:
  - `export type CustomGameLobby = { lobby_index: 0 | 1; balance_result?: unknown; selected_variant_index: number; next_map_id: number | null; balanced_at: string | null; lineup_recorded?: boolean; matches_count?: number }`
  - `CustomGame.lobby_count: 1 | 2`, `CustomGame.lobbies: CustomGameLobby[]`; полей `balance_result`, `selected_variant_index`, `next_map_id` на `CustomGame` больше нет.

- [ ] **Step 1: Write the failing test**

В `frontend/src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx` заменить фикстуру `game()` (строки 148-171, начиная с константы `CATALOGUE`) на версию с `lobbies` и добавить хелпер `lobbyRow` (имя `lobby` уже занято документом баланса на строке 121):

```tsx
const CATALOGUE = [mapRead(5, "King's Row", HYBRID), mapRead(6, "Ilios", CONTROL), mapRead(7, "Busan", CONTROL)];

/** One row of the mix's `lobbies[]` — the four columns that moved off `custom_game`. */
function lobbyRow(overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: 0,
    // The last option seats karin at damage, where she is rated 3100.
    balance_result: lobby([variant(0), variant(100), variant(200, ["8", "7"])]),
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: "2026-01-01T00:00:00Z",
    lineup_recorded: true,
    matches_count: 0,
    ...overrides,
  };
}

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 3,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday scrim",
    status: "balanced",
    settings: SETTINGS,
    created_at: null,
    lobby_count: 1,
    lobbies: [lobbyRow()],
    roster_shape: null,
    players: [],
    matches_count: 0,
    last_match_at: null,
    // Added by A8 to `CustomGame`; the fixture carries them so `bun run
    // typecheck` stays honest about the post-A shape.
    self_signup: "closed",
    self_role_edit: false,
    ...overrides,
  };
}
```

Импорт типа на строке 35 расширить: `import type { CustomGame, CustomGameLobby, CustomGameMatch } from "@/services/custom-game.service";`

Затем перевести все переопределения в тестах на `lobbies` (строки 347, 369, 409, 417, 424, 431, 458, 485):

```tsx
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: lobby([scored], { structural_min_off_role: 1 }) })] }));
```
```tsx
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: lobby([swapped]) })] }));
```
```tsx
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: lobby([variant(0)]) })] }), { variantIndex: 7 });
```
```tsx
    const scope = await mount(game({ status: "draft", lobbies: [lobbyRow({ balance_result: null, balanced_at: null })] }));
```
(последняя форма — для всех трёх тестов «offers the empty state…», «refuses to balance an empty lineup…», «balances on request…»; у второго остаётся `, { activeCount: 0 }`)
```tsx
    const scope = await mount(game({ lobbies: [lobbyRow({ next_map_id: 5 })] }), { maps: CATALOGUE });
```
```tsx
    const rolled = await mount(game({ lobbies: [lobbyRow({ next_map_id: 6 })] }), { maps: CATALOGUE, canWrite: false });
```

И добавить в конец `describe("PickupTeamsPanel", …)` тест, который прямо фиксирует новое место документа:

```tsx
  it("reads the matchup from the mix's first lobby, not from the mix itself", async () => {
    // The four columns moved to `custom_game_lobby`; a mix whose lobby row
    // carries the document must render exactly what the flat shape rendered.
    const scope = await mount(
      game({ lobbies: [lobbyRow({ next_map_id: 6 })] }),
      { maps: CATALOGUE, variantIndex: 2 },
    );

    expect(scope.textContent).toContain("karin");
    expect(scope.textContent).toContain("3100");
    expect(pagerLabel(scope)).toBe("3 / 3");
    expect(scope.querySelector('[data-testid="teams-capture"]')?.textContent).toContain("Ilios");
  });
```

- [ ] **Step 2: Run it, expected FAIL**

```bash
cd frontend && bunx vitest run src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx
```

Expected: FAIL. Тесты «renders seats and ratings…», «reads the matchup from the mix's first lobby…» и остальные падают на `No teams yet` вместо составов — `parseVariants(game?.balance_result, …)` получает `undefined`, потому что поля на `CustomGame` больше нет; тест про карту падает с `expected '…Not rolled yet…' to contain 'Ilios'`.

- [ ] **Step 3: Minimal implementation**

**3.1 `frontend/src/services/custom-game.service.ts`** — вставить тип `CustomGameLobby` прямо перед `export type CustomGame = {` и переписать сам `CustomGame` (пост-A вариант: `self_signup` / `self_role_edit` из A8 сохраняются дословно, удаляются только три верхнеуровневых поля лобби):

```ts
/**
 * One lobby of a mix — the four columns that used to sit on the mix itself
 * (`custom_game_lobby`). A mix always has exactly `lobby_count` of them, so
 * lobby 0 is an ordinary row rather than a special case, and a second lobby
 * carries its own document, its own pager position and its own next map.
 */
export type CustomGameLobby = {
  /** 0 = A, 1 = B. Also the offset of this lobby's team names: `lobby_index * 2 + team`. */
  lobby_index: 0 | 1;
  /**
   * The solver's own document for this lobby's last balance, or `null` before
   * one. Detail reads only -- `list` rows leave it out (it runs to megabytes).
   */
  balance_result?: unknown;
  /** Which option of this lobby's `balance_result` the mix is showing. */
  selected_variant_index: number;
  /** The map this lobby's next match is played on; cleared by recording it. */
  next_map_id: number | null;
  /** When this lobby was last balanced, or `null` while it never was. */
  balanced_at: string | null;
  /**
   * `false` when this lobby has been balanced and no match of its own has been
   * recorded since -- the lineup on screen is still unplayed, so anything that
   * would overwrite it asks first. Detail reads only.
   */
  lineup_recorded?: boolean;
  /** How many matches this lobby has recorded. Detail reads only. */
  matches_count?: number;
};

export type CustomGame = {
  id: number;
  workspace_id: number;
  host_user_id: number;
  /** Extra workspace members who write this mix exactly like the host (see `custom.add_co_host`). */
  co_hosts: CustomGameCoHost[];
  host_display_name: string | null;
  name: string;
  status: CustomGameStatus;
  settings: CustomGameSettings;
  created_at: string | null;
  /** How many lobbies this mix runs at once. `2` is the ceiling (CHECK server-side). */
  lobby_count: 1 | 2;
  /**
   * This mix's lobbies, ordered by `lobby_index` -- exactly `lobby_count` of
   * them. The balance document, the pager position and the next map all live
   * here now; the mix itself carries none of the three.
   */
  lobbies: CustomGameLobby[];
  /**
   * The mix's resolved team composition -- the host's own shape preference,
   * else the workspace default, else the built-in Overwatch 5v5 shape.
   */
  roster_shape: RosterShape | null;
  /** How many matches this mix has recorded -- the list's activity read, without loading the history. */
  matches_count: number;
  /** When the newest match was recorded, or `null` while none has been. */
  last_match_at: string | null;
  /** Whether players may sign themselves up, and where a signup lands. */
  self_signup: MixSelfSignup;
  /** Whether a player on the roster may reorder their own roles and flex. */
  self_role_edit: boolean;
  players?: CustomGamePlayer[];
};
```

**3.2 `frontend/src/app/balancer/mix/PickupTeamsPanel.tsx`** — строка 161 и блок `NextMapStrip`.

Заменить строку 161:

```tsx
  const lobby = game?.lobbies?.[0];
  const variants = parseVariants(lobby?.balance_result, teamNamesByIndex(game?.settings));
```

Заменить вызов `NextMapStrip` (строки 216-225) на передачу карты лобби:

```tsx
            {game ? (
              <NextMapStrip
                nextMapId={lobby?.next_map_id ?? null}
                maps={maps}
                matches={matches}
                canWrite={canWrite}
                saving={settingNextMap}
                capturing={capturing}
                onNextMapChange={onNextMapChange}
              />
            ) : null}
```

Заменить сигнатуру и два чтения в `NextMapStrip` (строки 460-482 и 564):

```tsx
function NextMapStrip({
  nextMapId,
  maps,
  matches,
  canWrite,
  saving,
  capturing,
  onNextMapChange
}: Readonly<{
  /** This lobby's own `next_map_id`, not the mix's -- the mix has none. */
  nextMapId: number | null;
  maps: MapRead[];
  matches: CustomGameMatch[];
  canWrite: boolean;
  saving: boolean;
  capturing: boolean;
  onNextMapChange: (mapId: number | null) => void;
}>) {
  const [modeId, setModeId] = useState<number | null>(null);
  const modes = rollableModes(maps);
  const nextMap = nextMapId == null ? null : (maps.find((map) => map.id === nextMapId) ?? null);
```

```tsx
          <MapCombobox maps={maps} mapId={nextMapId} onMapIdChange={onNextMapChange} />
```

Импорт типа на строке 56 расширить: `import type { CustomGame, CustomGameMatch } from "@/services/custom-game.service";` — остаётся как есть (`CustomGame` всё ещё нужен пропу `game`).

**3.3 `frontend/src/app/balancer/mix/usePickupMix.ts`** — `onMutate` внутри `const setVariantIndex = useMutation({` (A10 вставляет `mySeatQuery` выше и пять self-мутаций ниже, сам этот блок не трогает) пишет в лобби 0:

```ts
    onMutate: (variantIndex: number) => {
      const key = customGameKeys.one(workspaceId, selectedGameId ?? 0);
      const previous = queryClient.getQueryData<CustomGame>(key);
      if (previous != null) {
        queryClient.setQueryData(key, {
          ...previous,
          lobbies: previous.lobbies.map((row) =>
            row.lobby_index === 0 ? { ...row, selected_variant_index: variantIndex } : row,
          ),
        });
      }
      return { previous };
    },
```

**3.4 `frontend/src/app/balancer/mix/[gameId]/page.tsx`** — единственная строка `variantIndex={…}` у `<PickupTeamsPanel …>`:

```tsx
              variantIndex={game?.lobbies?.[0]?.selected_variant_index ?? 0}
```

**3.5 Остальные фикстуры.**

`PickupMixHeader.behavior.test.tsx` — фикстуру `game()` A9 уже переписал (она заканчивается `} as CustomGame;` и несёт `self_signup` / `self_role_edit` / `settings`). Заменить в ней три строки `balance_result` / `next_map_id` / `selected_variant_index` на пару лобби; остальное A-шное оставить дословно:

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
    created_at: "2026-01-01T00:00:00Z",
    lobby_count: 1,
    lobbies: [
      {
        lobby_index: 0,
        balance_result: null,
        selected_variant_index: 0,
        next_map_id: null,
        balanced_at: null,
        lineup_recorded: true,
        matches_count: 0,
      },
    ],
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: "555" },
    ...overrides,
  } as CustomGame;
}
```

`PickupMixList.behavior.test.tsx` — A этот файл не трогает; заменить строки 32-35 на:

```tsx
    created_at: "2026-01-02T00:00:00Z",
    lobby_count: 1,
    lobbies: [
      {
        lobby_index: 0,
        selected_variant_index: 0,
        next_map_id: null,
        balanced_at: null
      },
    ],
    self_signup: "closed",
    self_role_edit: false,
```

`PickupCreateMixDialog.behavior.test.tsx` — A этот файл не трогает; заменить строки 38-41 на:

```tsx
    created_at: "2026-01-01T00:00:00Z",
    lobby_count: 1,
    lobbies: [
      {
        lobby_index: 0,
        selected_variant_index: 0,
        next_map_id: null,
        balanced_at: null
      },
    ],
    self_signup: "closed",
    self_role_edit: false,
```

`usePickupMix.behavior.test.tsx` — A10 переписал здесь только мок сервиса и список спаев; фикстура `game()` его не касается. Заменить в ней `created_at` / `roster_shape` / `next_map_id` / `selected_variant_index` / `balance_result` на:

```tsx
    created_at: null,
    roster_shape: null,
    lobby_count: 1,
    lobbies: [
      {
        lobby_index: 0,
        balance_result: null,
        selected_variant_index: 0,
        next_map_id: null,
        balanced_at: null,
        lineup_recorded: true,
        matches_count: 0,
      },
    ],
    self_signup: "closed",
    self_role_edit: false,
```

там же — `setVariantIndex.mockResolvedValue(…)` в `beforeEach` и утверждение пейджера в тесте «pages the mix optimistically…»:

```tsx
  setVariantIndex.mockResolvedValue(
    game({
      players: [],
      lobbies: [
        {
          lobby_index: 0,
          balance_result: null,
          selected_variant_index: 2,
          next_map_id: null,
          balanced_at: null,
          lineup_recorded: true,
          matches_count: 0,
        },
      ],
    }),
  );
```

```tsx
    expect(setVariantIndex).toHaveBeenCalledWith(WORKSPACE_ID, GAME_ID, 2);
    expect(
      client.getQueryData<{ lobbies: { selected_variant_index: number }[] }>(gameKey)?.lobbies[0]
        .selected_variant_index,
    ).toBe(2);
```

- [ ] **Step 4: Run, expected PASS**

```bash
cd frontend && bunx vitest run src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx src/app/balancer/mix/PickupMixHeader.behavior.test.tsx src/app/balancer/mix/PickupMixList.behavior.test.tsx src/app/balancer/mix/PickupCreateMixDialog.behavior.test.tsx src/app/balancer/mix/usePickupMix.behavior.test.tsx
```

Expected: PASS, 5 файлов.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/custom-game.service.ts \
        frontend/src/app/balancer/mix/PickupTeamsPanel.tsx \
        frontend/src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx \
        frontend/src/app/balancer/mix/usePickupMix.ts \
        frontend/src/app/balancer/mix/usePickupMix.behavior.test.tsx \
        frontend/src/app/balancer/mix/[gameId]/page.tsx \
        frontend/src/app/balancer/mix/PickupMixHeader.behavior.test.tsx \
        frontend/src/app/balancer/mix/PickupMixList.behavior.test.tsx \
        frontend/src/app/balancer/mix/PickupCreateMixDialog.behavior.test.tsx
git commit -m "refactor(mix): the matchup, its pager and its map read the mix's first lobby"
```

---

### Task B3: Два лобби у микса — `lobby_count`, пин игрока, производное «в каком лобби»

**Files:**
- Modify: `backend/balancer-service/src/services/custom_game.py` — `_PLAYER_PATCH_FIELDS`, `create` (клон), `_apply_player_patch` (вынесен планом A) + оба его call-site, новый `set_lobby_count`
- Modify: `backend/balancer-service/src/schemas/custom_game.py` — `__all__`, `CustomGamePlayerPatch`, `CustomGameLobbyCountPatch` в конец файла
- Modify: `backend/balancer-service/src/rpc/custom.py` — `_dump_row`, `_dump_lobby`, `_dump_game`, `_with_roster`, новый субъект `set_lobby_count`
- Modify: `backend/shared/repository/casual.py` (новый `activity_for_lobbies`)
- Modify: `gateway/internal/balancer/routes.go` — новая строка после маршрута `…/custom-games/{game_id}/balance`
- Modify: `backend/balancer-service/src/openapi_schemas.py` (блок pickup-миксов в `OPERATIONS`), `backend/balancer-service/src/openapi_docs.py` (новая запись в `DOCS`)
- Test: `backend/balancer-service/tests/test_mix_lobbies.py` (новый), `backend/balancer-service/tests/test_custom_game.py`, `backend/balancer-service/tests/test_custom_public_reads.py`

**Interfaces:**
- Consumes: `models.CustomGameLobby`, `CustomGameService.lobbies`, `CustomGameService._lobby`, `_dump_lobby`, `seated_member_ids` (B1).
- Produces:
  - `async CustomGameService.set_lobby_count(session, *, workspace_id: int, custom_game_id: int, lobby_count: int, actor_user_id: int, actor_is_superuser: bool = False) -> models.CustomGame`
  - `schemas.CustomGameLobbyCountPatch{lobby_count: Literal[1, 2]}`; `schemas.CustomGamePlayerPatch.lobby_pin: int | None`
  - `rpc.balancer.custom.set_lobby_count`, маршрут `PUT /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/lobbies`
  - `CasualMatchRepository.activity_for_lobbies(session, custom_game_id) -> dict[int, tuple[int, datetime]]`
  - wire: строка ростера получает `current_lobby: 0 | 1 | null` и `lobby_pin: 0 | 1 | null`; лобби в детальном ответе — `lineup_recorded: bool` и `matches_count: int`

- [ ] **Step 1: Write the failing test**

Новый файл `backend/balancer-service/tests/test_mix_lobbies.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.balancer.result_serializer import lobby_document  # noqa: E402
from src.domain.mix_lobbies import seated_member_ids  # noqa: E402


def _payload(*teams: dict[str, list[str]]) -> dict:
    """One option as the solver emits it: a team per ``{bucket: [member id]}``."""
    return {
        "teams": [
            {
                "roster": {
                    bucket: [
                        {"uuid": uuid, "name": f"P{uuid}", "assigned_rating": 2500, "role_preferences": [bucket]}
                        for uuid in seats
                    ]
                    for bucket, seats in team.items()
                }
            }
            for team in teams
        ],
        "statistics": {},
        "benched_players": [],
    }


def test_seats_of_the_selected_option_are_the_lobby_membership() -> None:
    document = lobby_document([_payload({"tank": ["7"], "damage": ["8"]}, {"tank": ["9"], "damage": ["10"]})])
    assert seated_member_ids(document, 0) == frozenset({7, 8, 9, 10})


def test_each_option_seats_its_own_people() -> None:
    document = lobby_document(
        [
            _payload({"tank": ["7"]}, {"tank": ["8"]}),
            _payload({"tank": ["9"]}, {"tank": ["10"]}),
        ]
    )
    assert seated_member_ids(document, 1) == frozenset({9, 10})


def test_a_lobby_nobody_balanced_seats_nobody() -> None:
    assert seated_member_ids(None, 0) == frozenset()


def test_an_option_the_lobby_does_not_have_seats_nobody() -> None:
    """A stale pager must read as "empty lobby", never as an error."""
    document = lobby_document([_payload({"tank": ["7"]}, {"tank": ["8"]})])
    assert seated_member_ids(document, 4) == frozenset()


def test_a_document_stored_in_the_old_form_still_resolves() -> None:
    """Mixes balanced before the lobby form keep the solver payload verbatim."""
    stored = {"variants": [_payload({"tank": ["7"]}, {"tank": ["8"]})]}
    assert seated_member_ids(stored, 0) == frozenset({7, 8})
```

В `backend/balancer-service/tests/test_custom_game.py` — новые тесты: первый сразу после `test_create_clone_copies_the_role_edit_switch_but_closes_signup` (последний клон-тест, добавлен A1), остальные — сразу после `test_update_player_toggles_is_flex`:

```python
    async def test_create_clone_copies_the_lobby_layout(self) -> None:
        """Two lobbies and who is pinned where are how this host runs the
        session; the matchups and the history are last session's."""
        self.games.get.return_value = _game(id=5, lobby_count=2)
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, lobby_pin=1),
            _roster_row(2, 8, 1),
        ]
        self.roster.create_many = AsyncMock(side_effect=self._assign_roster_ids)

        game = await self.service.create(
            self.session,
            workspace_id=1,
            host_user_id=9,
            name="Scrim 2",
            actor_user_id=9,
            clone_from_game_id=5,
        )

        self.assertEqual(game.lobby_count, 2)
        rows = self.roster.create_many.await_args.args[1]
        self.assertEqual([row.lobby_pin for row in rows], [1, None])
        created = [call.args[1] for call in self.lobbies.create.await_args_list]
        self.assertEqual([lobby.lobby_index for lobby in created], [0, 1])
        self.assertTrue(all(lobby.balance_result_json is None for lobby in created))
```

```python
    async def test_update_player_pins_a_player_to_a_lobby(self) -> None:
        game = _game(lobby_count=2)
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]

        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"lobby_pin": 1},
            actor_user_id=9,
        )

        self.assertEqual(row.lobby_pin, 1)

    async def test_update_player_clears_a_pin_back_to_auto(self) -> None:
        game = _game(lobby_count=2)
        row = _roster_row(1, 7, 0, lobby_pin=0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [row]

        await self.service.update_player(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            workspace_member_id=7,
            patch={"lobby_pin": None},
            actor_user_id=9,
        )

        self.assertIsNone(row.lobby_pin)

    async def test_update_player_refuses_a_pin_in_a_one_lobby_mix_422(self) -> None:
        """There is nothing to pin to: the mix runs one lobby."""
        row = _roster_row(1, 7, 0)
        self.games.get.return_value = _game()
        self.roster.list_for_game.return_value = [row]

        with self.assertRaises(HTTPException) as ctx:
            await self.service.update_player(
                self.session,
                workspace_id=1,
                custom_game_id=11,
                workspace_member_id=7,
                patch={"lobby_pin": 1},
                actor_user_id=9,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(row.lobby_pin)

    async def test_set_lobby_count_two_opens_lobby_b(self) -> None:
        game = _game()
        self.games.get.return_value = game

        await self.service.set_lobby_count(
            self.session, workspace_id=1, custom_game_id=11, lobby_count=2, actor_user_id=9
        )

        self.assertEqual(game.lobby_count, 2)
        self.assertEqual(sorted(self.lobby_rows), [0, 1])
        self.assertIsNone(self.lobby_rows[1].balance_result_json)

    async def test_set_lobby_count_one_drops_lobby_b_and_every_pin(self) -> None:
        """Going back to one lobby loses B's matchup and frees everybody: a pin
        to a lobby that no longer exists would silently exclude that player
        from the next balance."""
        game = _game(lobby_count=2)
        self.lobby_rows[1] = _lobby(1, balance_result_json={"variants": []})
        pinned = _roster_row(1, 7, 0, lobby_pin=1)
        other = _roster_row(2, 8, 1, lobby_pin=0)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [pinned, other]

        await self.service.set_lobby_count(
            self.session, workspace_id=1, custom_game_id=11, lobby_count=1, actor_user_id=9
        )

        self.assertEqual(game.lobby_count, 1)
        self.assertEqual(sorted(self.lobby_rows), [0])
        self.assertIsNone(pinned.lobby_pin)
        self.assertIsNone(other.lobby_pin)

    async def test_set_lobby_count_to_the_current_value_changes_nothing(self) -> None:
        game = _game()
        self.games.get.return_value = game

        await self.service.set_lobby_count(
            self.session, workspace_id=1, custom_game_id=11, lobby_count=1, actor_user_id=9
        )

        self.lobbies.create.assert_not_awaited()
        self.lobbies.delete.assert_not_awaited()

    async def test_set_lobby_count_terminal_409(self) -> None:
        self.games.get.return_value = _game(status="completed")

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_lobby_count(
                self.session, workspace_id=1, custom_game_id=11, lobby_count=2, actor_user_id=9
            )
        self.assertEqual(ctx.exception.status_code, 409)
```

В `backend/balancer-service/tests/test_custom_public_reads.py` — тест детального ответа, после `test_list_rows_leave_the_solver_document_out`:

```python
    async def test_detail_read_says_where_every_player_sits_and_what_each_lobby_shows(self) -> None:
        """The board never derives lobby membership itself: the server reads it
        off each lobby's selected option, and says whether that option's lineup
        has been recorded yet."""
        from src.domain.balancer.result_serializer import lobby_document

        def seat(uuid: str) -> dict[str, Any]:
            return {"uuid": uuid, "name": f"P{uuid}", "assigned_rating": 2500, "role_preferences": ["tank"]}

        game = SimpleNamespace(
            id=3,
            workspace_id=7,
            host_user_id=5,
            name="Friday mix",
            status="balanced",
            lobby_count=2,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        document = lobby_document([{"teams": [{"roster": {"tank": [seat("7")]}}, {"roster": {"tank": [seat("8")]}}]}])
        balanced_at = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)
        lobbies = [
            SimpleNamespace(
                custom_game_id=3,
                lobby_index=0,
                selected_variant_index=0,
                next_map_id=None,
                balanced_at=balanced_at,
                balance_result_json=document,
            ),
            SimpleNamespace(
                custom_game_id=3,
                lobby_index=1,
                selected_variant_index=0,
                next_map_id=None,
                balanced_at=balanced_at,
                balance_result_json=None,
            ),
        ]
        rows = [
            SimpleNamespace(
                id=1,
                workspace_member_id=7,
                sort_order=0,
                participation="pool",
                role_selection_mode="all_ranked",
                is_flex=False,
                lobby_pin=None,
            ),
            SimpleNamespace(
                id=2,
                workspace_member_id=9,
                sort_order=1,
                participation="pool",
                role_selection_mode="all_ranked",
                is_flex=False,
                lobby_pin=1,
            ),
        ]

        service = MagicMock()
        service.get = AsyncMock(return_value=game)
        service.roster.list_for_game = AsyncMock(return_value=rows)
        service.lobbies.list_for_game = AsyncMock(return_value=lobbies)
        service.team_names.mapping_for_game = AsyncMock(return_value={})
        service.workspace_discord_channel_id = AsyncMock(return_value=None)
        service.host_points_per_win = AsyncMock(return_value=0)
        service.roster_shape = AsyncMock(
            return_value=SimpleNamespace(model_dump=lambda: {"slots": {"tank": 1}, "source": "default"})
        )
        service.co_hosts.user_ids_for_game = AsyncMock(return_value=[])
        service.hosts = AsyncMock(return_value={5: "Host"})
        service.casual_matches.activity_for_games = AsyncMock(return_value={})
        # Lobby 0 recorded a match after it was balanced; lobby 1 never did.
        service.casual_matches.activity_for_lobbies = AsyncMock(
            return_value={0: (2, datetime(2026, 1, 1, 22, 0, tzinfo=UTC))}
        )
        service.members = AsyncMock(return_value={})
        service.player_roles.roles_for_players = AsyncMock(return_value={})
        service.ranks.list_layer_rows = AsyncMock(return_value=[])
        service.ranks.resolve = AsyncMock(return_value={})

        with (
            patch.object(custom, "custom_game_service", service),
            patch.object(custom, "get_effective_division_grid", AsyncMock(return_value=object())),
        ):
            read = await self._call("rpc.balancer.custom.get", {"workspace_id": 7, "custom_game_id": 3})

        self.assertTrue(read["ok"], read)
        data = read["data"]
        self.assertNotIn("balance_result", data)
        by_member = {row["workspace_member_id"]: row for row in data["players"]}
        # 7 sits in lobby A's selected option; 9 is pinned to B but seated nowhere.
        self.assertEqual(0, by_member[7]["current_lobby"])
        self.assertIsNone(by_member[9]["current_lobby"])
        self.assertEqual(1, by_member[9]["lobby_pin"])
        self.assertEqual([0, 1], [lobby["lobby_index"] for lobby in data["lobbies"]])
        self.assertEqual(2, data["lobbies"][0]["matches_count"])
        self.assertTrue(data["lobbies"][0]["lineup_recorded"])
        self.assertEqual(0, data["lobbies"][1]["matches_count"])
        self.assertFalse(data["lobbies"][1]["lineup_recorded"])
        self.assertIsNotNone(data["lobbies"][0]["balance_result"])
```

- [ ] **Step 2: Run test to verify it fails**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_mix_lobbies.py -q
uv run pytest balancer-service/tests/test_custom_game.py -q -k "lobby"
uv run pytest balancer-service/tests/test_custom_public_reads.py -q -k detail
```
Expected: `test_mix_lobbies.py` — PASS (модуль сделан в B1, это его собственные тесты); `test_custom_game.py` — FAIL с `AttributeError: 'CustomGameService' object has no attribute 'set_lobby_count'` и `HTTPException: unknown fields ['lobby_pin']`; `test_custom_public_reads.py` — FAIL с `KeyError: 'current_lobby'`.

- [ ] **Step 3: Write minimal implementation**

**3.1 `backend/shared/repository/casual.py`** — после метода `activity_for_games`:

```python
    async def activity_for_lobbies(
        self, session: AsyncSession, custom_game_id: int
    ) -> dict[int, tuple[int, datetime]]:
        """``lobby_index -> (matches recorded, when the newest one was)``.

        Two lobbies keep two paces, so "game 5" in one is not "game 5" in the
        other: the embed's match number and the board's per-lobby counter both
        read this. A lobby with no matches is simply absent.
        """
        rows = await session.execute(
            sa.select(
                self.model.lobby_index,
                sa.func.count().label("matches"),
                sa.func.max(self.model.created_at).label("last_at"),
            )
            .where(self.model.custom_game_id == custom_game_id)
            .group_by(self.model.lobby_index)
        )
        return {row.lobby_index: (row.matches, row.last_at) for row in rows}
```

**3.2 `backend/balancer-service/src/services/custom_game.py`.** Константа `_PLAYER_PATCH_FIELDS` (`_SELF_PATCH_FIELDS` плана A рядом — не трогается):

```python
_PLAYER_PATCH_FIELDS = frozenset({"participation", "roles", "is_flex", "lobby_pin"})
```

`create` — конструктор `models.CustomGame(...)` получает `lobby_count` источника (`self_role_edit=` из A1 сохраняется), а вставка лобби из B1 становится циклом:

```python
        game = models.CustomGame(
            workspace_id=workspace_id,
            host_user_id=host_user_id,
            name=trimmed,
            status=MixStatus.DRAFT,
            # A clone is a new session: the host's "players edit their own roles"
            # choice carries over, the open signup window deliberately does not.
            self_role_edit=bool(source.self_role_edit) if source is not None else False,
            # How this host runs a session -- one lobby or two -- travels with
            # the clone; the matchups played in them do not.
            lobby_count=source.lobby_count if source is not None else 1,
        )
        await self.games.create(session, game)
        for lobby_index in range(game.lobby_count):
            await self.lobbies.create(
                session, models.CustomGameLobby(custom_game_id=game.id, lobby_index=lobby_index)
            )
```

и в цикле клонирования строк ростера (`for source_row in source_rows:`):

```python
        for source_row in source_rows:
            row = _new_roster_row(game.id, source_row.workspace_member_id, source_row.sort_order)
            row.role_selection_mode = source_row.role_selection_mode
            row.is_flex = source_row.is_flex
            row.lobby_pin = source_row.lobby_pin
            rows.append(row)
            cloned.append((source_row, row))
```

`_apply_player_patch` (вынесен планом A) получает ветку пина и новый keyword-only параметр `lobby_count`: проверка «микс ведёт одно лобби» нуждается в игре, которой у помощника нет. Заменить метод целиком:

```python
    async def _apply_player_patch(
        self,
        session: AsyncSession,
        row: models.CustomGamePlayer,
        patch: Mapping[str, Any],
        allowed: frozenset[str],
        *,
        lobby_count: int = 1,
    ) -> None:
        """Apply a validated lineup patch to one row, within ``allowed`` fields.

        One mutation for two callers: the host patches the whole row
        (``_PLAYER_PATCH_FIELDS``), a player only their own role order and flex
        (``_SELF_PATCH_FIELDS``). The difference between them is the gate, not
        the write -- a self edit that diverged here would be a second, subtly
        different way to set the same columns.

        ``lobby_count`` is the mix's, and only the pin reads it: pinning to a
        lobby the mix does not run is a client bug, not a silent no-op. The self
        path never carries a pin (``lobby_pin`` is not in ``_SELF_PATCH_FIELDS``),
        so it leaves the default alone.
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
        if "lobby_pin" in patch:
            if lobby_count < 2:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="lobby_pin requires a mix with two lobbies",
                )
            row.lobby_pin = patch["lobby_pin"]
```

Два call-site плана A. В `update_player` строка `await self._apply_player_patch(session, row, patch, _PLAYER_PATCH_FIELDS)` становится:

```python
        await self._apply_player_patch(session, row, patch, _PLAYER_PATCH_FIELDS, lobby_count=game.lobby_count)
```

В `self_update` строка `await self._apply_player_patch(session, ctx.row, patch, _SELF_PATCH_FIELDS)` **не меняется**: `_SELF_PATCH_FIELDS` остаётся `frozenset({"roles", "is_flex"})`, поэтому `_reject_unknown` отвечает 422 на попытку игрока выставить себе пин ещё до всякой проверки лобби.

Новый метод — после `set_participation` (перед self-методами, которые A4 вставил следом):

```python
    async def set_lobby_count(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_count: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Run this mix as one lobby or two.

        Going to two opens an empty lobby B: it has no matchup until somebody
        balances it, and lobby A is not touched. Going back to one deletes
        lobby B -- its stored matchup is lost, its recorded matches stay in the
        history -- and frees every pin, because a pin to a lobby the mix no
        longer runs would quietly exclude that player from the next balance.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if lobby_count == game.lobby_count:
            return game
        if lobby_count == 2:
            await self.lobbies.create(session, models.CustomGameLobby(custom_game_id=game.id, lobby_index=1))
        else:
            lobby = await self.lobbies.get(session, game.id, 1)
            if lobby is not None:
                await self.lobbies.delete(session, lobby)
            for row in await self.roster.list_for_game(session, game.id):
                row.lobby_pin = None
        game.lobby_count = lobby_count
        await session.flush()
        return game
```

**3.3 `backend/balancer-service/src/schemas/custom_game.py`.** В `__all__` добавить `"CustomGameLobbyCountPatch"` (записи `CustomGameSelfUpdate`/`CustomGameSelfServicePatch`/`CustomGamePostSignup` из A5/A7 остаются). `CustomGamePlayerPatch` получает поле:

```python
class CustomGamePlayerPatch(_Request):
    participation: MixParticipation | None = None
    # ``None`` is "auto": the balance places them wherever they fit. A patch that
    # does not mention the field leaves the pin exactly as it was.
    lobby_pin: int | None = Field(None, ge=0, le=1)
```

(остальные поля и валидаторы класса — без изменений). В конец файла:

```python
class CustomGameLobbyCountPatch(_Request):
    """How many lobbies the mix runs at once."""

    lobby_count: Literal[1, 2]
```

**3.4 `backend/balancer-service/src/rpc/custom.py`.** `_dump_lobby` (созданный в B1) получает счётчики:

```python
def _dump_lobby(lobby: Any, *, balance_result: bool, activity: tuple[int, Any] | None = None) -> dict[str, Any]:
    """One lobby: its pager, its rolled map, when it was last balanced -- and,
    in the detail read, its own matchup and match count.

    ``lineup_recorded`` is false while a balanced lineup has not been played:
    the UI asks for confirmation before anything that would overwrite it.
    """
    out: dict[str, Any] = {
        "lobby_index": lobby.lobby_index,
        "selected_variant_index": lobby.selected_variant_index,
        "next_map_id": lobby.next_map_id,
        "balanced_at": lobby.balanced_at.isoformat() if lobby.balanced_at else None,
    }
    if balance_result:
        matches_count, last_match_at = activity if activity is not None else (0, None)
        out["balance_result"] = as_lobby_document(lobby.balance_result_json)
        out["matches_count"] = matches_count
        out["lineup_recorded"] = lobby.balanced_at is None or (
            last_match_at is not None and last_match_at >= lobby.balanced_at
        )
    return out
```

`_dump_row` получает производное лобби и пин — сигнатура и два поля в результате:

```python
def _dump_row(
    row: Any,
    member: Any | None,
    roles: list[str] | None,
    resolved: dict[tuple[int, str], Any],
    author_ranks: dict[tuple[int, str], int],
    current_lobby: int | None = None,
) -> dict[str, Any]:
```

```python
        "is_flex": row.is_flex,
        # Where this player is right now, derived from the lobbies' selected
        # options: ``null`` means waiting for a seat. The host's pin is a
        # separate, durable wish the next balance honours.
        "current_lobby": current_lobby,
        "lobby_pin": row.lobby_pin,
        "roles": roles,
```

`_dump_game` получает ещё два параметра (рядом с `lobbies`) и передаёт их вниз:

```python
    lobbies: list[Any] | None = None,
    lobby_activity: dict[int, tuple[int, Any]] | None = None,
    current_lobby: dict[int, int] | None = None,
```

```python
        "lobbies": [
            _dump_lobby(
                lobby,
                balance_result=roster is not None,
                activity=(lobby_activity or {}).get(lobby.lobby_index),
            )
            for lobby in (lobbies or [])
        ],
```

```python
        out["players"] = [
            _dump_row(
                row,
                by_id.get(row.workspace_member_id),
                (by_player.get(row.id, []) if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT else None),
                resolved or {},
                author_ranks or {},
                (current_lobby or {}).get(row.workspace_member_id),
            )
            for row in roster
        ]
```

`_with_roster` — после чтения лобби (строка, добавленная в B1) считает производные:

```python
    lobbies = list(await custom_game_service.lobbies.list_for_game(session, game.id))
    lobby_activity = await custom_game_service.casual_matches.activity_for_lobbies(session, game.id)
    # Derived once, here: the board, the player sheet and the bot all ask the
    # same question, and none of them should re-parse a solver document.
    current_lobby = {
        member_id: lobby.lobby_index
        for lobby in lobbies
        for member_id in seated_member_ids(lobby.balance_result_json, lobby.selected_variant_index)
    }
```

и оба `_dump_game` в этой функции получают `lobbies=lobbies, lobby_activity=lobby_activity, current_lobby=current_lobby,`. Импорт наверху файла — рядом с `from src.domain.balancer.result_serializer import as_lobby_document`:

```python
from src.domain.mix_lobbies import seated_member_ids
```

Новый субъект — после блока self-субъектов плана A (т.е. после `_set_self_service`) и перед `_balance`:

```python
    @broker.subscriber("rpc.balancer.custom.set_lobby_count")
    async def _set_lobby_count(data: dict, msg: RabbitMessage) -> dict:
        """One lobby or two. Going back to one drops lobby B and every pin --
        see ``CustomGameService.set_lobby_count``."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameLobbyCountPatch, data)
            game = await custom_game_service.set_lobby_count(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                lobby_count=body.lobby_count,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="lobby", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_lobby_count", op, session_factory=_SF)
```

и в список субъектов в докстринге модуля добавить `set_lobby_count` после `set_participation` (план A уже дописал туда self-субъекты).

**3.5 `gateway/internal/balancer/routes.go`** — новая строка сразу после маршрута `POST …/custom-games/{game_id}/balance` (блоки `…/me`, `…/self-service` и `…/discord/signup` из A5/A7 стоят выше и не трогаются):

```go
	// One lobby or two. 1->2 opens an empty lobby B; 2->1 deletes it and frees
	// every pin, since a pin to a lobby the mix no longer runs would quietly
	// exclude that player from the next balance.
	{Method: "PUT", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/lobbies", Queue: "rpc.balancer.custom.set_lobby_count", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
```

**3.6 `backend/balancer-service/src/openapi_schemas.py`** — в блок `# ── pickup mixes`, рядом с `"rpc.balancer.custom.set_participation"`:

```python
    "rpc.balancer.custom.set_lobby_count": Op(request=custom_game.CustomGameLobbyCountPatch),
```

**3.7 `backend/balancer-service/src/openapi_docs.py`** — новая запись в `DOCS`, перед записью `"rpc.balancer.custom.hard_delete"`:

```python
    "rpc.balancer.custom.set_lobby_count": {
        "summary": "Set custom game lobby count",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Runs the mix as one lobby or two. Going to two opens an empty second lobby, leaving the "
            "first untouched; going back to one deletes the second lobby together with its stored "
            "matchup and clears every player's lobby pin. Matches already recorded for the second "
            "lobby stay in the history and in the statistics."
        ),
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_mix_lobbies.py balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_contract.py balancer-service/tests/test_custom_public_reads.py -q
bash scripts/export_openapi_schemas.sh && bash scripts/export_openapi_schemas.sh --check
uv run python scripts/check_rpc_docs.py
uv run python scripts/export_erd.py --check
cd ../gateway && go test ./internal/balancer/...
```
Expected: PASS; гейты — код 0. Go-тест `TestMixSelfServiceRoutes` (A5/A7) проверяет наличие своих ключей, а не точное множество маршрутов, поэтому новый `…/lobbies` его не ломает.

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/custom_game.py \
        backend/balancer-service/src/schemas/custom_game.py \
        backend/balancer-service/src/rpc/custom.py \
        backend/balancer-service/src/openapi_schemas.py \
        backend/balancer-service/src/openapi_docs.py \
        backend/shared/repository/casual.py \
        gateway/internal/balancer/routes.go \
        gateway/internal/openapi/schemas.json \
        backend/balancer-service/tests/test_mix_lobbies.py \
        backend/balancer-service/tests/test_custom_game.py \
        backend/balancer-service/tests/test_custom_public_reads.py
git commit -m "feat(balancer): a mix runs one lobby or two, with per-player pins"
```

---

### Task B4: Операции лобби — карта, пейджер, обмен, запись, отмена, Discord, ротация

**Files:**
- Modify: `backend/balancer-service/src/schemas/custom_game.py` — новый базовый `_LobbyScoped` и пять тел (`CustomGameNextMapPatch`, `CustomGameVariantIndexPatch`, `CustomGameSeatSwap`, `CustomGameRecordOutcome`, `CustomGamePostDiscord`)
- Modify: `backend/balancer-service/src/services/custom_game.py` — `set_next_map`, `set_variant_index`, `discord_lineup`, `swap_seats`, `record_outcome`, `undo_last_match`, `rotation`, новая константа `LOBBY_LABELS`
- Modify: `backend/balancer-service/src/domain/mix_discord.py` — только `build_lineup_embed` (`signup_card` и `__all__` из A7 не трогаются)
- Modify: `backend/shared/repository/casual.py` — `newest_id_for_game` → `newest_id_for_lobby`, новый `set_busy_players`
- Modify: `backend/balancer-service/src/rpc/custom.py` — `_dump_match` и обработчики `set_next_map`, `set_variant_index`, `post_discord`, `swap_seats`, `record_outcome`, `rotation`
- Modify: `gateway/internal/balancer/routes.go` — маршрут `GET …/custom-games/{game_id}/rotation` получает `AllQuery`
- Modify: `backend/balancer-service/src/openapi_docs.py` (шесть записей `DOCS`), `backend/balancer-service/src/openapi_schemas.py` (новая запись `rotation` в `OPERATIONS`)
- Test: `backend/balancer-service/tests/test_custom_game.py`, `backend/balancer-service/tests/test_mix_discord.py`

**Interfaces:**
- Consumes: `CustomGameService._lobby`, `seated_member_ids`, `models.CasualMatchBusyPlayer`, `CasualMatchRepository.activity_for_lobbies` (B1, B3).
- Produces:
  - `set_next_map(..., lobby_index: int = 0, map_id, ...)`, `set_variant_index(..., lobby_index: int = 0, variant_index, ...)`, `swap_seats(..., lobby_index: int = 0, variant_index, first_uuid, second_uuid, ...)`, `record_outcome(..., lobby_index: int = 0, winner, variant_index, map_id=None, ...)`, `discord_lineup(..., lobby_index: int = 0, variant_index, ...)`, `rotation(session, *, workspace_id, custom_game_id, lobby_index: int = 0)`
  - схемы `CustomGameNextMapPatch/CustomGameVariantIndexPatch/CustomGameSeatSwap/CustomGameRecordOutcome/CustomGamePostDiscord` с полем `lobby_index: int = Field(0, ge=0, le=1)`
  - `CasualMatchRepository.newest_id_for_lobby(session, custom_game_id, lobby_index) -> int | None`, `CasualMatchRepository.set_busy_players(session, match_id, workspace_member_ids) -> None`
  - `build_lineup_embed(..., lobby_label: str | None = None)`
  - wire: строка матча получает `lobby_index`

- [ ] **Step 1: Write the failing test**

В `backend/balancer-service/tests/test_custom_game.py` модульный помощник `_match` получает busy-строки:

```python
def _match(
    match_id: int,
    *,
    created_at: int,
    home: list,
    away: list,
    scores: tuple[int, int] = (1, 0),
    busy: Sequence[int] = (),
    **overrides,
) -> SimpleNamespace:
    """One frozen ``casual.match`` with both scored sides, their seats, and who
    was playing the mix's other lobby at the time."""
    fields = {
        "id": match_id,
        "created_at": created_at,
        "lobby_index": 0,
        "map_id": None,
        "recorded_by": 9,
        "points_per_win_applied": None,
        "busy_players": [_row(workspace_member_id=member_id) for member_id in busy],
        "teams": [
            _row(
                id=match_id * 100 + index,
                side=side,
                name=f"Team {index}",
                score=score,
                players=[_seat_row(spec) for spec in members],
            )
            for index, (side, members, score) in enumerate(
                ((CasualTeamSide.HOME, home, scores[0]), (CasualTeamSide.AWAY, away, scores[1])), start=1
            )
        ],
    }
    fields.update(overrides)
    return _row(**fields)
```

(в импорты файла добавить `from collections.abc import Sequence`).

В `setUp` строку `self.casual_matches.newest_id_for_game = AsyncMock(return_value=None)` заменить и добавить новые заглушки:

```python
        self.casual_matches.newest_id_for_lobby = AsyncMock(return_value=None)
        self.casual_matches.set_busy_players = AsyncMock()
        self.casual_matches.activity_for_lobbies = AsyncMock(return_value={})
```

Три существующих теста отмены переводятся на новое имя — `test_undo_only_applies_to_the_newest_match`, `test_undo_reverses_the_points_the_match_stored`, `test_undo_a_draw_deletes_without_touching_ranks`: `self.casual_matches.newest_id_for_game.return_value = …` → `self.casual_matches.newest_id_for_lobby.return_value = …`. Два теста Discord: в `test_discord_lineup_posts_to_the_workspace_channel` строка `self.casual_matches.activity_for_games = AsyncMock(return_value={})` → `self.casual_matches.activity_for_lobbies = AsyncMock(return_value={})`, в `test_discord_lineup_describes_the_next_match_of_this_mix` — `self.casual_matches.activity_for_games = AsyncMock(return_value={11: (3, datetime(2026, 1, 1, 20, 0))})` → `self.casual_matches.activity_for_lobbies = AsyncMock(return_value={0: (3, datetime(2026, 1, 1, 20, 0))})`.

Новые тесты (в конец класса, перед `test_hard_delete_removes_the_game_row`):

```python
    async def test_per_lobby_writes_touch_only_their_own_lobby(self) -> None:
        """Lobby B rolls its own map and pages its own option; lobby A keeps
        the map and the option the host set for it."""
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, next_map_id=42, balance_result_json=lobby_document([{"teams": []}]))
        self.lobby_rows[1] = _lobby(
            1, balance_result_json=lobby_document([{"teams": []}, {"teams": []}])
        )
        self.maps.get = AsyncMock(return_value=_row(id=5, name="Busan"))

        await self.service.set_next_map(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, map_id=5, actor_user_id=9
        )
        await self.service.set_variant_index(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, variant_index=1, actor_user_id=9
        )

        self.assertEqual(self.lobby_rows[1].next_map_id, 5)
        self.assertEqual(self.lobby_rows[1].selected_variant_index, 1)
        self.assertEqual(self.lobby_rows[0].next_map_id, 42)
        self.assertEqual(self.lobby_rows[0].selected_variant_index, 0)

    async def test_set_variant_index_refuses_an_option_seating_the_other_lobby_409(self) -> None:
        """Two co-hosts page at once: an option that seats somebody lobby A has
        already put on the floor is not a matchup anybody can play."""
        seated = [{"teams": [{"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}}, {"roster": {}}]}]
        contested = [
            {"teams": [{"roster": {"tank": [self._seat("8", "Bravo", 2900, "tank")]}}, {"roster": {}}]},
            {"teams": [{"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}}, {"roster": {}}]},
        ]
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(seated))
        self.lobby_rows[1] = _lobby(1, balance_result_json=lobby_document(contested))

        with self.assertRaises(HTTPException) as ctx:
            await self.service.set_variant_index(
                self.session, workspace_id=1, custom_game_id=11, lobby_index=1, variant_index=1, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "seat_conflict")
        self.assertEqual(self.lobby_rows[1].selected_variant_index, 0)

    async def test_record_outcome_stamps_its_lobby_and_who_was_in_the_other(self) -> None:
        """The match belongs to a lobby, and it remembers who was unavailable --
        playing next door -- so rotation does not read that as sitting out."""
        playing = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                    {"roster": {"tank": [self._seat("8", "Bravo", 2900, "tank")]}},
                ]
            }
        ]
        elsewhere = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    {"roster": {"tank": [self._seat("10", "Delta", 3000, "tank")]}},
                ]
            }
        ]
        self.games.get.return_value = _game(status="balanced", lobby_count=2)
        self.lobby_rows[0] = _lobby(0, next_map_id=42, balance_result_json=lobby_document(elsewhere))
        self.lobby_rows[1] = _lobby(1, next_map_id=7, balance_result_json=lobby_document(playing))

        await self.service.record_outcome(
            self.session,
            workspace_id=1,
            custom_game_id=11,
            lobby_index=1,
            winner=1,
            variant_index=0,
            actor_user_id=9,
        )

        created_match = self.casual_matches.create.await_args.args[1]
        self.assertEqual(created_match.lobby_index, 1)
        self.assertEqual(created_match.map_id, 7)
        self.casual_matches.set_busy_players.assert_awaited_once_with(self.session, 501, [9, 10])
        # Only this lobby's roll is consumed; lobby A still has its own.
        self.assertIsNone(self.lobby_rows[1].next_map_id)
        self.assertEqual(self.lobby_rows[0].next_map_id, 42)

    async def test_record_outcome_of_a_one_lobby_mix_records_no_busy_players(self) -> None:
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"tank": [self._seat("7", "Alpha", 3200, "tank")]}},
                        {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(status="balanced")
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(result["variants"]))

        await self.service.record_outcome(
            self.session, workspace_id=1, custom_game_id=11, winner=1, variant_index=0, actor_user_id=9
        )

        self.assertEqual(self.casual_matches.create.await_args.args[1].lobby_index, 0)
        self.casual_matches.set_busy_players.assert_not_awaited()

    async def test_undo_targets_the_newest_match_of_its_own_lobby(self) -> None:
        """Lobby A's last match is undoable even while lobby B has recorded a
        newer one: the rank book compounds per mix, but the pair a host is
        looking at is their own lobby's."""
        self.games.get.return_value = _game(lobby_count=2)
        self.casual_matches.get_for_game.return_value = _match(
            501, created_at=1, home=[7], away=[9], lobby_index=0
        )
        self.casual_matches.newest_id_for_lobby.return_value = 501

        await self.service.undo_last_match(
            self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
        )

        self.casual_matches.newest_id_for_lobby.assert_awaited_once_with(self.session, 11, 0)
        self.casual_matches.delete.assert_awaited_once()

    async def test_undo_refuses_an_older_match_of_the_same_lobby_409(self) -> None:
        self.games.get.return_value = _game(lobby_count=2)
        self.casual_matches.get_for_game.return_value = _match(
            501, created_at=1, home=[7], away=[9], lobby_index=1
        )
        self.casual_matches.newest_id_for_lobby.return_value = 503

        with self.assertRaises(HTTPException) as ctx:
            await self.service.undo_last_match(
                self.session, workspace_id=1, custom_game_id=11, match_id=501, actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.casual_matches.newest_id_for_lobby.assert_awaited_once_with(self.session, 11, 1)
        self.casual_matches.delete.assert_not_awaited()

    async def test_discord_lineup_names_the_lobby_and_counts_its_own_games(self) -> None:
        """Two lobbies keep two paces: "game 3" of B is not "game 3" of A."""
        result = {
            "variants": [
                {
                    "teams": [
                        {"roster": {"Tank": [{"uuid": "1", "name": "Ana", "assigned_rating": 3000}]}},
                        {"roster": {"Tank": [{"uuid": "2", "name": "Bob", "assigned_rating": 2900}]}},
                    ]
                }
            ]
        }
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[1] = _lobby(1, balance_result_json=lobby_document(result["variants"]))
        self.team_names.mapping_for_game.return_value = {}
        self.casual_matches.activity_for_lobbies = AsyncMock(
            return_value={0: (5, datetime(2026, 1, 1, 20, 0)), 1: (2, datetime(2026, 1, 1, 20, 5))}
        )
        self.session.scalar = AsyncMock(return_value={"mix_discord_channel_id": "555"})

        _channel_id, embed = await self.service.discord_lineup(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, variant_index=0, actor_user_id=9
        )

        self.assertEqual(embed["title"], "Scrim — Лобби B · игра 3")

    async def test_rotation_of_one_lobby_ignores_whoever_is_playing_the_other(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2 -> one lobby is four seats; 9 and 10 are on the
        # floor in lobby A and 11 is pinned to A, so lobby B ranks 7 and 8 only.
        seated = [
            {
                "teams": [
                    {"roster": {"tank": [self._seat("9", "Charlie", 2600, "tank")]}},
                    {"roster": {"tank": [self._seat("10", "Delta", 3000, "tank")]}},
                ]
            }
        ]
        self.games.get.return_value = _game(lobby_count=2)
        self.lobby_rows[0] = _lobby(0, balance_result_json=lobby_document(seated))
        self.lobby_rows[1] = _lobby(1)
        self.host_prefs.get_by_user.return_value = _prefs(role_slots_json={"tank": 1, "damage": 1})
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
            _roster_row(4, 10, 3, created_at=0),
            _roster_row(5, 11, 4, created_at=0, lobby_pin=0),
        ]

        recommendations = await self.service.rotation(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1
        )

        self.assertEqual(sorted(rec.member_id for rec in recommendations), [7, 8])
        self.assertTrue(all(rec.status is not RotationStatus.SHOULD_REST for rec in recommendations))
```

В `backend/balancer-service/tests/test_mix_discord.py` — один тест ярлыка, в конец файла:

```python
def test_a_two_lobby_mix_says_which_lobby_the_lineup_is_for() -> None:
    """Both lobbies post into the same channel, so the embed has to say which
    one it describes -- and each counts its own games."""
    assert _embed(match_number=3, lobby_label="B")["title"] == "Friday Scrim — Лобби B · игра 3"
    assert _embed(match_number=3)["title"] == "Friday Scrim — Match 3"
```

- [ ] **Step 2: Run test to verify it fails**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_custom_game.py -q -k "lobby or undo or discord_lineup or rotation"
uv run pytest balancer-service/tests/test_mix_discord.py -q
```
Expected: FAIL — `TypeError: set_next_map() got an unexpected keyword argument 'lobby_index'` и `TypeError: build_lineup_embed() got an unexpected keyword argument 'lobby_label'`.

- [ ] **Step 3: Write minimal implementation**

**3.1 `backend/balancer-service/src/schemas/custom_game.py`** — общий миксин и пять тел (классы `CustomGameSelfUpdate`/`CustomGameSelfServicePatch`/`CustomGamePostSignup` из A5/A7 остаются на `_Request`):

```python
class _LobbyScoped(_Request):
    """Every per-match write names its lobby; ``0`` is the only one a
    single-lobby mix has, which is why it is the default."""

    lobby_index: int = Field(0, ge=0, le=1)


class CustomGameNextMapPatch(_LobbyScoped):
    """``null`` clears the pick; the next match then records with no map."""

    map_id: int | None


class CustomGameVariantIndexPatch(_LobbyScoped):
    """Which stored balance option the lobby shows, for every viewer at once."""

    variant_index: int = Field(ge=0)
```

`CustomGamePostDiscord`, `CustomGameSeatSwap` и `CustomGameRecordOutcome` меняют базовый класс `_Request` → `_LobbyScoped`; их поля и валидаторы не трогаются.

**3.2 `backend/shared/repository/casual.py`** — метод `newest_id_for_game` заменяется:

```python
    async def newest_id_for_lobby(self, session: AsyncSession, custom_game_id: int, lobby_index: int) -> int | None:
        """Id of the most recently recorded match OF THIS LOBBY, or ``None``.

        Per lobby, not per mix: undo compounds inside one lobby's rank history,
        and a host looking at lobby A must be able to take back A's last result
        while B has already recorded a newer one.
        """
        return await session.scalar(
            sa.select(sa.func.max(self.model.id)).where(
                self.model.custom_game_id == custom_game_id,
                self.model.lobby_index == lobby_index,
            )
        )
```

и в конец класса:

```python
    async def set_busy_players(
        self, session: AsyncSession, match_id: int, workspace_member_ids: Sequence[int]
    ) -> None:
        """Freeze who was playing the mix's other lobby when this match landed."""
        session.add_all(
            [
                models.CasualMatchBusyPlayer(match_id=match_id, workspace_member_id=member_id)
                for member_id in workspace_member_ids
            ]
        )
        await session.flush()
```

**3.3 `backend/balancer-service/src/services/custom_game.py`.** Импорт — рядом с `from src.domain.mix_discord import build_lineup_embed`:

```python
from src.domain.mix_lobbies import seated_member_ids
```

`set_next_map` — сигнатура получает `lobby_index: int = 0` (после `custom_game_id`), тело — строка `game.next_map_id = map_id`:

```python
        lobby = await self._lobby(session, game, lobby_index)
        lobby.next_map_id = map_id
```

`set_variant_index` — сигнатура получает `lobby_index: int = 0`, тело — блок от `result = as_lobby_document(...)` до присваивания выбранного варианта:

```python
        lobby = await self._lobby(session, game, lobby_index)
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        if game.lobby_count == 2:
            # An option that seats somebody the other lobby has already put on
            # the floor is not a matchup anyone can play; the host picks another
            # or re-balances. Cheaper and clearer than silently benching them.
            other = await self._lobby(session, game, 1 - lobby_index)
            busy = seated_member_ids(other.balance_result_json, other.selected_variant_index)
            if busy & seated_member_ids(lobby.balance_result_json, variant_index):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="seat_conflict")
        lobby.selected_variant_index = variant_index
```

`swap_seats` — сигнатура получает `lobby_index: int = 0`, а строки `result = copy.deepcopy(as_lobby_document(lobby.balance_result_json))` и `lobby.balance_result_json = result` (после B1) читают/пишут `lobby = await self._lobby(session, game, lobby_index)` вместо лобби 0.

`discord_lineup` — сигнатура получает `lobby_index: int = 0`; строка чтения документа и блок от `team_names = …` до вызова `build_lineup_embed(...)`:

```python
        lobby = await self._lobby(session, game, lobby_index)
        result = as_lobby_document(lobby.balance_result_json)
```

```python
        # Team names are stored by GLOBAL index (``lobby_index * 2 + team``), so
        # the embed gets its own two renumbered to 0-1: ``build_lineup_embed``
        # names columns by their position inside the variant it was handed.
        team_names = {
            index - lobby_index * 2: name
            for index, name in (await self.team_names.mapping_for_game(session, game.id)).items()
            if 0 <= index - lobby_index * 2 < 2
        }
        # Per lobby: two lobbies keep two paces, so "game 5" in one is not
        # "game 5" in the other.
        activity = await self.casual_matches.activity_for_lobbies(session, game.id)
        matches_count = activity.get(lobby_index, (0, None))[0]
        next_map: tuple[str, str | None] | None = None
        if lobby.next_map_id is not None:
            row = await session.scalar(
                sa.select(models.Map)
                .options(selectinload(models.Map.gamemode))
                .where(models.Map.id == lobby.next_map_id)
            )
            if row is not None:
                next_map = (row.name, row.gamemode.name if row.gamemode is not None else None)

        embed = build_lineup_embed(
            mix_name=game.name,
            match_number=matches_count + 1,
            variant=variant,
            players=_lobby_players(result),
            team_names=team_names,
            next_map=next_map,
            points_per_win=await self.host_points_per_win(session, game.host_user_id) or None,
            # Both lobbies post into the same channel, so a two-lobby mix says
            # which one this lineup is; a one-lobby mix has nothing to qualify.
            lobby_label=LOBBY_LABELS[lobby_index] if game.lobby_count == 2 else None,
        )
```

Константа рядом с `_MAX_TEAM_NAME_LEN` (после A4 там же живут `_SELF_PATCH_FIELDS` и таблица статусов блокеров — их не трогаем):

```python
#: Board-facing name of a lobby; the wire and the database speak indexes.
LOBBY_LABELS = ("A", "B")
```

`record_outcome` — сигнатура получает `lobby_index: int = 0`; три блока тела (чтение карты и документа лобби; создание `CasualMatch`; сброс карты):

```python
        lobby = await self._lobby(session, game, lobby_index)
        if map_id is None:
            map_id = lobby.next_map_id
        elif await self.maps.get(session, map_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

        result = as_lobby_document(lobby.balance_result_json) or {}
```

```python
        match = models.CasualMatch(
            custom_game_id=game.id,
            lobby_index=lobby_index,
            map_id=map_id,
            recorded_by=actor_user_id,
            # Frozen on the match so :meth:`undo_last_match` rolls back what was
            # actually applied, not what the knob says by then.
            points_per_win_applied=(points_per_win if (points_per_win and winner in (1, 2)) else None),
        )
        await self.casual_matches.create(session, match)
        if game.lobby_count == 2:
            # Whoever was on the floor next door neither played this match nor
            # sat it out; rotation must not read their absence as a rest.
            other = await self._lobby(session, game, 1 - lobby_index)
            busy = seated_member_ids(other.balance_result_json, other.selected_variant_index)
            if busy:
                await self.casual_matches.set_busy_players(session, match.id, sorted(busy))
```

```python
        lobby.next_map_id = None
```

`undo_last_match` — проверка «самый новый матч»:

```python
        if await self.casual_matches.newest_id_for_lobby(session, game.id, match.lobby_index) != match.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Only the most recent match of this lobby can be undone"
            )
```

`rotation` — сигнатура и тело метода:

```python
    async def rotation(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int, lobby_index: int = 0
    ) -> list[RotationRecommendation]:
```

```python
        roster = list(await self.roster.list_for_game(session, game.id))
        if not roster:
            return []

        candidates = roster
        if game.lobby_count == 2:
            # The same candidate rule the single-lobby balance uses: whoever is
            # on the floor next door is playing, and whoever is pinned there is
            # not this lobby's to seat.
            other_index = 1 - lobby_index
            other = await self._lobby(session, game, other_index)
            busy = seated_member_ids(other.balance_result_json, other.selected_variant_index)
            candidates = [
                row
                for row in roster
                if row.workspace_member_id not in busy and row.lobby_pin != other_index
            ]
            if not candidates:
                return []

        histories = await self._rotation_histories(session, game, candidates)

        role_mask = (await self.roster_shape(session, workspace_id=workspace_id, host_user_id=game.host_user_id)).slots
        players_per_team = sum(role_mask.values())
        if players_per_team <= 0:
            usable_count = len(candidates)
        else:
            usable_count = (len(candidates) // players_per_team) * players_per_team
            if game.lobby_count == 2:
                # One lobby is exactly two teams; the rest of the pool is the
                # other lobby's business.
                usable_count = min(usable_count, 2 * players_per_team)
        return recommend_rotation(histories, usable_count=usable_count)
```

**3.4 `backend/balancer-service/src/domain/mix_discord.py`** — только функция `build_lineup_embed` (`signup_card` и `__all__`, добавленные A7, не трогаются). Сигнатура:

```python
def build_lineup_embed(
    *,
    mix_name: str,
    match_number: int,
    variant: Mapping[str, Any],
    players: Mapping[str, Any],
    team_names: Mapping[int, str],
    next_map: tuple[str, str | None] | None,
    points_per_win: int | None,
    lobby_label: str | None = None,
) -> dict[str, Any]:
```

(докстринг дополняется абзацем)

```python
    ``lobby_label`` names the lobby when the mix runs two of them: both post
    into the same channel, and "game 3" of one is not "game 3" of the other. A
    single-lobby mix passes ``None`` and reads exactly as it always did.
```

и запись `"title"` в собираемом эмбеде:

```python
        "title": (
            f"{mix_name} — Match {match_number}"
            if lobby_label is None
            else f"{mix_name} — Лобби {lobby_label} · игра {match_number}"
        ),
```

**3.5 `backend/balancer-service/src/rpc/custom.py`.** `_dump_match` получает поле сразу после `"id"`:

```python
        "id": match.id,
        # Which lobby played it: the history chips and the per-lobby undo both
        # read this.
        "lobby_index": match.lobby_index,
```

Хендлеры пробрасывают `lobby_index` из тела — `_set_next_map`, `_set_variant_index`, `_swap_seats`, `_record_outcome` и `_post_discord` получают соседнюю строку `lobby_index=body.lobby_index,` в вызове сервиса (хендлер `_post_signup`, добавленный A7 следом за `_post_discord`, не трогается: его тело — `CustomGamePostSignup`, без лобби). `_rotation`:

```python
            recommendations = await custom_game_service.rotation(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                # Query param: the rotation is a read, and which lobby it ranks
                # for is part of the question, not a body.
                lobby_index=c.q1(data, "lobby_index", int, 0),
            )
```

**3.6 `gateway/internal/balancer/routes.go`** — маршрут `GET …/custom-games/{game_id}/rotation` получает `AllQuery`:

```go
	{Method: "GET", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/rotation", Queue: "rpc.balancer.custom.rotation", IDParam: "game_id", Path: []string{"workspace_id"}, AllQuery: true, Auth: edge.AuthNone, Timeout: fastReadTimeout},
```

**3.7 `backend/balancer-service/src/openapi_docs.py`** — шесть записей `DOCS` переписываются целиком (адресуются по ключу-субъекту; записи A5/A7 рядом не трогаются):

```python
    "rpc.balancer.custom.set_next_map": {
        "summary": "Set custom game next map",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Names the map the lobby's next match is played on -- rolled or picked by a host ahead of "
            "the lobby -- or clears it with null. The next recorded match takes this map unless the "
            "outcome names one explicitly, and clears it either way. The lobby_index field names which "
            "lobby's roll this is; a single-lobby mix leaves it at 0. 404 when "
            "the map is not in the catalogue."
        ),
    },
    "rpc.balancer.custom.set_variant_index": {
        "summary": "Set custom game shown balance option",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Pages one lobby to one of the balance options its last run produced, for every viewer at "
            "once -- the option on screen is a fact about the lobby, not about one browser. "
            "404 when the index points past the stored options, and 409 seat_conflict when the option "
            "would seat somebody the mix's other lobby has already put on the floor. Re-balancing "
            "resets it to the first option."
        ),
    },
    "rpc.balancer.custom.post_discord": {
        "summary": "Post custom game lineup to Discord",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Queues an embed of one balance option's teams, the next map and the points at stake "
            "to the workspace-wide mix channel and returns immediately -- delivery is the bot's, "
            "and nothing about the mix changes. A two-lobby mix names the lobby in the embed title and "
            "numbers the match within that lobby. 409 when the workspace has "
            "no mix channel configured and 404 when the balance option is missing."
        ),
    },
    "rpc.balancer.custom.record_outcome": {
        "summary": "Record custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Freezes one played match of a balance option into the mix's history, moving both teams' "
            "ranks in the host's book by points_per_win when a winner is given and redeeming every "
            "seat's must_play pin back to the pool. The match is stamped with the lobby that played it "
            "and with whoever was playing the other lobby at that moment, whom rotation then counts as "
            "neither played nor sat out. Repeatable until the mix is closed."
        ),
    },
    "rpc.balancer.custom.undo_match": {
        "summary": "Undo custom game match",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Deletes the lobby's most recent match and gives back exactly the rank points it applied, "
            "read from the match itself rather than the mix's current points_per_win. "
            "404 when the match belongs to another mix and 409 when a newer match of the SAME lobby "
            "exists, since the rank book compounds. must_play pins the recording redeemed are not "
            "restored."
        ),
    },
    "rpc.balancer.custom.rotation": {
        "summary": "Get custom game rotation hints",
        "description": (
            "Permission: public; no authentication required. Recommends who is owed the next seat and "
            "who should sit out, computed from this mix's own match history, read-only. The optional "
            "lobby_index query parameter ranks the candidates of one lobby -- whoever is seated in the "
            "other lobby or pinned to it is left out -- and splits at that lobby's seat count."
        ),
    },
```

**3.8 `backend/balancer-service/src/openapi_schemas.py`** — ротация получает свой query-параметр; новая запись в блоке pickup-миксов, рядом с `"rpc.balancer.custom.record_outcome"`:

```python
    "rpc.balancer.custom.rotation": Op(
        query_params=(
            QueryParam(
                "lobby_index",
                "integer",
                description="Which lobby to rank candidates for (0 or 1); defaults to 0.",
            ),
        )
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_contract.py balancer-service/tests/test_mix_discord.py balancer-service/tests/test_custom_public_reads.py -q
bash scripts/export_openapi_schemas.sh && bash scripts/export_openapi_schemas.sh --check
uv run python scripts/check_rpc_docs.py
cd ../gateway && go test ./internal/balancer/...
```
Expected: PASS; гейты — код 0.

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/custom_game.py \
        backend/balancer-service/src/schemas/custom_game.py \
        backend/balancer-service/src/domain/mix_discord.py \
        backend/balancer-service/src/rpc/custom.py \
        backend/balancer-service/src/openapi_docs.py \
        backend/balancer-service/src/openapi_schemas.py \
        backend/shared/repository/casual.py \
        gateway/internal/balancer/routes.go \
        gateway/internal/openapi/schemas.json \
        backend/balancer-service/tests/test_custom_game.py \
        backend/balancer-service/tests/test_mix_discord.py
git commit -m "feat(balancer): every per-match mix write names its lobby"
```

---

### Task B5: Ротация не считает чужое лобби ни игрой, ни отдыхом

**Files:**
- Modify: `backend/balancer-service/src/services/custom_game.py` — `_rotation_histories`
- Test: `backend/balancer-service/tests/test_custom_game.py`

**Interfaces:**
- Consumes: `models.CasualMatch.busy_players` (B1), `CasualMatchRepository.set_busy_players` (B4).
- Produces: `_rotation_histories` пропускает матч для участника, записанного в его `busy_players`; `played` такого игрока короче на этот матч.

- [ ] **Step 1: Write the failing test**

В `backend/balancer-service/tests/test_custom_game.py`, рядом с остальными тестами ротации (сразу после `test_rotation_ignores_maps_played_before_a_member_joined`):

```python
    async def test_rotation_counts_a_match_spent_in_the_other_lobby_as_neither(self) -> None:
        from src.domain.mix_rotation import RotationStatus

        # players_per_team=2, pool of 3 -> one seat short. Two maps were played
        # in lobby A; 9 spent the first of them on the floor of lobby B.
        self.games.get.return_value = _game()
        self.host_prefs.get_by_user.return_value = _prefs(role_slots_json={"tank": 1, "damage": 1})
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
        ]
        self.casual_matches.list_for_custom_game = AsyncMock(
            return_value=[
                _match(2, created_at=2, home=[7], away=[8]),  # 7 & 8 played, 9 sat
                _match(1, created_at=1, home=[7], away=[8], busy=[9]),  # 9 was in lobby B
            ]
        )

        recommendations = await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)
        by_id = {rec.member_id: rec for rec in recommendations}

        # One map missed, not two: the first never counted against 9 at all.
        self.assertEqual(by_id[9].consecutive_sat, 1)
        self.assertEqual(by_id[9].games_played, 0)
        # 7 and 8 played both maps in a row, so one of them makes room and the
        # single sat-out map is still enough to owe 9 the next seat.
        self.assertEqual(by_id[9].status, RotationStatus.MUST_PLAY)

    async def test_rotation_of_a_one_lobby_mix_has_nothing_to_skip(self) -> None:
        """No busy rows anywhere: the verdict is the one this mix always got."""
        from src.domain.mix_rotation import RotationStatus

        self.games.get.return_value = _game()
        self.host_prefs.get_by_user.return_value = _prefs(role_slots_json={"tank": 1, "damage": 1})
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0, created_at=0),
            _roster_row(2, 8, 1, created_at=0),
            _roster_row(3, 9, 2, created_at=0),
        ]
        self.casual_matches.list_for_custom_game = AsyncMock(
            return_value=[
                _match(2, created_at=2, home=[7], away=[8]),
                _match(1, created_at=1, home=[7], away=[8]),
            ]
        )

        by_id = {
            rec.member_id: rec
            for rec in await self.service.rotation(self.session, workspace_id=1, custom_game_id=11)
        }

        self.assertEqual(by_id[9].consecutive_sat, 2)
        self.assertEqual(by_id[9].status, RotationStatus.MUST_PLAY)
        self.assertEqual(by_id[7].status, RotationStatus.SHOULD_REST)
```

- [ ] **Step 2: Run test to verify it fails**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_custom_game.py -q -k "other_lobby or one_lobby_mix_has_nothing"
```
Expected: FAIL в `test_rotation_counts_a_match_spent_in_the_other_lobby_as_neither` — `AssertionError: 2 != 1` (`consecutive_sat`): busy-строки пока не читаются. Второй тест проходит (сегодняшнее поведение).

- [ ] **Step 3: Write minimal implementation**

`backend/balancer-service/src/services/custom_game.py`, метод `_rotation_histories` целиком:

```python
    async def _rotation_histories(
        self, session: AsyncSession, game: models.CustomGame, roster: Sequence[models.CustomGamePlayer]
    ) -> list[PlayerHistory]:
        """One `PlayerHistory` per given roster row, from every map this mix recorded.

        Shared by :meth:`rotation` (ranks the whole pool for the host's hint) and
        :meth:`balance` (ranks the active lineup, so ``run_balance``'s own
        overflow trim benches the least-owed player first).

        A map the member spent in the mix's OTHER lobby drops out of their
        history entirely: it is neither a game they played nor one they sat out,
        and counting it as a rest would let somebody who has been playing
        non-stop next door outrank the people actually waiting. Empty for every
        one-lobby mix, which is why the verdict there is unchanged.
        """
        matches = list(await self.casual_matches.list_for_custom_game(session, game.id))
        matches.reverse()  # newest-first -> chronological, oldest map first
        participants = [
            {seat.workspace_member_id for team in match.teams for seat in team.players} for match in matches
        ]
        busy = [{row.workspace_member_id for row in match.busy_players} for match in matches]
        return [
            PlayerHistory(
                member_id=row.workspace_member_id,
                # Only maps recorded after this row joined the pool count --
                # a map played before they signed up is not one they sat out.
                played=tuple(
                    row.workspace_member_id in played
                    for match, played, elsewhere in zip(matches, participants, busy, strict=True)
                    if (row.created_at is None or match.created_at >= row.created_at)
                    and row.workspace_member_id not in elsewhere
                ),
                pinned_must_play=row.participation == MixParticipation.MUST_PLAY,
            )
            for row in roster
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run (из `backend/`):
```
uv run pytest balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_flow.py balancer-service/tests/test_mix_rotation.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/custom_game.py \
        backend/balancer-service/tests/test_custom_game.py
git commit -m "feat(balancer): a map spent in the other lobby is neither played nor sat out"
```

---

### Task B6: Баланс одного лобби

**Files:**
- Modify: `backend/balancer-service/src/services/custom_game.py:5` (импорт `datetime`), `:46-51` (блок импортов домена), `:688-793` (метод `balance` целиком заменяется на `_lineup_nodes` + `_solve_lobby` + `_lobby_candidates` + `balance`)
- Modify: `backend/balancer-service/src/schemas/custom_game.py:14-29` (`__all__`), `:104-107` (вставка после `CustomGameVariantIndexPatch`)
- Modify: `backend/balancer-service/src/rpc/custom.py:557-574` (`_balance`)
- Modify: `backend/balancer-service/src/openapi_schemas.py:113-125` (строка `custom.balance`)
- Modify: `backend/balancer-service/src/openapi_docs.py:295-303`
- Modify: `gateway/internal/balancer/routes.go:96`
- Modify (generated): `gateway/internal/openapi/schemas.json`
- Test: `backend/balancer-service/tests/test_custom_game.py`, `backend/balancer-service/tests/test_custom_game_contract.py`

**Interfaces:**
- Consumes: `CustomGameService._lobby(session, game, lobby_index) -> models.CustomGameLobby` (B1); `self.lobbies.get(session, custom_game_id, lobby_index) -> models.CustomGameLobby | None` (B1); `src.domain.mix_lobbies.seated_member_ids(balance_result_json, variant_index) -> frozenset[int]` (B2); `models.CustomGame.lobby_count`, `models.CustomGamePlayer.lobby_pin` (B2); `src.domain.mix_rotation.rotation_priority(PlayerHistory) -> float`; `src.services.balancer.solver.run_mix_balance` через `self.run_balance`.
- Produces:
  - `CustomGameService._lineup_nodes(session, *, game, lineup) -> dict[str, Any]` (B8 расширит возврат до кортежа с кандидатами деления)
  - `CustomGameService._solve_lobby(session, game, lobby, lineup) -> None`
  - `CustomGameService._lobby_candidates(session, game, lineup, lobby_index) -> list[models.CustomGamePlayer]`
  - `CustomGameService.balance(session, *, workspace_id, custom_game_id, lobby_index: int = 0, actor_user_id, actor_is_superuser=False) -> models.CustomGame`
  - `src.schemas.custom_game.CustomGameBalanceRequest` (`scope: Literal["lobby"] = "lobby"`, `lobby_index: int = Field(0, ge=0, le=1)`)
  - RPC `rpc.balancer.custom.balance` теперь читает тело.

> Модуль деления приходит только в B7, поэтому в B6 `_lineup_nodes` отдаёт один словарь узлов движка; типа `SplitCandidate` в этом коммите ещё нет. B8 меняет её возврат на `tuple[dict[str, Any], list[SplitCandidate]]` и показывает тело целиком.

- [ ] **Step 1: Write the failing test**

В `backend/balancer-service/tests/test_custom_game.py` добавить три теста рядом с существующими балансными (после `test_balance_uses_role_order_as_priority`, `:750-761`):

```python
    async def test_balance_of_one_lobby_leaves_out_the_other_lobbys_players(self) -> None:
        """Лобби A играет: его места и закреплённые за ним не попадают в баланс B."""
        game = _game(status="balanced", lobby_count=2)
        roster = [
            _roster_row(1, 7, 0),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2, lobby_pin=0),
            _roster_row(4, 10, 3),
        ]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8, 9, 10)
        self.lobby_rows[1] = _lobby(1)
        self.lobby_rows[0] = _lobby(
            0,
            balanced_at=datetime(2026, 3, 1, 21, 0),
            balance_result_json=lobby_document(
                [
                    {
                        "teams": [
                            {"id": 1, "roster": {"tank": [self._seat("8", "P8", 2500, "tank")]}},
                            {"id": 2, "roster": {"tank": [self._seat("10", "P10", 2400, "tank")]}},
                        ],
                        "statistics": {},
                        "benched_players": [],
                    }
                ]
            ),
        )

        await self.service.balance(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=1, actor_user_id=9
        )

        # 8 и 10 сидят в выбранном варианте лобби A, 9 закреплён за A -- остаётся 7.
        self.assertEqual(list(self.run_balance.await_args.args[0]["players"]), ["7"])
        self.assertIsNotNone(self.lobby_rows[1].balance_result_json)
        self.assertIsNotNone(self.lobby_rows[1].balanced_at)
        # Документ соседнего лобби не переписан.
        self.assertEqual(self.lobby_rows[0].balanced_at, datetime(2026, 3, 1, 21, 0))

    async def test_balance_of_a_one_lobby_mix_keeps_the_whole_pool(self) -> None:
        """У микса одно лобби: ни чужой документ, ни залежавшийся пин не сужают пул."""
        self.games.get.return_value = _game(lobby_count=1)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0), _roster_row(2, 8, 1, lobby_pin=1)]
        self.ranks.resolve.return_value = _ranks(7, 8)
        self.lobby_rows[1] = _lobby(
            1,
            balance_result_json=lobby_document(
                [
                    {
                        "teams": [
                            {"id": 1, "roster": {"tank": [self._seat("7", "P7", 2500, "tank")]}},
                            {"id": 2, "roster": {"tank": [self._seat("8", "P8", 2400, "tank")]}},
                        ],
                        "statistics": {},
                        "benched_players": [],
                    }
                ]
            ),
        )

        await self.service.balance(self.session, workspace_id=1, custom_game_id=11, actor_user_id=9)

        self.assertEqual(sorted(self.run_balance.await_args.args[0]["players"]), ["7", "8"])
        self.assertIsNotNone(self.lobby_rows[0].balance_result_json)

    async def test_balance_of_a_two_lobby_mix_leaves_the_unseated_waiting(self) -> None:
        """Невлезший в лобби игрок ждёт соседнее, а не уходит в бенч: бенч выкинул
        бы его и из кандидатов второго лобби."""
        game = _game(lobby_count=2)
        roster = [_roster_row(1, 7, 0), _roster_row(2, 8, 1), _roster_row(3, 9, 2)]
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = roster
        self.ranks.resolve.return_value = _ranks(7, 8, 9)
        self.lobby_rows[1] = _lobby(1)
        self.run_balance.return_value = {
            "players": {"7": {"name": "P7"}, "8": {"name": "P8"}, "9": {"name": "P9"}},
            "variants": [{"teams": [{"roster": {"tank": ["7", "8"]}}], "statistics": {}, "benched": ["9"]}],
        }

        await self.service.balance(
            self.session, workspace_id=1, custom_game_id=11, lobby_index=0, actor_user_id=9
        )

        self.assertEqual([row.participation for row in roster], [MixParticipation.POOL] * 3)
```

В `backend/balancer-service/tests/test_custom_game_contract.py` добавить в конец файла:

```python
def test_balance_request_defaults_to_the_first_lobby() -> None:
    """Пустое тело -- ровно то, что слали клиенты до появления лобби."""
    body = _schemas().CustomGameBalanceRequest.model_validate({})
    assert body.scope == "lobby"
    assert body.lobby_index == 0


def test_balance_request_rejects_a_third_lobby() -> None:
    with pytest.raises(ValidationError):
        _schemas().CustomGameBalanceRequest.model_validate({"lobby_index": 2})
```

- [ ] **Step 2: Run test to verify it fails**

Из `backend/`:

```bash
uv run pytest balancer-service/tests/test_custom_game_contract.py -q
uv run pytest balancer-service/tests/test_custom_game.py -q
```

Ожидание: контрактные — `AttributeError: module 'src.schemas.custom_game' has no attribute 'CustomGameBalanceRequest'` (оба теста); сервисные — `TypeError: balance() got an unexpected keyword argument 'lobby_index'` в двух тестах с `lobby_index=`, а `test_balance_of_a_one_lobby_mix_keeps_the_whole_pool` падает на `AssertionError: unexpectedly None` (без исключения соседних лобби сегодняшний код и так берёт обоих, но лобби-строку не пишет — её пишет только новый `_solve_lobby`).

- [ ] **Step 3: Write minimal implementation**

**3.1.** `backend/balancer-service/src/services/custom_game.py:5` — заменить импорт:

```python
from datetime import UTC, datetime
```

**3.2.** там же, блок импортов домена (`:46-51`) — добавить строку `mix_lobbies` (если B2 уже её добавил для `record_outcome`, оставить как есть):

```python
from src.domain.balancer.result_serializer import as_lobby_document, seat_rating
from src.domain.mix_discord import build_lineup_embed
from src.domain.mix_lobbies import seated_member_ids
from src.domain.mix_rotation import PlayerHistory, RotationRecommendation, recommend_rotation, rotation_priority
```

**3.3.** заменить весь метод `balance` (`:688-793`) на:

```python
    async def _lineup_nodes(
        self,
        session: AsyncSession,
        *,
        game: models.CustomGame,
        lineup: Sequence[models.CustomGamePlayer],
    ) -> dict[str, Any]:
        """Вход движка для этих строк ростера: ранги, порядок ролей, приоритет ротации.

        Вынесено из ``balance``, потому что один микс теперь решается по лобби:
        каждое лобби получает свой набор строк, а читает их одинаково.
        """
        # If the lineup does not divide evenly into full teams, `run_balance`'s own
        # overflow trim (`domain.balancer.runtime._prepare_balance_context`) sorts the
        # players not pinned to a seat by `Player.rotation_priority` ascending and
        # benches the TAIL -- the HIGHEST values, i.e. those `rotation_priority()`
        # ranks least owed a seat (a long sat-out streak drives it negative and
        # protects the player). Same fairness rank the "Apply rotation hints" button
        # reads, computed here and carried through as one number per player, since
        # `player_loader.load_players_from_dict` sorts its input by uuid and would
        # otherwise discard any ordering placed on `lineup` itself.
        histories_by_member = {
            history.member_id: history for history in await self._rotation_histories(session, game, lineup)
        }
        members = await self.members(session, game.workspace_id, [row.workspace_member_id for row in lineup])
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(REGISTRATION_ROLE_CODES),
            # ``MIX_ORDER`` puts the host's own book above the workspace canon: a
            # mix balances on this host's read of these players, not the official one.
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await get_effective_division_grid(session, None),
        )
        explicit_roles = await self.player_roles.roles_for_players(
            session,
            [row.id for row in lineup if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT],
        )
        player_nodes: dict[str, Any] = {}
        for row in lineup:
            member = members[row.workspace_member_id]
            classes: dict[str, Any] = {}
            role_order = (
                explicit_roles.get(row.id, [])
                if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
                else REGISTRATION_ROLE_CODES
            )
            # An explicit empty list means no playable role; it never falls back.
            for priority, role in enumerate(role_order, start=1):
                ranked = resolved.get((member.member_id, role))
                if ranked is None or ranked.value is None:
                    continue
                classes[role] = {"isActive": True, "rank": ranked.value, "priority": priority}
            if not classes:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="missing_ranked_role")
            player_nodes[str(member.member_id)] = {
                "identity": {
                    "name": member.display_name or member.battle_tag or f"player-{member.member_id}",
                    "isFullFlex": row.is_flex,
                    "mustPlay": row.participation == MixParticipation.MUST_PLAY,
                    "rotationPriority": rotation_priority(histories_by_member[row.workspace_member_id]),
                },
                "stats": {"classes": classes},
            }
        return player_nodes

    async def _solve_lobby(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        lobby: models.CustomGameLobby,
        lineup: Sequence[models.CustomGamePlayer],
    ) -> None:
        """Прогнать движок ровно на этих игроках и записать прогон в это лобби."""
        player_nodes = await self._lineup_nodes(session, game=game, lineup=lineup)
        # The HOST's row, not the acting co-host's, and read exactly once: the
        # ranks above are already resolved against the host's own book
        # (``MIX_ORDER`` + ``author_user_id=game.host_user_id``), so reading the
        # presser's preferences instead would make the same mix balance
        # differently depending on who clicked. The same row carries both the
        # solver overrides and the roster shape, so they come off one load.
        host_config = await self._host_config(session, game.host_user_id)
        role_mask = (await self._shape_for(session, game.workspace_id, host_config)).slots
        try:
            result = await self.run_balance(
                {"players": player_nodes},
                host_config.config_json if host_config is not None else None,
                _noop_progress,
                role_mask,
            )
        except ValueError as exc:
            # The solver raises plain ``ValueError`` for input problems it can
            # diagnose (uneven player count, short role coverage, ...). Left
            # uncaught it reaches the generic RPC handler, which cannot tell it
            # apart from a real bug and reports "internal error" -- hiding the
            # actual, actionable reason from the host.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        lobby.balance_result_json = result
        # A fresh search renumbers every option, so whatever the host had paged
        # to describes nothing now -- back to the best one.
        lobby.selected_variant_index = 0
        lobby.balanced_at = datetime.now(UTC)

    async def _lobby_candidates(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        lineup: Sequence[models.CustomGamePlayer],
        lobby_index: int,
    ) -> list[models.CustomGamePlayer]:
        """Кого это лобби может посадить: пул минус игроки соседнего лобби.

        Сидящий в выбранном варианте соседнего лобби играет прямо сейчас, а
        закреплённый за ним обещан ему. У однолобби-микса соседа нет, и пул --
        это весь не-benched лайнап, ровно как раньше.
        """
        if game.lobby_count < 2:
            return list(lineup)
        other_index = 1 - lobby_index
        other = await self.lobbies.get(session, game.id, other_index)
        busy = (
            seated_member_ids(other.balance_result_json, other.selected_variant_index)
            if other is not None
            else frozenset()
        )
        return [row for row in lineup if row.workspace_member_id not in busy and row.lobby_pin != other_index]

    async def balance(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Пересобрать составы ОДНОГО лобби (по умолчанию -- первого).

        Для однолобби-микса это сегодняшнее поведение целиком: весь не-benched
        пул уходит в движок и ложится в документ лобби 0.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        lineup = [row for row in roster if row.participation != MixParticipation.BENCHED]
        if not lineup:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
        lobby = await self._lobby(session, game, lobby_index)
        candidates = await self._lobby_candidates(session, game, lineup, lobby_index)
        if not candidates:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
        await self._solve_lobby(session, game, lobby, candidates)
        # Бенч перелива -- ответ однолобби-микса. При двух лобби невлезшие ЖДУТ
        # соседнее (§Derived state), а BENCHED-строка выпала бы и из его пула.
        if game.lobby_count < 2:
            _apply_balance_result(roster, lobby.balance_result_json)
        game.status = MixStatus.BALANCED
        await session.flush()
        return game
```

**3.4.** `backend/balancer-service/src/schemas/custom_game.py` — в `__all__` (`:14-29`) добавить строку в алфавитном порядке, сразу после `"CustomGameCoHostPatch",`:

```python
    "CustomGameBalanceRequest",
```

и после класса `CustomGameVariantIndexPatch` (`:104-107`) вставить:

```python
class CustomGameBalanceRequest(_Request):
    """Что балансировать. Пустое тело = первое лобби, как до появления второго."""

    scope: Literal["lobby"] = "lobby"
    lobby_index: int = Field(0, ge=0, le=1)
```

**3.5.** `backend/balancer-service/src/rpc/custom.py:557-574` — заменить на:

```python
    @broker.subscriber("rpc.balancer.custom.balance")
    async def _balance(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameBalanceRequest, data)
            game = await custom_game_service.balance(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                lobby_index=body.lobby_index,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="balance", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.balance", op, session_factory=_SF)
```

**3.6.** `backend/balancer-service/src/openapi_schemas.py` — в блоке pickup-mix-записей (`:113-125`) добавить строку после `"rpc.balancer.custom.set_participation": …`:

```python
    "rpc.balancer.custom.balance": Op(request=custom_game.CustomGameBalanceRequest),
```

**3.7.** `backend/balancer-service/src/openapi_docs.py:295-303` — заменить описание:

```python
    "rpc.balancer.custom.balance": {
        "summary": "Balance custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "Balances the non-benched lineup of ONE lobby (`lobby_index`, default 0) -- everyone the "
            "other lobby is already playing or holds a pin on is left out -- reading the host's own "
            "rank book above the workspace canon, stores the resulting options on that lobby and "
            "returns the mix; 422 when the lineup is empty or a seated player has no ranked role."
        ),
    },
```

**3.8.** `gateway/internal/balancer/routes.go:96` — добавить `Body: true`:

```go
	{Method: "POST", Pattern: "/api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/balance", Queue: "rpc.balancer.custom.balance", IDParam: "game_id", Path: []string{"workspace_id"}, Body: true, Auth: edge.AuthRequired},
```

**3.9.** перегенерировать манифест схем. Из `backend/`:

```bash
bash scripts/export_openapi_schemas.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Из `backend/`:

```bash
uv run pytest balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_contract.py -q
bash scripts/export_openapi_schemas.sh --check
uv run python scripts/check_rpc_docs.py
```

Из `gateway/`:

```bash
go test ./internal/balancer/... ./internal/openapi/...
```

Ожидание: всё PASS, `schemas.json is up to date`.

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/custom_game.py \
        backend/balancer-service/src/schemas/custom_game.py \
        backend/balancer-service/src/rpc/custom.py \
        backend/balancer-service/src/openapi_schemas.py \
        backend/balancer-service/src/openapi_docs.py \
        backend/balancer-service/tests/test_custom_game.py \
        backend/balancer-service/tests/test_custom_game_contract.py \
        gateway/internal/balancer/routes.go \
        gateway/internal/openapi/schemas.json
git commit -m "feat(balancer): mix balances one lobby at a time"
```

---

### Task B7: Деление пула на два лобби

**Files:**
- Create: `backend/balancer-service/src/domain/mix_lobby_split.py`
- Test: `backend/balancer-service/tests/test_mix_lobby_split.py` (новый)

**Interfaces:**
- Consumes: `src.domain.matching.maximum_bipartite_matching(*, candidates, slots, eligible_slots) -> BipartiteMatching` (`src/domain/matching.py:38-84`, свойство `.matched_count`); `shared.domain.roster_shape.FLEX_SLOT_CODE` (`:40`).
- Produces:
  - `SplitCandidate(member_id: int, ratings: Mapping[str, int], strength: int, pin: int | None = None, must_play: bool = False, rotation_priority: float = 0.0)` — frozen slots-dataclass
  - `LobbySplit(lobbies: tuple[tuple[int, ...], tuple[int, ...]], waiting: tuple[int, ...])` — frozen slots-dataclass
  - `LobbySplitError(ValueError)` c атрибутом `.code ∈ {"not_enough_for_two_lobbies", "too_many_must_play", "too_many_pinned", "roles_infeasible"}`
  - `split_into_lobbies(candidates: Sequence[SplitCandidate], *, mask: Mapping[str, int]) -> LobbySplit`

- [ ] **Step 1: Write the failing test**

Создать `backend/balancer-service/tests/test_mix_lobby_split.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.mix_lobby_split import LobbySplitError, SplitCandidate, split_into_lobbies  # noqa: E402

#: 1 танк на команду -> 2 места в лобби, 4 игрока на два лобби.
MASK_TANK = {"tank": 1}
#: 1 танк + 1 дамаг на команду -> 4 места в лобби (2 танковых + 2 дамажных).
MASK_TANK_DAMAGE = {"tank": 1, "damage": 1}


def _candidate(
    member_id: int,
    strength: int,
    *,
    roles: tuple[str, ...] = ("tank", "damage", "support"),
    pin: int | None = None,
    must_play: bool = False,
    rotation_priority: float = 0.0,
) -> SplitCandidate:
    return SplitCandidate(
        member_id=member_id,
        ratings={role: strength for role in roles},
        strength=strength,
        pin=pin,
        must_play=must_play,
        rotation_priority=rotation_priority,
    )


def test_pinned_players_land_in_their_own_lobby() -> None:
    candidates = [
        _candidate(1, 3000, pin=1),
        _candidate(2, 2900),
        _candidate(3, 2800, pin=0),
        _candidate(4, 2700),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK)

    assert 1 in split.lobbies[1]
    assert 3 in split.lobbies[0]
    assert sorted(split.lobbies[0] + split.lobbies[1]) == [1, 2, 3, 4]
    assert split.waiting == ()


def test_more_pins_than_seats_in_one_lobby_is_refused() -> None:
    candidates = [
        _candidate(1, 3000, pin=0),
        _candidate(2, 2900, pin=0),
        _candidate(3, 2800, pin=0),
        _candidate(4, 2700),
    ]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask=MASK_TANK)

    assert exc.value.code == "too_many_pinned"


def test_two_lobbies_need_a_full_pool_for_both() -> None:
    candidates = [_candidate(member_id, 2500) for member_id in (1, 2, 3)]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask=MASK_TANK)

    assert exc.value.code == "not_enough_for_two_lobbies"


def test_more_must_play_than_seats_in_both_lobbies_is_refused() -> None:
    """Пин обещает место: 21 обещание на 20 мест двух лобби -- не тихий waiting."""
    candidates = [_candidate(member_id, 2500, must_play=True) for member_id in range(1, 22)]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask={"tank": 1, "damage": 2, "support": 2})

    assert exc.value.code == "too_many_must_play"


def test_five_tank_only_players_do_not_fit_four_tank_slots() -> None:
    # Два лобби дают 4 танковых слота; пятый «только танк» не сядет никуда,
    # как бы ни делили остальных.
    candidates = [_candidate(member_id, 3000 - member_id, roles=("tank",)) for member_id in (1, 2, 3, 4, 5)]
    candidates += [_candidate(member_id, 2000 - member_id, roles=("tank", "damage")) for member_id in (6, 7, 8)]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask=MASK_TANK_DAMAGE)

    assert exc.value.code == "roles_infeasible"


def test_must_play_takes_a_seat_over_a_rested_pool() -> None:
    candidates = [
        _candidate(1, 3000, rotation_priority=-5.0),
        _candidate(2, 2900, rotation_priority=-4.0),
        _candidate(3, 2800, rotation_priority=-3.0),
        _candidate(4, 2700, rotation_priority=-2.0),
        _candidate(5, 2600, must_play=True, rotation_priority=9.0),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK)

    assert 5 in split.lobbies[0] + split.lobbies[1]
    # Место отдаёт тот, кто по ротации должен его меньше всех.
    assert split.waiting == (4,)


def test_waiting_are_the_players_least_owed_a_seat() -> None:
    candidates = [
        _candidate(1, 2500, rotation_priority=4.0),
        _candidate(2, 2500, rotation_priority=-1.0),
        _candidate(3, 2500, rotation_priority=0.0),
        _candidate(4, 2500, rotation_priority=-3.0),
        _candidate(5, 2500, rotation_priority=3.0),
        _candidate(6, 2500, rotation_priority=-2.0),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK)

    assert split.waiting == (1, 5)
    assert sorted(split.lobbies[0] + split.lobbies[1]) == [2, 3, 4, 6]


def test_role_bound_greedy_is_repaired_by_swaps() -> None:
    """Жадный шаг обязан слушаться ролевых слотов и потому перекашивается.

    Танки 100/60/50/40, дамаги 90/80/20/10, по два танковых и два дамажных
    слота на лобби. Жадно (сильнейший -- в лобби полегче, где он помещается)
    получается 190 против 260, разрыв 70: как только танковые слоты лобби
    заполнены, следующий танк вынужден идти в тяжёлое. Обмены, сохраняющие
    заполнимость, закрывают разрыв до 10 -- лучшего эта ролевая структура не
    допускает (танки делятся только как 100+40 против 60+50).
    """
    candidates = [
        _candidate(1, 100, roles=("tank",)),
        _candidate(2, 90, roles=("damage",)),
        _candidate(3, 80, roles=("damage",)),
        _candidate(4, 60, roles=("tank",)),
        _candidate(5, 50, roles=("tank",)),
        _candidate(6, 40, roles=("tank",)),
        _candidate(7, 20, roles=("damage",)),
        _candidate(8, 10, roles=("damage",)),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK_DAMAGE)

    strength = {candidate.member_id: candidate.strength for candidate in candidates}
    totals = [sum(strength[member_id] for member_id in lobby) for lobby in split.lobbies]
    assert abs(totals[0] - totals[1]) == 10
    assert set(split.lobbies[0]) == {1, 3, 6, 8}
    assert set(split.lobbies[1]) == {2, 4, 5, 7}


def test_identical_players_split_by_input_order() -> None:
    """Ни RNG, ни обхода множеств: равные игроки ложатся так, как их подали."""
    candidates = [_candidate(member_id, 2500) for member_id in (1, 2, 3, 4)]

    first = split_into_lobbies(candidates, mask=MASK_TANK)
    second = split_into_lobbies(candidates, mask=MASK_TANK)

    assert first == second
    assert first.lobbies == ((1, 3), (2, 4))


def test_a_flex_slot_takes_any_ranked_player() -> None:
    """Воркспейс может держать all-flex форму; ранга с именем "flex" нет ни у кого."""
    candidates = [_candidate(member_id, 2500, roles=("support",)) for member_id in (1, 2, 3, 4)]

    split = split_into_lobbies(candidates, mask={"flex": 1})

    assert sorted(split.lobbies[0] + split.lobbies[1]) == [1, 2, 3, 4]
```

- [ ] **Step 2: Run test to verify it fails**

Из `backend/`:

```bash
uv run pytest balancer-service/tests/test_mix_lobby_split.py -q
```

Ожидание: коллекция падает — `ModuleNotFoundError: No module named 'src.domain.mix_lobby_split'`.

- [ ] **Step 3: Write minimal implementation**

Создать `backend/balancer-service/src/domain/mix_lobby_split.py`:

```python
"""Делит пул микса на два равных по силе лобби.

Pure domain algorithm: no I/O, no async, no ORM. Вызывающий
(``CustomGameService.balance`` со ``scope="all"``) резолвит ранги, порядок
ролей и приоритет ротации, а точную рассадку внутри лобби делает прежний
``mix_balancer`` -- здесь решается только, КТО с кем в одном лобби.

``strength`` -- приближение (рейтинг роли, на которую игрока посадят первой),
поэтому фактический разрыв между лобби считается потом по ``average_mmr``
выбранных вариантов. Жадное деление плюс локальные обмены -- не глобальный
оптимум: если разрыв на практике окажется заметным, здесь появится точный
перебор делений.

Детерминизм обязателен: один и тот же пул должен делиться одинаково при
каждом нажатии. Все сортировки доломаны до входного порядка кандидатов, RNG
нет, множества нигде не обходятся.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shared.domain.roster_shape import FLEX_SLOT_CODE
from src.domain.matching import maximum_bipartite_matching

__all__ = ("LobbySplit", "LobbySplitError", "SplitCandidate", "split_into_lobbies")

#: Потолок спеки: ровно два лобби (CHECK ``lobby_index BETWEEN 0 AND 1``).
_LOBBIES = (0, 1)

#: Слот роли одного лобби: (лобби, роль, порядковый номер слота этой роли).
_Slot = tuple[int, str, int]


@dataclass(frozen=True, slots=True)
class SplitCandidate:
    """Один не-benched игрок пула глазами делителя.

    ``ratings`` -- только роли, на которых у него нашёлся ранг; пустой словарь
    означает «не играбелен» (движок такого всё равно не посадит).
    ``strength`` -- рейтинг роли с высшим приоритетом, для ``all_ranked``
    максимум. ``rotation_priority``: меньше = больше должен место.
    """

    member_id: int
    ratings: Mapping[str, int]
    strength: int
    pin: int | None = None
    must_play: bool = False
    rotation_priority: float = 0.0


@dataclass(frozen=True, slots=True)
class LobbySplit:
    lobbies: tuple[tuple[int, ...], tuple[int, ...]]
    waiting: tuple[int, ...] = ()


class LobbySplitError(ValueError):
    """Почему пул не делится. ``code`` уходит на провод как ``detail`` 422:
    ``not_enough_for_two_lobbies``, ``too_many_must_play``, ``too_many_pinned``,
    ``roles_infeasible``.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _slots(mask: Mapping[str, int]) -> tuple[_Slot, ...]:
    """Ролевые слоты обоих лобби: две команды на лобби, ``mask`` слотов на команду."""
    return tuple(
        (lobby, role, position)
        for lobby in _LOBBIES
        for role, count in mask.items()
        for position in range(count * 2)
    )


def _eligible(candidate: SplitCandidate, slot: _Slot, lobby: int | None) -> bool:
    """Может ли игрок занять слот: своё лобби (или ещё никакое) плюс роль.

    Флекс-слот берёт любого играбельного: ранга с именем ``flex`` не бывает,
    а ``resolve_roster_shape`` такую форму отдать может.
    """
    if lobby is not None and lobby != slot[0]:
        return False
    return slot[1] == FLEX_SLOT_CODE or slot[1] in candidate.ratings


def _fillable(
    playing: Sequence[SplitCandidate],
    slots: Sequence[_Slot],
    assignment: Mapping[int, int],
) -> bool:
    """Заполнимы ли роли ОБОИХ лобби при этой (частичной) расстановке.

    Уже поставленные привязаны к слотам своего лобби, остальные могут попасть
    в любое -- вместимость лобби кодируется числом его слотов, поэтому полное
    сопоставление автоматически даёт каждому лобби ровно его места.
    """
    eligible = {
        candidate.member_id: [
            slot for slot in slots if _eligible(candidate, slot, assignment.get(candidate.member_id))
        ]
        for candidate in playing
    }
    matching = maximum_bipartite_matching(
        candidates=[candidate.member_id for candidate in playing],
        slots=slots,
        eligible_slots=eligible,
    )
    return matching.matched_count == len(slots)


def split_into_lobbies(candidates: Sequence[SplitCandidate], *, mask: Mapping[str, int]) -> LobbySplit:
    """Разделить пул на два лобби по ``mask`` слотов на команду.

    1. Кто играет: ``must_play`` -> ``rotation_priority`` по возрастанию ->
       входной порядок; первые ``2 * seats`` играют, остальные ждут. Обещанных
       мест (``must_play``) больше, чем мест вообще -- отказ целиком.
    2. Закреплённые садятся в своё лобби.
    3. Остальные по убыванию силы -- в лобби полегче, если после хода роли
       обоих лобби ещё заполнимы.
    4. Пока есть незакреплённая пара, обмен которой уменьшает разрыв и
       сохраняет заполнимость, меняем лучшую такую пару.
    """
    seats = 2 * sum(mask.values())
    order = {candidate.member_id: position for position, candidate in enumerate(candidates)}
    playable = [candidate for candidate in candidates if candidate.ratings]
    if len(playable) < 2 * seats:
        raise LobbySplitError("not_enough_for_two_lobbies")
    if sum(candidate.must_play for candidate in playable) > 2 * seats:
        # Пин обещает место, а их на два лобби ровно ``2 * seats``: тихо
        # отправить часть обещанных в ``waiting`` -- сломать само обещание.
        raise LobbySplitError("too_many_must_play")

    ranked = sorted(
        playable,
        key=lambda candidate: (not candidate.must_play, candidate.rotation_priority, order[candidate.member_id]),
    )
    playing = ranked[: 2 * seats]
    seated_ids = {candidate.member_id for candidate in playing}
    waiting = tuple(candidate.member_id for candidate in candidates if candidate.member_id not in seated_ids)

    assignment: dict[int, int] = {}
    counts = [0, 0]
    totals = [0, 0]
    for candidate in playing:
        if candidate.pin is None:
            continue
        if counts[candidate.pin] >= seats:
            raise LobbySplitError("too_many_pinned")
        assignment[candidate.member_id] = candidate.pin
        counts[candidate.pin] += 1
        totals[candidate.pin] += candidate.strength

    slots = _slots(mask)
    rest = sorted(
        (candidate for candidate in playing if candidate.member_id not in assignment),
        key=lambda candidate: (-candidate.strength, order[candidate.member_id]),
    )
    for candidate in rest:
        options = sorted((index for index in _LOBBIES if counts[index] < seats), key=lambda index: (totals[index], index))
        for lobby in options:
            assignment[candidate.member_id] = lobby
            if _fillable(playing, slots, assignment):
                counts[lobby] += 1
                totals[lobby] += candidate.strength
                break
            del assignment[candidate.member_id]
        else:
            raise LobbySplitError("roles_infeasible")

    swappable = [candidate for candidate in playing if candidate.pin is None]
    # Каждая итерация строго уменьшает разрыв, так что цикл конечен и без
    # потолка; ``seats ** 2`` -- страховка спеки от патологического входа.
    for _ in range(seats * seats):
        gap = abs(totals[0] - totals[1])
        improving = []
        for first in swappable:
            if assignment[first.member_id] != 0:
                continue
            for second in swappable:
                if assignment[second.member_id] != 1:
                    continue
                moved = abs(totals[0] - totals[1] + 2 * (second.strength - first.strength))
                if moved < gap:
                    improving.append((moved, order[first.member_id], order[second.member_id], first, second))
        improving.sort(key=lambda item: item[:3])
        for _moved, _first_position, _second_position, first, second in improving:
            assignment[first.member_id], assignment[second.member_id] = 1, 0
            if _fillable(playing, slots, assignment):
                totals[0] += second.strength - first.strength
                totals[1] += first.strength - second.strength
                break
            assignment[first.member_id], assignment[second.member_id] = 0, 1
        else:
            break

    seated = tuple(
        tuple(candidate.member_id for candidate in playing if assignment[candidate.member_id] == lobby)
        for lobby in _LOBBIES
    )
    return LobbySplit(lobbies=(seated[0], seated[1]), waiting=waiting)
```

- [ ] **Step 4: Run test to verify it passes**

Из `backend/`:

```bash
uv run pytest balancer-service/tests/test_mix_lobby_split.py -q
```

Ожидание: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/domain/mix_lobby_split.py \
        backend/balancer-service/tests/test_mix_lobby_split.py
git commit -m "feat(balancer): split a mix pool into two equal lobbies"
```

---

### Task B8: Перемешать оба лобби (`scope: "all"`)

**Files:**
- Modify: `backend/balancer-service/src/services/custom_game.py` — импорт `mix_lobby_split`; `_lineup_nodes` (возвращает кортеж), `balance` (параметр `scope` + ветка), новый `_balance_both`
- Modify: `backend/balancer-service/src/schemas/custom_game.py` — литерал `scope` в `CustomGameBalanceRequest`
- Modify: `backend/balancer-service/src/rpc/custom.py` — `_balance` передаёт `scope`
- Modify: `backend/balancer-service/src/openapi_docs.py` — описание `custom.balance`
- Modify (generated): `gateway/internal/openapi/schemas.json`
- Test: `backend/balancer-service/tests/test_custom_game.py`, `backend/balancer-service/tests/test_custom_game_contract.py`

**Interfaces:**
- Consumes: `split_into_lobbies(candidates, *, mask) -> LobbySplit`, `SplitCandidate(...)`, `LobbySplitError.code` (B7); `CustomGameService._lobby`, `_solve_lobby`, `_host_config`, `_shape_for`.
- Produces:
  - `CustomGameService._lineup_nodes(session, *, game, lineup) -> tuple[dict[str, Any], list[SplitCandidate]]`
  - `CustomGameService._balance_both(session, game, lineup) -> None`
  - `CustomGameService.balance(session, *, workspace_id, custom_game_id, scope: str = "lobby", lobby_index: int = 0, actor_user_id, actor_is_superuser=False) -> models.CustomGame`
  - `CustomGameBalanceRequest.scope: Literal["lobby", "all"]`

- [ ] **Step 1: Write the failing test**

В `backend/balancer-service/tests/test_custom_game.py` добавить после тестов B6:

```python
    async def test_balance_of_both_lobbies_fills_each_with_its_own_half(self) -> None:
        """«Перемешать оба»: один прогон движка на лобби, ровно на своих игроках."""
        self.workspace_roster_slots.return_value = {"tank": 1}
        game = _game(lobby_count=2)
        self.games.get.return_value = game
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2),
            _roster_row(4, 10, 3),
        ]
        self.ranks.resolve.return_value = _ranks(7, 8, 9, 10)
        self.lobby_rows[1] = _lobby(1)

        await self.service.balance(
            self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9
        )

        self.assertEqual(self.run_balance.await_count, 2)
        first, second = (call.args[0]["players"] for call in self.run_balance.await_args_list)
        # Силы равны, поэтому деление идёт по входному порядку -- и ни один игрок
        # не попадает в оба лобби.
        self.assertEqual(set(first), {"7", "9"})
        self.assertEqual(set(second), {"8", "10"})
        for lobby in self.lobby_rows.values():
            self.assertIsNotNone(lobby.balance_result_json)
            self.assertIsNotNone(lobby.balanced_at)
            self.assertEqual(lobby.selected_variant_index, 0)
        self.assertEqual(game.status, "balanced")

    async def test_balance_of_both_lobbies_needs_two_lobbies(self) -> None:
        self.games.get.return_value = _game(lobby_count=1)
        self.roster.list_for_game.return_value = [_roster_row(1, 7, 0)]
        self.ranks.resolve.return_value = _ranks(7)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(
                self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "single_lobby")
        self.run_balance.assert_not_called()

    async def test_balance_of_both_lobbies_refuses_a_pool_that_fills_only_one(self) -> None:
        self.workspace_roster_slots.return_value = {"tank": 1}
        self.games.get.return_value = _game(lobby_count=2)
        self.roster.list_for_game.return_value = [
            _roster_row(1, 7, 0),
            _roster_row(2, 8, 1),
            _roster_row(3, 9, 2),
        ]
        self.ranks.resolve.return_value = _ranks(7, 8, 9)
        self.lobby_rows[1] = _lobby(1)

        with self.assertRaises(HTTPException) as ctx:
            await self.service.balance(
                self.session, workspace_id=1, custom_game_id=11, scope="all", actor_user_id=9
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "not_enough_for_two_lobbies")
        self.run_balance.assert_not_called()
```

В `backend/balancer-service/tests/test_custom_game_contract.py` добавить в конец:

```python
def test_balance_request_takes_the_both_lobbies_scope() -> None:
    body = _schemas().CustomGameBalanceRequest.model_validate({"scope": "all"})
    assert body.scope == "all"
    assert body.lobby_index == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Из `backend/`:

```bash
uv run pytest balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_contract.py -q
```

Ожидание: сервисные — `TypeError: balance() got an unexpected keyword argument 'scope'`; контрактный — `pydantic_core.ValidationError: Input should be 'lobby'`.

- [ ] **Step 3: Write minimal implementation**

**3.1.** `backend/balancer-service/src/services/custom_game.py`, блок импортов домена — добавить строку после `mix_lobbies`:

```python
from src.domain.mix_lobbies import seated_member_ids
from src.domain.mix_lobby_split import LobbySplitError, SplitCandidate, split_into_lobbies
```

**3.2.** заменить сигнатуру и тело `_lineup_nodes` (та часть, что строит узлы) так, чтобы она отдавала и кандидатов деления. Заменяемый фрагмент — от строки `    ) -> dict[str, Any]:` до `        return player_nodes` включительно:

```python
    ) -> tuple[dict[str, Any], list[SplitCandidate]]:
        """Вход движка для этих строк ростера плюс те же факты для делителя.

        Один проход по одним и тем же чтениям: ранги, порядок ролей и приоритет
        ротации, которые нужны движку, -- ровно то, что взвешивает делитель на
        два лобби, так что они не могут разъехаться (и ``member_rank`` не
        читается по два раза на один лайнап).
        """
        # If the lineup does not divide evenly into full teams, `run_balance`'s own
        # overflow trim (`domain.balancer.runtime._prepare_balance_context`) sorts the
        # players not pinned to a seat by `Player.rotation_priority` ascending and
        # benches the TAIL -- the HIGHEST values, i.e. those `rotation_priority()`
        # ranks least owed a seat (a long sat-out streak drives it negative and
        # protects the player). Same fairness rank the "Apply rotation hints" button
        # reads, computed here and carried through as one number per player, since
        # `player_loader.load_players_from_dict` sorts its input by uuid and would
        # otherwise discard any ordering placed on `lineup` itself.
        histories_by_member = {
            history.member_id: history for history in await self._rotation_histories(session, game, lineup)
        }
        members = await self.members(session, game.workspace_id, [row.workspace_member_id for row in lineup])
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(REGISTRATION_ROLE_CODES),
            # ``MIX_ORDER`` puts the host's own book above the workspace canon: a
            # mix balances on this host's read of these players, not the official one.
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await get_effective_division_grid(session, None),
        )
        explicit_roles = await self.player_roles.roles_for_players(
            session,
            [row.id for row in lineup if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT],
        )
        player_nodes: dict[str, Any] = {}
        candidates: list[SplitCandidate] = []
        for row in lineup:
            member = members[row.workspace_member_id]
            classes: dict[str, Any] = {}
            explicit = row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
            role_order = explicit_roles.get(row.id, []) if explicit else REGISTRATION_ROLE_CODES
            # An explicit empty list means no playable role; it never falls back.
            for priority, role in enumerate(role_order, start=1):
                ranked = resolved.get((member.member_id, role))
                if ranked is None or ranked.value is None:
                    continue
                classes[role] = {"isActive": True, "rank": ranked.value, "priority": priority}
            if not classes:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="missing_ranked_role")
            fairness = rotation_priority(histories_by_member[row.workspace_member_id])
            player_nodes[str(member.member_id)] = {
                "identity": {
                    "name": member.display_name or member.battle_tag or f"player-{member.member_id}",
                    "isFullFlex": row.is_flex,
                    "mustPlay": row.participation == MixParticipation.MUST_PLAY,
                    "rotationPriority": fairness,
                },
                "stats": {"classes": classes},
            }
            ratings = {role: entry["rank"] for role, entry in classes.items()}
            candidates.append(
                SplitCandidate(
                    member_id=member.member_id,
                    ratings=ratings,
                    # На какой роли игрока посадят первой: ``classes`` собран в
                    # порядке приоритетов, так что первая запись -- она и есть.
                    # У all-ranked предпочтений нет, поэтому берётся лучший ранг.
                    strength=next(iter(ratings.values())) if explicit else max(ratings.values()),
                    pin=row.lobby_pin,
                    must_play=row.participation == MixParticipation.MUST_PLAY,
                    rotation_priority=fairness,
                )
            )
        return player_nodes, candidates
```

**3.3.** в `_solve_lobby` первую строку тела заменить на распаковку кортежа:

```python
        player_nodes, _candidates = await self._lineup_nodes(session, game=game, lineup=lineup)
```

**3.4.** заменить метод `balance` (целиком, от `    async def balance(` до `        return game`) на:

```python
    async def balance(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        scope: str = "lobby",
        lobby_index: int = 0,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Пересобрать составы ОДНОГО лобби (по умолчанию) или обоих сразу.

        ``scope="lobby"`` -- сегодняшнее поведение микса: не-benched пул минус
        те, кого уже играет соседнее лобби, уходит в движок и ложится в
        документ этого лобби. ``scope="all"`` существует только для микса с
        двумя лобби: пул сначала делится на две равные по силе половины
        (``domain.mix_lobby_split``), а дальше каждая решается тем же движком.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        lineup = [row for row in roster if row.participation != MixParticipation.BENCHED]
        if not lineup:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
        if scope == "all":
            await self._balance_both(session, game, lineup)
        else:
            lobby = await self._lobby(session, game, lobby_index)
            candidates = await self._lobby_candidates(session, game, lineup, lobby_index)
            if not candidates:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
            await self._solve_lobby(session, game, lobby, candidates)
            # Бенч перелива -- ответ однолобби-микса. При двух лобби невлезшие ЖДУТ
            # соседнее (§Derived state), а BENCHED-строка выпала бы и из его пула.
            if game.lobby_count < 2:
                _apply_balance_result(roster, lobby.balance_result_json)
        game.status = MixStatus.BALANCED
        await session.flush()
        return game

    async def _balance_both(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        lineup: Sequence[models.CustomGamePlayer],
    ) -> None:
        """Поделить пул на два равных лобби и решить каждое своим прогоном.

        Делитель отдаёт ровно ``seats`` игроков на лобби, поэтому собственный
        trim движка внутри каждого прогона становится no-op, а невзятые в игру
        остаются в пуле и ждут -- ни одна строка ростера не бенчится.
        """
        if game.lobby_count < 2:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="single_lobby")
        _player_nodes, candidates = await self._lineup_nodes(session, game=game, lineup=lineup)
        host_config = await self._host_config(session, game.host_user_id)
        role_mask = (await self._shape_for(session, game.workspace_id, host_config)).slots
        try:
            split = split_into_lobbies(candidates, mask=role_mask)
        except LobbySplitError as exc:
            # Машиночитаемая причина (not_enough_for_two_lobbies / too_many_must_play /
            # too_many_pinned / roles_infeasible): UI показывает её как текст, а не стектрейс.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.code) from exc
        rows = {row.workspace_member_id: row for row in lineup}
        for lobby_index, member_ids in enumerate(split.lobbies):
            lobby = await self._lobby(session, game, lobby_index)
            await self._solve_lobby(session, game, lobby, [rows[member_id] for member_id in member_ids])
```

**3.5.** `backend/balancer-service/src/schemas/custom_game.py` — в `CustomGameBalanceRequest` расширить литерал:

```python
class CustomGameBalanceRequest(_Request):
    """Что балансировать. Пустое тело = первое лобби, как до появления второго.

    ``scope="all"`` перемешивает оба лобби разом и требует ``lobby_count = 2``.
    """

    scope: Literal["lobby", "all"] = "lobby"
    lobby_index: int = Field(0, ge=0, le=1)
```

**3.6.** `backend/balancer-service/src/rpc/custom.py`, хендлер `_balance` — добавить строку `scope=body.scope,` перед `lobby_index=`:

```python
            game = await custom_game_service.balance(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                scope=body.scope,
                lobby_index=body.lobby_index,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
```

**3.7.** `backend/balancer-service/src/openapi_docs.py` — заменить описание `custom.balance`:

```python
    "rpc.balancer.custom.balance": {
        "summary": "Balance custom game",
        "description": (
            "Permission: workspace membership plus being the mix's host or co-host (or a superuser). "
            "With `scope=\"lobby\"` (the default) balances the non-benched lineup of ONE lobby "
            "(`lobby_index`, default 0) -- everyone the other lobby is already playing or holds a pin "
            "on is left out. With `scope=\"all\"` it splits the whole pool into two equally strong "
            "lobbies and balances both. Ranks come from the host's own book above the workspace canon. "
            "422 when the lineup is empty, a seated player has no ranked role, the mix has one lobby "
            "(`single_lobby`) or the pool cannot be split (`not_enough_for_two_lobbies`, "
            "`too_many_must_play`, `too_many_pinned`, `roles_infeasible`)."
        ),
    },
```

**3.8.** перегенерировать манифест схем. Из `backend/`:

```bash
bash scripts/export_openapi_schemas.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Из `backend/`:

```bash
uv run pytest balancer-service/tests/test_custom_game.py balancer-service/tests/test_custom_game_contract.py balancer-service/tests/test_mix_lobby_split.py -q
bash scripts/export_openapi_schemas.sh --check
uv run python scripts/check_rpc_docs.py
```

Ожидание: всё PASS, `schemas.json is up to date`.

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/custom_game.py \
        backend/balancer-service/src/schemas/custom_game.py \
        backend/balancer-service/src/rpc/custom.py \
        backend/balancer-service/src/openapi_docs.py \
        backend/balancer-service/tests/test_custom_game.py \
        backend/balancer-service/tests/test_custom_game_contract.py \
        gateway/internal/openapi/schemas.json
git commit -m "feat(balancer): reshuffle both mix lobbies at once"
```

---

### Task B9: Пер-лобби вызовы, активное лобби и вкладки

**Files:**
- Modify: `frontend/src/services/custom-game.service.ts` — якоря по именам (A8 вставил между ними свои типы, ключ `me` и шесть функций): `CustomGameMatch`, `CustomGamePlayer`, `CustomGamePlayerPatch`, `customGameKeys.rotation`, методы `balance`, `recordOutcome`, `rotation`, `setNextMap`, `setVariantIndex`, `swapSeats`, `postToDiscord` (+ новый `setLobbyCount` сразу после `postToDiscord`, перед блоком A-шных self-функций)
- Modify: `frontend/src/app/balancer/mix/pickup-lineup.ts:12-16` (`PickupRecordOutcomeInput`), `:325-334` (`teamNamesByIndex`) — A этот файл не трогает
- Modify: `frontend/src/app/balancer/mix/usePickupMix.ts` — якоря по именам: сигнатура `export function usePickupMix(` (третий аргумент A10 сохраняется), вставка `activeLobby` перед `const rotationQuery`, сам `rotationQuery`, `applyGame`, мутации `postToDiscord` / `swapSeats` / `balance` / `recordOutcome` / `setNextMap` / `setVariantIndex`, блок `return`
- Modify: `frontend/src/app/balancer/mix/PickupTeamsPanel.tsx:74-166`, `:216-260`, `:270-285`, `:355-370`, `:460-468`, `:594-627`, `:821-940` — A этот файл не трогает, номера актуальны
- Modify: `frontend/src/app/balancer/mix/[gameId]/page.tsx` — деструктуризация `usePickupMix` (после A10 в ней есть `mySeatQuery` и пять self-мутаций), `<PickupMixHeader …>` (после A10 у него четыре self-пропса) и `<PickupTeamsPanel …>`; блок `<PickupMySeatPanel …>` под ним не трогаем
- Create: `frontend/src/app/balancer/mix/PickupLobbyTabs.tsx`
- Modify: `frontend/src/i18n/messages/ru.json`, `frontend/src/i18n/messages/en.json` (новое поддерево `mixes.lobbies` — сразу после `mixes.self`, заведённого A9)
- Test: `frontend/src/app/balancer/mix/PickupLobbyTabs.behavior.test.tsx` (новый), `PickupTeamsPanel.behavior.test.tsx`, `usePickupMix.behavior.test.tsx` (трёхаргументный `customGameKeys.rotation` в моке, переписанном A10)

**Interfaces:**
- Consumes: `CustomGameLobby`, `CustomGame.lobbies`, `CustomGame.lobby_count` (задача B2); RPC `set_lobby_count`, `lobby_index` в телах пер-лобби RPC (задачи B1/B5); `CustomGameBalanceRequest{scope, lobby_index}` (`B6–B8`).
- Produces:
  - `customGameService.balance(workspaceId: number, gameId: number, request: { scope: "lobby"; lobbyIndex: 0 | 1 } | { scope: "all" }): Promise<CustomGame>`
  - `customGameService.setNextMap(workspaceId: number, gameId: number, lobbyIndex: 0 | 1, mapId: number | null): Promise<CustomGame>`
  - `customGameService.setVariantIndex(workspaceId: number, gameId: number, lobbyIndex: 0 | 1, variantIndex: number): Promise<CustomGame>`
  - `customGameService.swapSeats(workspaceId: number, gameId: number, lobbyIndex: 0 | 1, variantIndex: number, firstUuid: string, secondUuid: string): Promise<CustomGame>`
  - `customGameService.recordOutcome(workspaceId: number, gameId: number, lobbyIndex: 0 | 1, outcome: CustomGameOutcome, variantIndex: number): Promise<CustomGame>`
  - `customGameService.postToDiscord(workspaceId: number, gameId: number, lobbyIndex: 0 | 1, variantIndex: number, image?: Blob | null): Promise<{ status: "queued"; channel_id: string }>`
  - `customGameService.rotation(workspaceId: number, gameId: number, lobbyIndex: 0 | 1): Promise<RotationRecommendation[]>`
  - `customGameService.setLobbyCount(workspaceId: number, gameId: number, lobbyCount: 1 | 2): Promise<CustomGame>`
  - `customGameKeys.rotation(workspaceId: number, gameId: number, lobbyIndex: number)`
  - `PickupRecordOutcomeInput = { outcome: CustomGameOutcome; variantIndex: number; lobbyIndex: 0 | 1 }`
  - `teamNamesByIndex(settings: CustomGameSettings | undefined, lobbyIndex?: number): Record<number, string>`
  - `usePickupMix(...)` дополнительно возвращает `activeLobby: 0 | 1`, `setActiveLobby: (index: 0 | 1) => void`, `setLobbyCount` (мутация)
  - `<PickupLobbyTabs lobbies activeLobby onSelect maps />`
  - i18n `mixes.lobbies.*` (ru + en), поддерево заводится здесь: `tabsLabel`, `tab` (аргумент `letter`), `game` (аргумент `number`), `notRecorded`, `notBalanced`, `rebalanceTitle`, `rebalanceDescription`, `rebalanceConfirm`

- [ ] **Step 1: Write the failing test**

Новый файл `frontend/src/app/balancer/mix/PickupLobbyTabs.behavior.test.tsx`:

```tsx
// @vitest-environment happy-dom
//
// The tabs are the only way a host reaches lobby B, so three things are
// load-bearing:
//
//  1. a one-lobby mix renders nothing at all -- the control would be a tab bar
//     with a single tab, which is chrome describing itself;
//  2. picking a tab reports the lobby to the page, which owns `activeLobby`;
//  3. each tab carries the state a host decides on without opening it: which
//     game that lobby is on, whether its current lineup is still unrecorded,
//     and what it is about to play.
//
// Every string here is a `mixes.lobbies.*` message, so next-intl is mocked to
// echo the key (and its arguments) rather than a translation -- the same shape
// the other mix-board behaviour tests use.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGameLobby } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

import { PickupLobbyTabs } from "./PickupLobbyTabs";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// `key` alone, or `key:arg,arg` when the message interpolates: the lobby
// status is the one place a VALUE is load-bearing (which game the lobby is on),
// so the mock keeps the arguments instead of collapsing to the key.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${Object.values(values).join(",")}` : key,
}));

const onSelect = vi.fn();

const CONTROL = { id: 1, name: "Control", slug: "control", image_path: "", description: "", aliases: [] };

function mapRead(id: number, name: string): MapRead {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_path: "",
    gamemode_id: CONTROL.id,
    in_competitive: true,
    aliases: [],
    gamemode: CONTROL,
  };
}

const CATALOGUE = [mapRead(6, "Ilios"), mapRead(7, "Busan")];

function lobbyRow(overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: 0,
    balance_result: null,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: "2026-01-01T00:00:00Z",
    lineup_recorded: true,
    matches_count: 0,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(lobbies: CustomGameLobby[], activeLobby: 0 | 1 = 0) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupLobbyTabs
        lobbies={lobbies}
        activeLobby={activeLobby}
        maps={CATALOGUE}
        onSelect={onSelect}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function tabs(scope: ParentNode) {
  return [...scope.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  onSelect.mockReset();
});

describe("PickupLobbyTabs", () => {
  it("renders nothing for a mix that runs one lobby", async () => {
    const scope = await mount([lobbyRow()]);

    expect(tabs(scope)).toHaveLength(0);
    expect(scope.textContent).toBe("");
  });

  it("switches the page to the lobby the host picked", async () => {
    const scope = await mount([lobbyRow(), lobbyRow({ lobby_index: 1 })]);

    expect(tabs(scope).map((node) => node.getAttribute("aria-selected"))).toEqual(["true", "false"]);

    await click(tabs(scope)[1]);

    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("marks the tab the page is already on instead of reporting it again", async () => {
    const scope = await mount([lobbyRow(), lobbyRow({ lobby_index: 1 })], 1);

    expect(tabs(scope).map((node) => node.getAttribute("aria-selected"))).toEqual(["false", "true"]);

    await click(tabs(scope)[1]);

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("says which game each lobby is on, and names the map it is about to play", async () => {
    const scope = await mount([
      lobbyRow({ matches_count: 4, next_map_id: 6 }),
      lobbyRow({ lobby_index: 1, matches_count: 2, next_map_id: 7 }),
    ]);

    expect(tabs(scope)[0].textContent).toContain("tab:A");
    expect(tabs(scope)[0].textContent).toContain("game:5");
    expect(tabs(scope)[0].textContent).toContain("Ilios");
    expect(tabs(scope)[1].textContent).toContain("tab:B");
    expect(tabs(scope)[1].textContent).toContain("game:3");
    expect(tabs(scope)[1].textContent).toContain("Busan");
  });

  it("flags a lobby whose balanced lineup has not been recorded yet", async () => {
    const scope = await mount([
      lobbyRow(),
      lobbyRow({ lobby_index: 1, lineup_recorded: false }),
    ]);

    expect(tabs(scope)[0].textContent).not.toContain("notRecorded");
    expect(tabs(scope)[1].textContent).toContain("notRecorded");
  });

  it("says nothing about a lobby that has never been balanced", async () => {
    const scope = await mount([
      lobbyRow(),
      lobbyRow({ lobby_index: 1, balanced_at: null, lineup_recorded: true, matches_count: 0 }),
    ]);

    expect(tabs(scope)[1].textContent).toContain("notBalanced");
    expect(tabs(scope)[1].textContent).not.toContain("game:1");
  });
});
```

И в `frontend/src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx` — три новых теста в конец `describe("PickupTeamsPanel", …)`, плюс расширение `mount` под новый проп. В `mount` (строки 197-251) заменить блок пропов так, чтобы панель получала лобби явно:

```tsx
async function mount(
  current: CustomGame | undefined,
  props: {
    canWrite?: boolean;
    activeCount?: number;
    variantIndex?: number;
    lobbyIndex?: 0 | 1;
    hasMix?: boolean;
    omitSwapSeats?: boolean;
    maps?: MapRead[];
    matches?: CustomGameMatch[];
    undoingMatchId?: number | null;
    omitUndoMatch?: boolean;
    omitPostToDiscord?: boolean;
  } = {},
) {
  const lobbyIndex = props.lobbyIndex ?? 0;
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupTeamsPanel
        canWrite={props.canWrite ?? true}
        gamesLoading={false}
        gamesError={false}
        onRetryGames={vi.fn()}
        game={current}
        lobby={current?.lobbies.find((row) => row.lobby_index === lobbyIndex)}
        lobbyIndex={lobbyIndex}
        gameLoading={false}
        hasMix={props.hasMix ?? current != null}
        balancing={false}
        activeCount={props.activeCount ?? 10}
        onBalance={onBalance}
        variantIndex={props.variantIndex ?? 0}
        onVariantIndexChange={onVariantIndexChange}
        recordingOutcome={false}
        onRecordOutcome={onRecordOutcome}
        matches={props.matches ?? []}
        undoingMatchId={props.undoingMatchId ?? null}
        onUndoMatch={props.omitUndoMatch ? undefined : onUndoMatch}
        maps={props.maps ?? []}
        settingNextMap={false}
        onNextMapChange={onNextMapChange}
        closingMix={false}
        onCloseMix={onCloseMix}
        onRenameTeam={onRenameTeam}
        onSwapSeats={props.omitSwapSeats ? undefined : onSwapSeats}
        onCopyBattleTags={onCopyBattleTags}
        postingToDiscord={false}
        onPostToDiscord={props.omitPostToDiscord ? undefined : onPostToDiscord}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}
```

Фикстура `match()` (строки 173-189) получает `lobby_index`:

```tsx
function match(overrides: Partial<CustomGameMatch> = {}): CustomGameMatch {
  return {
    id: 2,
    home_team_name: "Wolves",
    away_team_name: "Bears",
    home_score: 1,
    away_score: 0,
    winner: 1,
    map_id: 5,
    map_name: "King's Row",
    map_image_path: null,
    recorded_by: 9,
    recorded_at: new Date().toISOString(),
    points_per_win_applied: null,
    lobby_index: 0,
    ...overrides,
  };
}
```

Новые тесты:

```tsx
  it("records a result for the lobby it is showing, not always the first", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, { lobbyIndex: 1, variantIndex: 1 });

    await click(byName(scope, "Team 1 win"));

    expect(onRecordOutcome).toHaveBeenCalledWith({
      outcome: { winner: 1 },
      variantIndex: 1,
      lobbyIndex: 1,
    });
  });

  it("renames lobby B's teams at their global indices, not at 0 and 1", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, { lobbyIndex: 1 });

    const pencils = [...scope.querySelectorAll('button[aria-label="Edit team name"]')];
    await click(pencils[0]);
    const field = inputByLabel(scope, "team name");
    await typeInto(field as HTMLInputElement, "Ravens");
    await click(scope.querySelector('button[aria-label="Save team name"]'));

    // A: 0-1, B: 2-3 -- the same `CustomGameTeamName.team_index` the host's
    // override for lobby A already uses.
    expect(onRenameTeam).toHaveBeenCalledWith(2, "Ravens");
  });

  it("shows lobby B its own stored name override", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
      settings: { ...SETTINGS, team_names: { "0": "Wolves", "2": "Ravens" } },
    });
    const scope = await mount(twoLobbies, { lobbyIndex: 1 });

    expect(scope.textContent).toContain("Ravens");
    expect(scope.textContent).not.toContain("Wolves");
  });

  it("asks before rebalancing a lobby whose lineup is still unrecorded", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow({ lineup_recorded: false })] }));

    await click(byName(scope, "Balance teams"));
    expect(onBalance).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "rebalanceDescription",
    );

    await click(byName(document, "rebalanceConfirm"));
    expect(onBalance).toHaveBeenCalledTimes(1);
  });

  it("balances straight away once this lobby's last lineup has been recorded", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow({ lineup_recorded: true })] }));

    await click(byName(scope, "Balance teams"));

    expect(onBalance).toHaveBeenCalledTimes(1);
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  });

  it("offers an undo on the newest match of each lobby, not only on the newest of the mix", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, {
      matches: [
        match({ id: 12, lobby_index: 0 }),
        match({ id: 11, lobby_index: 1 }),
        match({ id: 10, lobby_index: 0 }),
      ],
    });

    // 12 is A's newest, 11 is B's newest; 10 sits under 12 in the same lobby.
    expect(scope.querySelectorAll('button[aria-label="Undo this match"]')).toHaveLength(2);
  });

  it("marks which lobby each recorded match belongs to once the mix runs two", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, {
      matches: [match({ id: 12, lobby_index: 0 }), match({ id: 11, lobby_index: 1 })],
    });

    const chips = [...scope.querySelectorAll('[data-testid="match-lobby"]')].map((node) =>
      node.textContent?.trim(),
    );
    expect(chips).toEqual(["A", "B"]);
  });

  it("leaves the history unchipped while the mix has run one lobby all along", async () => {
    const scope = await mount(game(), { matches: [match({ id: 12 })] });

    expect(scope.querySelector('[data-testid="match-lobby"]')).toBeNull();
  });
```

- [ ] **Step 2: Run it, expected FAIL**

```bash
cd frontend && bunx vitest run src/app/balancer/mix/PickupLobbyTabs.behavior.test.tsx src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx
bun test src/i18n/messages.parity.test.ts
```

Expected: FAIL. vitest: `PickupLobbyTabs.behavior.test.tsx` падает целиком — `Failed to resolve import "./PickupLobbyTabs"`; в `PickupTeamsPanel.behavior.test.tsx` падают новые тесты — `onRecordOutcome` вызван без `lobbyIndex`, `onRenameTeam` вызван с `0` вместо `2`, подтверждения нет (`onBalance` вызван сразу), кнопок undo одна вместо двух, `[data-testid="match-lobby"]` не найден. bun: `en and ru have identical key sets` остаётся зелёным (поддерева ещё нет ни в одном словаре) — здесь он запускается как регрессионный страж на шаге 3, где ключи добавляются сразу в оба файла.

- [ ] **Step 3: Minimal implementation**

**3.1 `frontend/src/services/custom-game.service.ts`.**

`CustomGameMatch` (строка 147) получает лобби — вставить перед `points_per_win_applied`:

```ts
  /** Which lobby of the mix played it (0 = A, 1 = B). A one-lobby mix records only 0. */
  lobby_index: 0 | 1;
```

`CustomGamePlayerPatch` (строки 168-172) получает пин:

```ts
/** Patch semantics: an omitted key is left untouched on the server. */
export type CustomGamePlayerPatch = {
  participation?: MixParticipation;
  roles?: string[] | null;
  is_flex?: boolean;
  /**
   * Which lobby this player is tied to, or `null` for "wherever the balance
   * puts them". Host-only, and 422 on a mix that runs one lobby.
   */
  lobby_pin?: 0 | 1 | null;
};
```

`CustomGamePlayer` (строки 36-53) получает два читаемых поля — вставить после `is_flex`:

```ts
  /**
   * Which lobby this player is seated in right now, derived server-side from
   * the selected variant of each lobby; `null` means waiting for a seat.
   * Detail reads only.
   */
  current_lobby?: 0 | 1 | null;
  /** The host's own tie to a lobby, independent of where the balance seated them. */
  lobby_pin?: 0 | 1 | null;
```

Ключ очереди — заменить запись `rotation` в `customGameKeys` (пост-A сразу под ней лежит `me` из A8, её не трогаем):

```ts
  rotation: (workspaceId: number, gameId: number, lobbyIndex: number) =>
    ["custom-games", workspaceId, gameId, "rotation", lobbyIndex] as const,
```

Восемь методов:

```ts
  /**
   * Re-runs the solver. `scope: "lobby"` balances that lobby alone, leaving the
   * other one's document, map and pager untouched, and its candidates exclude
   * whoever is seated in the other lobby or pinned to it. `scope: "all"` splits
   * the whole pool into two even lobbies and solves each -- two-lobby mixes only
   * (422 `single_lobby` otherwise).
   */
  balance(
    workspaceId: number,
    gameId: number,
    request: { scope: "lobby"; lobbyIndex: 0 | 1 } | { scope: "all" },
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/balance`, {
      method: "POST",
      body:
        request.scope === "all"
          ? { scope: "all" }
          : { scope: "lobby", lobby_index: request.lobbyIndex },
    }).then((r) => r.json());
  },
```

```ts
  /**
   * Snapshots one played match of one lobby into the permanent casual-match log
   * — team rosters and who won. Repeatable: a mix can record many before its
   * host calls `close`. `variantIndex` is whichever balance option that lobby is
   * showing; the map is that lobby's `next_map_id`, consumed server-side.
   */
  recordOutcome(
    workspaceId: number,
    gameId: number,
    lobbyIndex: 0 | 1,
    outcome: CustomGameOutcome,
    variantIndex: number,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/outcome`, {
      method: "POST",
      body: { lobby_index: lobbyIndex, outcome, variant_index: variantIndex },
    }).then((r) => r.json());
  },
```

```ts
  /**
   * Who is owed the next seat in this lobby and who should rest, ranked from
   * the mix's own map history and split at the seat count a balance of THIS
   * lobby would fill right now. Read-only, feeds the lineup as a hint.
   */
  rotation(workspaceId: number, gameId: number, lobbyIndex: 0 | 1): Promise<RotationRecommendation[]> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/rotation`, {
      query: { lobby_index: lobbyIndex },
    }).then((r) => r.json());
  },
```

```ts
  /**
   * Names the map this lobby's next match is played on, or clears it (`null`).
   * The roll itself happens client-side (`rollNextMap`); this stores the verdict
   * so co-hosts and viewers see the same map and `recordOutcome` stamps it.
   */
  setNextMap(
    workspaceId: number,
    gameId: number,
    lobbyIndex: 0 | 1,
    mapId: number | null,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/next-map`, {
      method: "PUT",
      body: { lobby_index: lobbyIndex, map_id: mapId },
    }).then((r) => r.json());
  },
```

```ts
  /**
   * Pages one lobby to one of the options its last balance produced. Not a local
   * view toggle: the index is stored on the lobby, so co-hosts and viewers move
   * with the host. 404s an index past the stored options; 409 `seat_conflict`
   * when the option would seat somebody the other lobby has already seated.
   */
  setVariantIndex(
    workspaceId: number,
    gameId: number,
    lobbyIndex: 0 | 1,
    variantIndex: number,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/variant`, {
      method: "PUT",
      body: { lobby_index: lobbyIndex, variant_index: variantIndex },
    }).then((r) => r.json());
  },
```

```ts
  /**
   * Swap two seated players between the teams of ONE lobby, same role only -- a
   * same-role swap can never break a team's role quota, so it needs no
   * eligibility check beyond "both exist and share a role". `variantIndex` edits
   * whichever balance option that lobby is showing, not always the first.
   */
  swapSeats(
    workspaceId: number,
    gameId: number,
    lobbyIndex: 0 | 1,
    variantIndex: number,
    firstUuid: string,
    secondUuid: string,
  ): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/teams/swap`, {
      method: "POST",
      body: {
        lobby_index: lobbyIndex,
        variant_index: variantIndex,
        first_uuid: firstUuid,
        second_uuid: secondUuid,
      },
    }).then((r) => r.json());
  },
```

```ts
  /**
   * Posts one lobby's current matchup -- teams and its next map -- to the mix's
   * Discord channel. Fire-and-forget: the response only says the message was
   * queued for the bot. `variantIndex` is whichever balance option that lobby is
   * showing.
   *
   * `image` is that matchup rasterised in the browser; it is what the bot
   * attaches. Passing `null` (a capture that failed, or a caller with no node
   * to capture) posts the server's text embed instead.
   */
  async postToDiscord(
    workspaceId: number,
    gameId: number,
    lobbyIndex: 0 | 1,
    variantIndex: number,
    image: Blob | null = null,
  ): Promise<{ status: "queued"; channel_id: string }> {
    const response = await apiFetch(
      `/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/discord/post`,
      {
        method: "POST",
        body: {
          lobby_index: lobbyIndex,
          variant_index: variantIndex,
          image_b64: image ? await blobToBase64(image) : null,
        },
      },
    );
    return response.json();
  },

  /**
   * How many lobbies this mix runs. 1 -> 2 opens an empty lobby B; 2 -> 1 drops
   * lobby B's row (its balance is lost, its recorded matches stay in the
   * history) and clears every player's `lobby_pin`.
   *
   * Placed right after `postToDiscord`, ahead of the self-signup block A8
   * appended (`getMySeat`…`postSignup`) -- host writes stay together.
   */
  setLobbyCount(workspaceId: number, gameId: number, lobbyCount: 1 | 2): Promise<CustomGame> {
    return apiFetch(`/api/v1/balancer/workspaces/${workspaceId}/custom-games/${gameId}/lobbies`, {
      method: "PUT",
      body: { lobby_count: lobbyCount },
    }).then((r) => r.json());
  },
```

**3.2 `frontend/src/app/balancer/mix/pickup-lineup.ts`.**

Строки 12-16:

```ts
/** What recording a match needs: the click, which balance option it was played from, and whose lobby it was. */
export type PickupRecordOutcomeInput = {
  outcome: CustomGameOutcome;
  variantIndex: number;
  lobbyIndex: 0 | 1;
};
```

Строки 319-334 (`teamNamesByIndex`) — переводим глобальный индекс в локальный:

```ts
/**
 * A host's team-name overrides re-keyed by the position `parseVariants` assigns
 * names by -- which is a position INSIDE one lobby. Team names are stored
 * relationally (`custom.set_team_names`) at their global index
 * (`lobby_index * 2 + team`, A: 0-1, B: 2-3), so lobby B's overrides shift down
 * by two here and lobby A's drop out of B's map entirely.
 */
export function teamNamesByIndex(
  settings: CustomGameSettings | undefined,
  lobbyIndex = 0,
): Record<number, string> {
  const offset = lobbyIndex * 2;
  const out: Record<number, string> = {};
  for (const [key, value] of Object.entries(settings?.team_names ?? {})) {
    const index = Number(key) - offset;
    if (Number.isInteger(index) && index >= 0 && value.trim()) {
      out[index] = value;
    }
  }
  return out;
}
```

**3.3 Новый файл `frontend/src/app/balancer/mix/PickupLobbyTabs.tsx`.** Каждая строка компонента — сообщение `mixes.lobbies.*`; буквы `A`/`B` — глифы, одинаковые в обеих локалях:

```tsx
"use client";

import { useTranslations } from "next-intl";

import { CAPTION_CLASS, teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { cn } from "@/lib/utils";
import type { CustomGameLobby } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

/** A: 0, B: 1 -- the same letters the team-name offset and the Discord embed use. */
const LOBBY_LETTERS = ["A", "B"] as const;

type PickupLobbyTabsProps = {
  /** The mix's lobbies, ordered by `lobby_index`. One of them renders nothing. */
  lobbies: CustomGameLobby[];
  activeLobby: 0 | 1;
  /** The OW catalogue, so a tab can name the map its lobby is about to play. */
  maps: MapRead[];
  onSelect: (lobbyIndex: 0 | 1) => void;
};

/**
 * The only way a host reaches lobby B. Tabs rather than two matchups side by
 * side because the matchup column is capped at 1180px next to a 568px lineup
 * (see `[gameId]/page.tsx`) -- two do not fit, and half a matchup is worse than
 * one whole one.
 *
 * Each tab carries what a host decides on without opening it: which game that
 * lobby is on, whether the lineup currently on its screen has been recorded,
 * and what it is about to play. A mix running one lobby renders nothing at all:
 * a tab bar with a single tab is chrome describing itself.
 */
export function PickupLobbyTabs({
  lobbies,
  activeLobby,
  maps,
  onSelect
}: Readonly<PickupLobbyTabsProps>) {
  const t = useTranslations("mixes.lobbies");

  if (lobbies.length < 2) {
    return null;
  }

  return (
    <div
      role="tablist"
      aria-label={t("tabsLabel")}
      className="flex gap-1.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-1"
    >
      {lobbies.map((lobby) => {
        const selected = lobby.lobby_index === activeLobby;
        const accent = teamAccent(lobby.lobby_index);
        return (
          <button
            key={lobby.lobby_index}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => {
              if (!selected) onSelect(lobby.lobby_index);
            }}
            className={cn(
              "flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left transition-colors",
              selected
                ? "border-[color:var(--aqt-border-3)] bg-[color:var(--aqt-overlay-3)]"
                : "border-transparent hover:bg-[color:var(--aqt-overlay-2)]"
            )}
          >
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className={cn("h-3 w-[3px] shrink-0 rounded-sm", accent.bar)} />
              <span
                className={cn(
                  "font-display text-sm font-bold tracking-[0.01em]",
                  selected ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]"
                )}
              >
                {t("tab", { letter: LOBBY_LETTERS[lobby.lobby_index] })}
              </span>
            </span>
            <span className={cn(CAPTION_CLASS, "truncate")}>{lobbyStatus(lobby, maps, t)}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * One lobby's line, in the order a host reads it: how far along it is, whether
 * the lineup on its screen is still unplayed-and-unrecorded, and what it plays
 * next. A lobby that has never been balanced says so instead of claiming
 * "game 1": nothing has been set up to play yet.
 *
 * Takes the translator rather than calling the hook: it is a plain function,
 * not a component, and a hook here would break the rules of hooks.
 */
function lobbyStatus(
  lobby: CustomGameLobby,
  maps: MapRead[],
  t: (key: string, values?: Record<string, unknown>) => string,
): string {
  const parts: string[] = [];
  if (lobby.balanced_at == null) {
    parts.push(t("notBalanced"));
  } else {
    parts.push(t("game", { number: (lobby.matches_count ?? 0) + 1 }));
    if (lobby.lineup_recorded === false) {
      parts.push(t("notRecorded"));
    }
  }
  const map = lobby.next_map_id == null ? null : maps.find((entry) => entry.id === lobby.next_map_id);
  if (map) {
    parts.push(map.name);
  }
  return parts.join(" \u00B7 ");
}
```

**3.4 `frontend/src/app/balancer/mix/PickupTeamsPanel.tsx`.** Новые строки (подтверждение перебаланса, подпись чипа лобби) — через `useTranslations("mixes.lobbies")`; существующие литералы (`Balance teams`, `Next map`, `Close mix`, диалоги закрытия и отмены матча) не трогаем.

Импорты (строка 3 и строка 56):

```tsx
import { useState } from "react";
import { useTranslations } from "next-intl";
```

```tsx
import type { CustomGame, CustomGameLobby, CustomGameMatch } from "@/services/custom-game.service";
```

Пропы (строки 74-120) — добавить два и переписать комментарий пейджера:

```tsx
type PickupTeamsPanelProps = {
  canWrite: boolean;
  gamesLoading: boolean;
  gamesError: boolean;
  onRetryGames: () => void;
  game: CustomGame | undefined;
  /** The one lobby this panel is showing. `undefined` before the mix loads. */
  lobby: CustomGameLobby | undefined;
  /** Its index, which is also the offset of its team names (`lobbyIndex * 2 + team`). */
  lobbyIndex: 0 | 1;
  gameLoading: boolean;
  hasMix: boolean;
  balancing: boolean;
  activeCount: number;
  /** Re-runs the solver for THIS lobby. The confirm for an unrecorded lineup is this panel's. */
  onBalance: () => void;
  /**
   * Which of the solver's options is on screen — this lobby's own
   * `selected_variant_index`, so the host's pager moves every viewer with it.
   * Viewers get no pager at all: the matchup is read out to a lobby, and a
   * player quietly paging their own copy is looking at teams nobody is playing.
   */
  variantIndex: number;
  onVariantIndexChange: (index: number) => void;
  recordingOutcome: boolean;
  onRecordOutcome: (input: PickupRecordOutcomeInput) => void;
  /** The permanent record of every match this mix has played, both lobbies, newest first. */
  matches: CustomGameMatch[];
  /** The match whose undo is in flight, so only that row spins. */
  undoingMatchId?: number | null;
  /** Omitted -- the history renders read-only, matching a page that offers no undo. */
  onUndoMatch?: (matchId: number) => void;
  /** The OW map catalogue with its gamemodes -- the roll pool and the manual picker. */
  maps: MapRead[];
  settingNextMap: boolean;
  /** Rolled or hand-picked; `null` clears. Persisted per lobby server-side. */
  onNextMapChange: (mapId: number | null) => void;
  closingMix: boolean;
  onCloseMix: () => void;
  /** Takes the GLOBAL team index (`lobbyIndex * 2 + team`). Omitted -- team headers render read-only. */
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  /** Omitted -- seats render without drag handles, matching a `canWrite=false` viewer. */
  onSwapSeats?: (
    variantIndex: number,
    firstUuid: string,
    secondUuid: string
  ) => void | Promise<unknown>;
  onCopyBattleTags: () => void;
  postingToDiscord?: boolean;
  /** Omitted -- no Post to Discord button, matching a page that offers no post. */
  onPostToDiscord?: (variantIndex: number, image: Blob | null) => void;
};
```

Тело (строки 132-166) — принять новые пропы и читать лобби из них:

```tsx
export function PickupTeamsPanel({
  canWrite,
  gamesLoading,
  gamesError,
  onRetryGames,
  game,
  lobby,
  lobbyIndex,
  gameLoading,
  hasMix,
  balancing,
  activeCount,
  onBalance,
  variantIndex,
  onVariantIndexChange,
  recordingOutcome,
  onRecordOutcome,
  matches,
  undoingMatchId = null,
  onUndoMatch,
  maps,
  settingNextMap,
  onNextMapChange,
  closingMix,
  onCloseMix,
  onRenameTeam,
  onSwapSeats,
  onCopyBattleTags,
  postingToDiscord = false,
  onPostToDiscord
}: Readonly<PickupTeamsPanelProps>) {
  const t = useTranslations("mixes.lobbies");
  const variants = parseVariants(lobby?.balance_result, teamNamesByIndex(game?.settings, lobbyIndex));
  // Clamped rather than reset in an effect: a shorter result must not leave the
  // pager pointing past the end.
  const index = Math.min(variantIndex, Math.max(0, variants.length - 1));
  const variant = variants[index];
  const pointsPerWin = game?.settings.points_per_win ?? null;
  const lobbyCount = game?.lobby_count ?? 1;
  // The matchup card is a self-contained graphic, so "share the teams" here needs
  // no detour through the fullscreen board.
  const { ref: captureRef, capturing, capture, rasterize } = useNodeCapture();
  const [closeOpen, setCloseOpen] = useState(false);
  // A balance replaces this lobby's lineup. If the lineup on screen was never
  // played into the log, that is a result about to be lost, so it is the one
  // case the button asks first.
  const [balanceOpen, setBalanceOpen] = useState(false);
  const lineupAtRisk = lobby?.lineup_recorded === false;
```

Вызов `NextMapStrip` уже получает `nextMapId={lobby?.next_map_id ?? null}` после задачи B2 — менять нечего, `lobby` теперь приходит пропом, а не вычисляется здесь.

Блок результата (строки 255-266):

```tsx
        {variant && canWrite ? (
          <PickupResultControls
            teamCount={variant.teams.length}
            teamNames={variant.teams.map((team) => team.name)}
            saving={recordingOutcome}
            pointsPerWin={pointsPerWin}
            onRecord={(recordedOutcome) =>
              onRecordOutcome({ outcome: recordedOutcome, variantIndex: index, lobbyIndex })
            }
          />
        ) : null}
```

Кнопка Balance (строки 270-295) — подтверждение перед перезаписью несыгранного лайнапа:

```tsx
          {canWrite ? (
            <>
              <Button
                type="button"
                className="h-9"
                disabled={balancing || activeCount === 0}
                onClick={() => (lineupAtRisk ? setBalanceOpen(true) : onBalance())}
                title={
                  activeCount > LOBBY_SIZE
                    ? `${activeCount - LOBBY_SIZE} extra player${activeCount - LOBBY_SIZE === 1 ? "" : "s"} will be benched automatically -- rotation fairness picks who`
                    : undefined
                }
              >
                {balancing ? (
                  <Spinner className="mr-1.5 size-3.5" />
                ) : (
                  <Shuffle className="mr-1.5 size-3.5" aria-hidden="true" />
                )}
                Balance teams
              </Button>
              <ConfirmDialog
                open={balanceOpen}
                onOpenChange={setBalanceOpen}
                intent={{
                  title: t("rebalanceTitle"),
                  description: t("rebalanceDescription"),
                  confirmLabel: t("rebalanceConfirm"),
                  tone: "danger"
                }}
                pending={balancing}
                onConfirm={() => {
                  setBalanceOpen(false);
                  onBalance();
                }}
              />
            </>
          ) : null}
```

Post to Discord (строки 355-371) — остаётся `onPostToDiscord(index, image)`; страница подставляет лобби.

История (строки 434-441) — прокинуть `lobbyCount`:

```tsx
        {matches.length > 0 ? (
          <MatchHistoryList
            matches={matches}
            lobbyCount={lobbyCount}
            canWrite={canWrite}
            undoingMatchId={undoingMatchId}
            onUndoMatch={onUndoMatch}
          />
        ) : null}
```

`VariantView` (строка 232) — сдвиг индекса при переименовании:

```tsx
              <VariantView
                variant={variant}
                canWrite={canWrite}
                capturing={capturing}
                onRenameTeam={
                  onRenameTeam &&
                  ((teamIndex, name) => onRenameTeam(lobbyIndex * 2 + teamIndex, name))
                }
                onSwapSeats={
                  onSwapSeats &&
                  ((firstUuid, secondUuid) => onSwapSeats(index, firstUuid, secondUuid))
                }
              />
```

`MatchHistoryList` (строки 594-627) — отмена у самого нового матча каждого лобби и чип:

```tsx
/** Every match this mix has recorded, both lobbies, newest first — the permanent record `Record result` writes into. */
function MatchHistoryList({
  matches,
  lobbyCount,
  canWrite,
  undoingMatchId,
  onUndoMatch
}: Readonly<{
  matches: CustomGameMatch[];
  lobbyCount: number;
  canWrite: boolean;
  undoingMatchId: number | null;
  onUndoMatch?: (matchId: number) => void;
}>) {
  // Newest first, so the first row of each lobby IS that lobby's newest -- the
  // only one the server will undo (`newest_id_for_lobby`).
  const newestPerLobby = new Set<number>();
  const seenLobbies = new Set<number>();
  for (const match of matches) {
    if (!seenLobbies.has(match.lobby_index)) {
      seenLobbies.add(match.lobby_index);
      newestPerLobby.add(match.id);
    }
  }
  // A mix that switched back to one lobby keeps lobby B's matches in the log,
  // so the chip follows the history as well as the current count.
  const showLobby = lobbyCount > 1 || seenLobbies.has(1);

  return (
    <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
      <span className={cn(EYEBROW_CLASS, "flex items-center gap-1.5 tracking-label")}>
        <History className="size-3.5" aria-hidden="true" />
        Match history
      </span>
      <ul className="flex flex-col gap-1.5">
        {matches.map((match) => (
          <MatchHistoryRow
            key={match.id}
            match={match}
            showLobby={showLobby}
            canUndo={newestPerLobby.has(match.id) && canWrite && onUndoMatch != null}
            undoing={undoingMatchId === match.id}
            onUndoMatch={onUndoMatch}
          />
        ))}
      </ul>
    </div>
  );
}
```

`MatchHistoryRow` (строки 639-650) — сигнатура и чип; вставить чип первым элементом строки, перед миниатюрой карты:

```tsx
function MatchHistoryRow({
  match,
  showLobby,
  canUndo,
  undoing,
  onUndoMatch
}: Readonly<{
  match: CustomGameMatch;
  /** Two lobbies now, or lobby B somewhere in the log: say which one played it. */
  showLobby: boolean;
  canUndo: boolean;
  undoing: boolean;
  onUndoMatch?: (matchId: number) => void;
}>) {
  const t = useTranslations("mixes.lobbies");
  const homeAccent = teamAccent(0);
  const awayAccent = teamAccent(1);
  const lobbyAccent = teamAccent(match.lobby_index);
  // A: 0, B: 1 -- glyphs, identical in every locale, like a team number.
  const lobbyLetter = match.lobby_index === 0 ? "A" : "B";
  const [undoOpen, setUndoOpen] = useState(false);

  return (
    <li className="flex items-center gap-3 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-2.5 py-2">
      {showLobby ? (
        <span
          data-testid="match-lobby"
          title={t("tab", { letter: lobbyLetter })}
          className={cn(
            "flex size-5 shrink-0 items-center justify-center rounded font-display text-label font-extrabold",
            lobbyAccent.bar,
            "text-[color:var(--aqt-bg)]"
          )}
        >
          {lobbyLetter}
        </span>
      ) : null}
```

(остальная часть `MatchHistoryRow` без изменений)

**3.5 `frontend/src/app/balancer/mix/usePickupMix.ts`.** Пост-A файл уже имеет третий аргумент `options`, `mySeatQuery` сразу под `rotationQuery`, пять self-мутаций перед `return` и шесть их имён в `return`. Ничего из этого не удаляем.

Импорты — добавить `useState` к импорту React-биндингов (строка 3 пост-A файла — `import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";`, выше него A10 положил `import type { RoleCode } …`):

```ts
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
```

Типы входа — заменить `PickupSwapSeatsInput` и дописать рядом (пост-A следом идёт `PickupMySeatInput` из A10, её не трогаем):

```ts
export type PickupSwapSeatsInput = {
  lobbyIndex: 0 | 1;
  variantIndex: number;
  firstUuid: string;
  secondUuid: string;
};

/** Which lobby a balance run covers: one of them, or the whole pool split across both. */
export type PickupBalanceInput = { scope: "lobby"; lobbyIndex: 0 | 1 } | { scope: "all" };
```

Состояние и очередь — вставить `activeLobby` сразу после `gameQuery` и заменить `rotationQuery` целиком (следующий за ним `mySeatQuery` из A10 остаётся как есть):

```ts
  // The lobby on screen. Page state, not server state: two co-hosts may well be
  // watching different lobbies of the same mix.
  const [activeLobby, setActiveLobby] = useState<0 | 1>(0);
  const lobbyCount = gameQuery.data?.lobby_count ?? 1;
  // Dropping to one lobby while B is open would leave the page pointing at a
  // lobby the mix no longer has. Reset during render, React's own pattern for
  // state derived from a prop that must follow it.
  if (activeLobby >= lobbyCount) {
    setActiveLobby(0);
  }

  /**
   * Who is owed the next seat in the open lobby and who should rest, from this
   * mix's own map history -- feeds a hint into the lineup panel, ahead of
   * `balance` rather than as a separate screen (see
   * `mix_rotation.recommend_rotation`). Keyed by lobby: the candidates of lobby
   * A are not the candidates of lobby B.
   */
  const rotationQuery = useQuery({
    queryKey: customGameKeys.rotation(workspaceId, selectedGameId ?? 0, activeLobby),
    queryFn: () => customGameService.rotation(workspaceId, selectedGameId as number, activeLobby),
    enabled: selectedGameId != null,
  });
```

`applyGame` инвалидирует очередь обоих лобби — ключ `rotation` теперь длиннее, поэтому префикс без лобби (строка `void queryClient.invalidateQueries({ queryKey: customGameKeys.rotation(workspaceId, game.id) });`):

```ts
    void queryClient.invalidateQueries({
      queryKey: ["custom-games", workspaceId, game.id, "rotation"],
    });
```

Мутации — заменить существующие по именам; `applySeat` и пять self-мутаций A10, лежащие ниже `setAuthorRanks`, не трогаем:

```ts
  const postToDiscord = useMutation({
    mutationFn: ({
      lobbyIndex,
      variantIndex,
      image,
    }: {
      lobbyIndex: 0 | 1;
      variantIndex: number;
      image: Blob | null;
    }) =>
      customGameService.postToDiscord(
        workspaceId,
        selectedGameId as number,
        lobbyIndex,
        variantIndex,
        image,
      ),
    onSuccess: () => notify.success("Sent to Discord"),
    onError: (error) => notify.apiError(error),
  });
```

```ts
  const swapSeats = useMutation({
    mutationFn: (input: PickupSwapSeatsInput) =>
      customGameService.swapSeats(
        workspaceId,
        selectedGameId as number,
        input.lobbyIndex,
        input.variantIndex,
        input.firstUuid,
        input.secondUuid,
      ),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const balance = useMutation({
    mutationFn: (input: PickupBalanceInput) =>
      customGameService.balance(workspaceId, selectedGameId as number, input),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Teams balanced");
    },
    onError: (error) => notify.apiError(error),
  });

  const recordOutcome = useMutation({
    mutationFn: (input: PickupRecordOutcomeInput) =>
      customGameService.recordOutcome(
        workspaceId,
        selectedGameId as number,
        input.lobbyIndex,
        input.outcome,
        input.variantIndex,
      ),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Result recorded");
    },
    onError: (error) => notify.apiError(error),
  });
```

```ts
  /** The map this lobby's next match is on -- rolled or picked; `null` clears it. */
  const setNextMap = useMutation({
    mutationFn: ({ lobbyIndex, mapId }: { lobbyIndex: 0 | 1; mapId: number | null }) =>
      customGameService.setNextMap(workspaceId, selectedGameId as number, lobbyIndex, mapId),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });
```

```ts
  const setVariantIndex = useMutation({
    mutationFn: ({ lobbyIndex, variantIndex }: { lobbyIndex: 0 | 1; variantIndex: number }) =>
      customGameService.setVariantIndex(
        workspaceId,
        selectedGameId as number,
        lobbyIndex,
        variantIndex,
      ),
    onMutate: ({ lobbyIndex, variantIndex }: { lobbyIndex: 0 | 1; variantIndex: number }) => {
      const key = customGameKeys.one(workspaceId, selectedGameId ?? 0);
      const previous = queryClient.getQueryData<CustomGame>(key);
      if (previous != null) {
        queryClient.setQueryData(key, {
          ...previous,
          lobbies: previous.lobbies.map((row) =>
            row.lobby_index === lobbyIndex ? { ...row, selected_variant_index: variantIndex } : row,
          ),
        });
      }
      return { previous };
    },
    onSuccess: (game) => queryClient.setQueryData(customGameKeys.one(workspaceId, game.id), game),
    onError: (error, _input, context) => {
      if (context?.previous != null) {
        queryClient.setQueryData(customGameKeys.one(workspaceId, selectedGameId ?? 0), context.previous);
      }
      notify.apiError(error);
    },
  });

  /**
   * How many lobbies this mix runs. Going back to one drops lobby B's balance
   * and every pin server-side, so the whole game is re-seeded from the response.
   */
  const setLobbyCount = useMutation({
    mutationFn: (lobbyCount: 1 | 2) =>
      customGameService.setLobbyCount(workspaceId, selectedGameId as number, lobbyCount),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(game.lobby_count === 2 ? "Second lobby opened" : "Back to one lobby");
    },
    onError: (error) => notify.apiError(error),
  });
```

Возврат — заменить блок `return { … }` целиком. Пост-A он уже содержит `mySeatQuery`, `joinMix`, `leaveMix`, `updateMySeat`, `setSelfService`, `postSignup`; ниже они на месте, добавлены только `activeLobby`, `setActiveLobby` и `setLobbyCount`:

```ts
  return {
    selectedGameId,
    activeLobby,
    setActiveLobby,
    gamesQuery,
    gameQuery,
    matchesQuery,
    rotationQuery,
    mySeatQuery,
    createGame,
    setRoster,
    patchPlayer,
    applyRotationHints,
    balance,
    recordOutcome,
    undoMatch,
    setNextMap,
    setVariantIndex,
    setLobbyCount,
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
  };
```

**3.6 `frontend/src/app/balancer/mix/[gameId]/page.tsx`.**

Импорт вкладок рядом с остальными (сразу под `import { PickupMySeatPanel } …`, добавленным A10):

```tsx
import { PickupLobbyTabs } from "@/app/balancer/mix/PickupLobbyTabs";
```

Деструктуризация хука — в пост-A список (`mySeatQuery` после `rotationQuery`, `joinMix`…`postSignup` в конце, третий аргумент `{ seatEnabled: isSignedIn }`) добавить `activeLobby`, `setActiveLobby` после `selectedGameId` и `setLobbyCount` после `setVariantIndex`. Третий аргумент и все имена A остаются.

Перед `return`, рядом с `const rows = game?.players ?? []` — активное лобби как объект:

```tsx
  const lobbies = game?.lobbies ?? [];
  const lobby = lobbies.find((row) => row.lobby_index === activeLobby);
```

Правая колонка — заменить `<PickupMixHeader …>` и `<PickupTeamsPanel …>`, вставив между ними вкладки. Четыре self-пропса заголовка (A9/A10) сохраняются дословно; блок `<PickupMySeatPanel …>`, который A10 поставил **после** `<PickupTeamsPanel …>`, остаётся ниже нетронутым:

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
              settingLobbyCount={setLobbyCount.isPending}
              onLobbyCountChange={(count) => setLobbyCount.mutate(count)}
              shufflingAll={balance.isPending && balance.variables?.scope === "all"}
              onShuffleAll={() => balance.mutate({ scope: "all" })}
            />
            <PickupLobbyTabs
              lobbies={lobbies}
              activeLobby={activeLobby}
              maps={mapsQuery.data ?? []}
              onSelect={setActiveLobby}
            />
            <PickupTeamsPanel
              canWrite={canWrite}
              gamesLoading={gamesQuery.isLoading}
              gamesError={gamesQuery.isError}
              onRetryGames={() => void gamesQuery.refetch()}
              game={game}
              lobby={lobby}
              lobbyIndex={activeLobby}
              gameLoading={gameQuery.isLoading}
              hasMix={selectedGameId != null}
              balancing={balance.isPending}
              activeCount={summarizeLineup(rows).active}
              onBalance={() => balance.mutate({ scope: "lobby", lobbyIndex: activeLobby })}
              variantIndex={lobby?.selected_variant_index ?? 0}
              onVariantIndexChange={(index) =>
                setVariantIndex.mutate({ lobbyIndex: activeLobby, variantIndex: index })
              }
              recordingOutcome={recordOutcome.isPending}
              onRecordOutcome={(input) => recordOutcome.mutate(input)}
              maps={mapsQuery.data ?? []}
              matches={matchesQuery.data ?? []}
              undoingMatchId={undoMatch.isPending ? (undoMatch.variables ?? null) : null}
              onUndoMatch={(matchId) => undoMatch.mutate(matchId)}
              settingNextMap={setNextMap.isPending}
              onNextMapChange={(mapId) => setNextMap.mutate({ lobbyIndex: activeLobby, mapId })}
              closingMix={closeMix.isPending}
              onCloseMix={() => closeMix.mutate()}
              onRenameTeam={(teamIndex, name) => setTeamNames.mutateAsync({ teamIndex, name })}
              onSwapSeats={(idx, firstUuid, secondUuid) =>
                swapSeats.mutateAsync({
                  lobbyIndex: activeLobby,
                  variantIndex: idx,
                  firstUuid,
                  secondUuid,
                })
              }
              onCopyBattleTags={copyBattleTags}
              postingToDiscord={postToDiscord.isPending}
              onPostToDiscord={(idx, image) =>
                postToDiscord.mutate({ lobbyIndex: activeLobby, variantIndex: idx, image })
              }
            />
```

**3.7 i18n — новое поддерево `mixes.lobbies`.** Ставится **сразу после** блока `"self"`, который A9 сделал последним внутри объекта `mixes` (порядок: `list`, `create`, `leaderboard`, `self`, `lobbies`). На закрывающую `}` блока `self` ставится запятая, `lobbies` закрывает объект `mixes` без неё — ниже блоки показаны с запятой на случай, если к моменту исполнения после них появится ещё один сестринский ключ; итоговый JSON должен остаться валидным.

`frontend/src/i18n/messages/en.json`:

```json
    "lobbies": {
      "tabsLabel": "Lobbies",
      "tab": "Lobby {letter}",
      "game": "game {number}",
      "notRecorded": "not recorded",
      "notBalanced": "not balanced",
      "rebalanceTitle": "Rebalance this lobby?",
      "rebalanceDescription": "The result of the lineup on screen has not been recorded. Balancing replaces it, and there will be nothing left to record it from.",
      "rebalanceConfirm": "Balance anyway"
    },
```

`frontend/src/i18n/messages/ru.json`:

```json
    "lobbies": {
      "tabsLabel": "Лобби",
      "tab": "Лобби {letter}",
      "game": "игра {number}",
      "notRecorded": "не записано",
      "notBalanced": "не собрано",
      "rebalanceTitle": "Перебалансировать это лобби?",
      "rebalanceDescription": "Результат состава на экране не записан. Перебаланс заменит его, и записывать будет нечего.",
      "rebalanceConfirm": "Всё равно перебалансировать"
    },
```

**3.8 `frontend/src/app/balancer/mix/usePickupMix.behavior.test.tsx`** — в моке сервиса, переписанном A10, `customGameKeys.rotation` становится трёхаргументным. Без этого мок молча отдаёт ключ без лобби и расходится с настоящим модулем:

```tsx
    rotation: (workspaceId: number, gameId: number, lobbyIndex: number) => [
      "custom-games",
      workspaceId,
      gameId,
      "rotation",
      lobbyIndex,
    ],
```

и рядом со спаями сервиса (`const getMySeat = vi.fn();` и соседи, добавленные A10) — спай для нового вызова:

```tsx
const setLobbyCount = vi.fn();
```

плюс запись в `customGameService` мока, рядом с `setVariantIndex`:

```tsx
    setLobbyCount: (...args: unknown[]) => setLobbyCount(...args),
```

- [ ] **Step 4: Run, expected PASS**

```bash
cd frontend && bunx vitest run src/app/balancer/mix/PickupLobbyTabs.behavior.test.tsx src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx src/app/balancer/mix/pickup-lineup.test.ts src/app/balancer/mix/usePickupMix.behavior.test.tsx
bun test src/i18n/messages.parity.test.ts
```

Expected: PASS обеих команд. (`pickup-lineup.test.ts:168-182` проверяет `teamNamesByIndex` одним аргументом — новый параметр со значением по умолчанию оставляет эти два теста зелёными. Парити-тест — `bun:test`: он проверяет, что `mixes.lobbies` появился в обоих словарях с одинаковым набором ключей.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/custom-game.service.ts \
        frontend/src/app/balancer/mix/pickup-lineup.ts \
        frontend/src/app/balancer/mix/usePickupMix.ts \
        frontend/src/app/balancer/mix/PickupLobbyTabs.tsx \
        frontend/src/app/balancer/mix/PickupLobbyTabs.behavior.test.tsx \
        frontend/src/app/balancer/mix/PickupTeamsPanel.tsx \
        frontend/src/app/balancer/mix/PickupTeamsPanel.behavior.test.tsx \
        frontend/src/app/balancer/mix/[gameId]/page.tsx \
        frontend/src/app/balancer/mix/usePickupMix.behavior.test.tsx \
        frontend/src/i18n/messages/ru.json \
        frontend/src/i18n/messages/en.json
git commit -m "feat(mix): lobby tabs, and every matchup write addresses one lobby"
```

---

### Task B10: Число лобби, пины и бейджи

**Files:**
- Modify: `frontend/src/app/balancer/mix/PickupMixHeader.tsx` — пост-A импорты, тип пропсов, сигнатура и первый ряд карточки (якоря: `type PickupMixHeaderProps = {`, `export function PickupMixHeader({`, блок `Manage access`); второй ряд с self-контролами A9 не трогаем
- Modify: `frontend/src/app/balancer/mix/pickup-lineup.ts:148-191` (`ROLE_DEMAND`, `summarizeRoleSupply`) — A этот файл не трогает
- Modify: `frontend/src/app/balancer/mix/PickupLobbyPanel.tsx:85-105`, `:151-170`, `:397-420`, `:568-580`, `:626-700` — A этот файл не трогает, номера актуальны
- Modify: `frontend/src/app/balancer/mix/PickupPlayerSheet.tsx` — пост-A файл (A10 вынес `SortableRoleCard`/`RoleCardBody` в `PickupRoleOrderEditor.tsx` и заменил блок ролей на `<PickupRoleOrderEditor …>`); якоря: блок импортов, `type PickupPlayerSheetProps = {`, `type RoleDraft = {`, `function buildDraft(`, сигнатура `export function PickupPlayerSheet({`, `handleSave`, закрывающий `</section>` блока Status
- Modify: `frontend/src/app/balancer/mix/PickupMixList.tsx:145-152` — A этот файл не трогает
- Modify: `frontend/src/app/balancer/mix/[gameId]/page.tsx` — пропсы `<PickupLobbyPanel …>` и `<PickupPlayerSheet …>` (якоря по именам компонентов)
- Modify: `frontend/src/i18n/messages/ru.json`, `frontend/src/i18n/messages/en.json` (поддерево `mixes.lobbies`, заведённое задачей B9)
- Test: `PickupMixHeader.behavior.test.tsx`, `PickupLobbyPanel.behavior.test.tsx`, `PickupPlayerSheet.behavior.test.tsx`, `PickupMixList.behavior.test.tsx`, `frontend/src/i18n/messages.parity.test.ts`

**Interfaces:**
- Consumes: `CustomGame.lobby_count`, `CustomGame.lobbies`, `CustomGamePlayer.current_lobby`, `CustomGamePlayer.lobby_pin`, `CustomGamePlayerPatch.lobby_pin` (задачи B2/B9); `setLobbyCount`, `balance({scope:"all"})` (задача B9).
- Produces:
  - `PickupMixHeaderProps` дополнительно: `settingLobbyCount?: boolean`, `onLobbyCountChange?: (lobbyCount: 1 | 2) => void`, `shufflingAll?: boolean`, `onShuffleAll?: () => void`
  - `PickupLobbyPanelProps` дополнительно: `lobbyCount?: 1 | 2`
  - `PickupPlayerSheetProps` дополнительно: `lobbyCount?: 1 | 2`
  - `export const ROLE_DEMAND: Record<RoleCode, number>`
  - `summarizeRoleSupply(rows: CustomGamePlayer[], lobbyCount?: number): RoleSupply[]`
  - i18n `mixes.lobbies.*` (ru + en): `count` (ICU, аргумент `count`), `countLabel`, `shuffleAll`, `shuffleTitle`, `shuffleDescription`, `shuffleConfirm`, `dropTitle`, `dropDescription`, `dropConfirm`, `seatedIn` (аргумент `letter`), `waiting`, `waitingTitle`, `pinHeading`, `pinGroup` (аргумент `name`), `pinOption` (аргументы `option`, `name`), `pinAuto`, `pinA`, `pinB`, `pinHint`

- [ ] **Step 1: Write the failing test**

`frontend/src/app/balancer/mix/PickupMixHeader.behavior.test.tsx` — расширить `mount` и добавить тесты.

Дописать два шпиона рядом с существующими (`onOpenPool`, `onOpenAccess`, а также `onSetSelfService`/`onPostSignup`, добавленными A9):

```tsx
const onLobbyCountChange = vi.fn();
const onShuffleAll = vi.fn();
```

Заменить `mount` (пост-A версия прокидывает `onSetSelfService`/`onPostSignup` — они остаются):

```tsx
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
        settingLobbyCount={false}
        onLobbyCountChange={onLobbyCountChange}
        shufflingAll={false}
        onShuffleAll={onShuffleAll}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}
```

Добавить в `beforeEach` (где уже сбрасываются `onOpenPool`, `onOpenAccess`, `onSetSelfService`, `onPostSignup`) сброс двух новых шпионов:

```tsx
  onLobbyCountChange.mockReset();
  onShuffleAll.mockReset();
```

Хелпер для лобби-строк, рядом с `game()`:

```tsx
function lobbyRow(lobbyIndex: 0 | 1, overrides: Record<string, unknown> = {}) {
  return {
    lobby_index: lobbyIndex,
    balance_result: null,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: "2026-01-01T00:00:00Z",
    lineup_recorded: true,
    matches_count: 0,
    ...overrides,
  } as CustomGame["lobbies"][number];
}
```

Тесты в конец `describe`. Файл уже мокает next-intl ключами (`PickupMixHeader.behavior.test.tsx:26` — `useTranslations: () => (key: string) => key`), поэтому новые строки утверждаются по ключу `mixes.lobbies.*`, а не по переводу — ровно как в плане A:

```tsx
  it("opens a second lobby on request", async () => {
    const scope = await mount(game());

    await click(byName(scope, "2"));

    expect(onLobbyCountChange).toHaveBeenCalledWith(2);
  });

  it("does not re-send the lobby count the mix already runs", async () => {
    const scope = await mount(game());

    await click(byName(scope, "1"));

    expect(onLobbyCountChange).not.toHaveBeenCalled();
  });

  it("asks before dropping a lobby, because its balance goes with it", async () => {
    const scope = await mount(
      game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }),
    );

    await click(byName(scope, "1"));
    expect(onLobbyCountChange).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "dropDescription",
    );

    await click(byName(document, "dropConfirm"));
    expect(onLobbyCountChange).toHaveBeenCalledWith(1);
  });

  it("offers the shared reshuffle only once the mix runs two lobbies", async () => {
    const one = await mount(game());
    expect(byName(one, "shuffleAll")).toBeNull();

    const two = await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }));
    await click(byName(two, "shuffleAll"));

    expect(onShuffleAll).toHaveBeenCalledTimes(1);
  });

  it("asks before a shared reshuffle while some lobby's lineup is unrecorded", async () => {
    const scope = await mount(
      game({
        lobby_count: 2,
        lobbies: [lobbyRow(0), lobbyRow(1, { lineup_recorded: false })],
      }),
    );

    await click(byName(scope, "shuffleAll"));
    expect(onShuffleAll).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "shuffleDescription",
    );

    await click(byName(document, "shuffleConfirm"));
    expect(onShuffleAll).toHaveBeenCalledTimes(1);
  });

  it("gives a viewer no lobby controls at all", async () => {
    const scope = await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }), {
      canWrite: false,
    });

    expect(byName(scope, "shuffleAll")).toBeNull();
    expect(byName(scope, "2")).toBeNull();
  });
```

`frontend/src/app/balancer/mix/PickupLobbyPanel.behavior.test.tsx` — новый проп в `mount` (строки 111-140): добавить `lobbyCount?: 1 | 2` в объект `props` и `lobbyCount={props.lobbyCount ?? 1}` в JSX. Файл уже мокает next-intl ключами (строка 46), поэтому «ждёт» утверждается как ключ `waiting`; буквы `A`/`B` — глифы компонента и приходят как есть. Тесты:

```tsx
  it("says which lobby each player is in once the mix runs two", async () => {
    const scope = await mount(
      [
        row({ workspace_member_id: 1, battle_tag: "Aria#1111", current_lobby: 0 }),
        row({ workspace_member_id: 2, battle_tag: "Bex#2222", current_lobby: 1 }),
        row({ workspace_member_id: 3, battle_tag: "Cy#3333", current_lobby: null }),
      ],
      { lobbyCount: 2 },
    );

    const badges = [...scope.querySelectorAll('[data-testid="lineup-lobby"]')].map((node) =>
      node.textContent?.trim(),
    );
    expect(badges).toEqual(["A", "B", "waiting"]);
  });

  it("says nothing about lobbies while the mix runs one", async () => {
    const scope = await mount([row({ current_lobby: 0 })]);

    expect(scope.querySelector('[data-testid="lineup-lobby"]')).toBeNull();
  });

  it("asks for twice the roles once two lobbies have to be filled", async () => {
    const rows = Array.from({ length: 3 }, (_, index) =>
      row({ workspace_member_id: index + 1, roles: ["tank"], ranks: { tank: 2400 } }),
    );
    const scope = await mount(rows, { lobbyCount: 2 });

    // One lobby needs 2 tanks, two lobbies need 4 -- three volunteers are short one.
    expect(scope.textContent).toContain("3 of 4 \u00B7 short 1");
  });
```

`frontend/src/app/balancer/mix/PickupPlayerSheet.behavior.test.tsx` — этот файл next-intl НЕ мокает, а лист теперь зовёт `useTranslations`; без провайдера он бросит. Мок добавляется рядом с остальными (после `vi.mock("@/components/RankHistory", …)`, строка 36):

```tsx
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
```

И `mount` получает третий аргумент:

```tsx
async function mount(
  value: CustomGamePlayer | null = row(),
  mixStats: MixMemberStats | null = null,
  lobbyCount: 1 | 2 = 1,
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupPlayerSheet
        row={value}
        mixStats={mixStats}
        lobbyCount={lobbyCount}
        canEdit
        saving={false}
        onOpenChange={onOpenChange}
        onSave={onSave}
        onRemove={onRemove}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  // Radix portals the sheet, so the content is a sibling of the mount point.
  return document.body;
}
```

Тесты:

```tsx
  it("offers no lobby pin while the mix runs one lobby", async () => {
    const scope = await mount(row());

    expect(scope.querySelector('[role="radiogroup"][aria-label="pinGroup"]')).toBeNull();
  });

  it("pins the player to a lobby, and writes it with the rest of the patch", async () => {
    const scope = await mount(row(), null, 2);

    await act(async () => {
      findButton(scope, "pinB").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });
    // Staged, like everything else in this sheet.
    expect(onSave).not.toHaveBeenCalled();

    await act(async () => {
      findButton(scope, "Save").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });

    expect(onSave.mock.calls[0][0]).toMatchObject({ lobby_pin: 1 });
  });

  it("sends no lobby pin at all from a one-lobby mix -- the server 422s it", async () => {
    const scope = await mount(row());

    await act(async () => {
      findButton(scope, "Save").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });

    expect(onSave.mock.calls[0][0]).not.toHaveProperty("lobby_pin");
  });

  it("shows the pin the server already stored", async () => {
    const scope = await mount(row({ lobby_pin: 0 }), null, 2);

    expect(findButton(scope, "pinA").getAttribute("aria-checked")).toBe("true");
    expect(findButton(scope, "pinB").getAttribute("aria-checked")).toBe("false");
  });
```

`frontend/src/app/balancer/mix/PickupMixList.behavior.test.tsx` — этот файл монтирует настоящий `NextIntlClientProvider` с реальным `en.json` (строки 3-8 и 58-60), поэтому здесь утверждается перевод, а не ключ:

```tsx
  it("says on the card when a mix runs two lobbies", async () => {
    const one = await mount([game(1, "balanced")]);
    expect(one.textContent).not.toContain("lobbies");

    const two = await mount([
      {
        ...game(2, "balanced"),
        lobby_count: 2,
        lobbies: [
          { lobby_index: 0, selected_variant_index: 0, next_map_id: null, balanced_at: null },
          { lobby_index: 1, selected_variant_index: 0, next_map_id: null, balanced_at: null },
        ],
      } as CustomGame,
    ]);
    expect(two.textContent).toContain("2 lobbies");
  });
```

`frontend/src/i18n/messages.parity.test.ts` — **дополнить** `describe("interpolated message keys", …)` третьим `it` (A9 уже добавил туда два: про `mixes.self.signup` и `mixes.self.blocker`; свой `describe` не заводим). В отличие от остальных тестов задачи этот не красный на шаге 2: поддерево `mixes.lobbies` уже завела B9, и её восемь ключей согласованы. Он ставится здесь потому, что именно B10 добавляет в это поддерево 19 ключей сразу в двух словарях, четыре из них — с ICU-аргументами; он краснеет ровно тогда, когда ru и en разойдутся в именах аргументов:

```ts
  it("every mixes.lobbies message takes the same ICU arguments in both locales", () => {
    // The key-set check above passes while ru says `{number}` where en says
    // `{count}`: next-intl then throws at render time in ONE locale, which no
    // key comparison can see. Every string in this subtree is rendered by the
    // mix board, where a throw blanks the whole matchup column.
    const argsOf = (value: unknown) =>
      [...String(value).matchAll(/\{\s*([a-zA-Z_][a-zA-Z0-9_]*)/g)].map((match) => match[1]).sort();
    const enLobbies: Record<string, unknown> = en.mixes.lobbies;
    const ruLobbies: Record<string, unknown> = ru.mixes.lobbies;
    const mismatched = Object.keys(enLobbies).filter(
      (key) => argsOf(enLobbies[key]).join() !== argsOf(ruLobbies[key]).join(),
    );
    expect(mismatched).toEqual([]);
  });
```

- [ ] **Step 2: Run it, expected FAIL**

```bash
cd frontend && bunx vitest run src/app/balancer/mix/PickupMixHeader.behavior.test.tsx src/app/balancer/mix/PickupLobbyPanel.behavior.test.tsx src/app/balancer/mix/PickupPlayerSheet.behavior.test.tsx src/app/balancer/mix/PickupMixList.behavior.test.tsx
bun test src/i18n/messages.parity.test.ts
```

Expected: FAIL. vitest: в шапке нет кнопок `1`/`2` и `shuffleAll` (`Expected a clickable node`); в составе нет `[data-testid="lineup-lobby"]` и спрос остаётся `3 of 2`; в листе игрока нет `pinA`/`pinB` (`No button with text "pinB"`); карточка списка не печатает «2 lobbies» (ключа `mixes.lobbies.count` ещё нет, `next-intl` рендерит сырой путь). bun: PASS — новый `it` сторожит согласованность аргументов и на пустом наборе ключей B10 зелёный; красным он станет только при расхождении ru/en, которое шаг 3 обязан не допустить.

- [ ] **Step 3: Minimal implementation**

**3.1 `frontend/src/app/balancer/mix/pickup-lineup.ts`** — строки 148-191:

```ts
/**
 * A 5v5 mix needs one tank and two of each damage/support per team, so ONE
 * lobby needs twice that before a balance can seat everyone. Exported because a
 * two-lobby mix asks for the same shape twice: the lineup's supply strip
 * multiplies by `lobby_count` rather than keeping a second table of its own.
 */
export const ROLE_DEMAND: Record<RoleCode, number> = { tank: 2, damage: 4, support: 4 };

/**
 * Seats one lobby's balance can actually fill — the sum of the demand above.
 *
 * The add-players dialog counts against this rather than against a literal 10 so
 * the "you are two over a full lobby" line and the role gauges below it can
 * never disagree about how big a lobby is.
 */
export const LOBBY_SIZE: number = Object.values(ROLE_DEMAND).reduce((sum, need) => sum + need, 0);

export type RoleSupply = {
  role: RoleCode;
  /** Active players who both selected this role and carry a rank for it. */
  supply: number;
  need: number;
  /** How many more the solver would want; 0 once the role is covered. */
  short: number;
};

/**
 * Who can actually fill each role, counted the way the solver counts, against
 * the demand of every lobby the mix is running.
 *
 * A selected role with no rank is not supply — the balance refuses to seat it —
 * so this deliberately does not match "how many chips are lit".
 */
export function summarizeRoleSupply(
  rows: CustomGamePlayer[],
  lobbyCount = 1,
): RoleSupply[] {
  return LINEUP_ROLES.map((role) => {
    const supply = rows.filter(
      (row) =>
        row.participation !== "benched" &&
        resolveRoleOrder(row).includes(role) &&
        row.ranks[role] != null,
    ).length;
    const need = ROLE_DEMAND[role] * lobbyCount;
    return { role, supply, need, short: Math.max(0, need - supply) };
  });
}
```

**3.2 `frontend/src/app/balancer/mix/PickupMixHeader.tsx`.** Каждая новая строка — через `useTranslations("mixes.lobbies")`. Имя `t` здесь уже занято переводчиком `mixes.self` (A9), поэтому наш берётся как `tl`. Существующие литералы (`Mixes`, `Mix`, `Add players`, `Manage access`, диалог удаления) и весь self-ряд A9 не трогаем.

Импорты — пост-A блок плюс `Shuffle` и `Spinner`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, Send, Shuffle, Trash2, UserCog, UserPlus } from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { CustomGame, MixSelfSignup } from "@/services/custom-game.service";

/** The three signup modes, in the order a host widens access. */
const SELF_SIGNUP_OPTIONS: readonly MixSelfSignup[] = ["closed", "pool", "benched"];
```

Пропы — пост-A тип плюс четыре наших в конец:

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
  settingLobbyCount?: boolean;
  /** Omitted -- the lobby-count switch is not rendered. */
  onLobbyCountChange?: (lobbyCount: 1 | 2) => void;
  shufflingAll?: boolean;
  /** Omitted -- no shared reshuffle, matching a page that offers none. */
  onShuffleAll?: () => void;
};
```

Сигнатура и тело — пост-A версия плюс наши параметры, состояние и второй переводчик:

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
  settingLobbyCount = false,
  onLobbyCountChange,
  shufflingAll = false,
  onShuffleAll,
}: Readonly<PickupMixHeaderProps>) {
  const t = useTranslations("mixes.self");
  const tl = useTranslations("mixes.lobbies");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [dropLobbyOpen, setDropLobbyOpen] = useState(false);
  const [shuffleOpen, setShuffleOpen] = useState(false);
  // The workspace's channel is the only target a mix has -- with none, the
  // signup card has nowhere to go. Unlike the matchup post (which simply is
  // not offered), this one stays visible and says why: a host who opens
  // signup expects the Discord button to be there, and "missing" reads as a
  // bug where "disabled, because there is no channel" reads as an answer.
  const hasChannel = game?.settings.workspace_discord_channel_id != null;
  const lobbyCount = game?.lobby_count ?? 1;
  // A lineup that was balanced and never played into the log: a shared
  // reshuffle would replace it with nothing left to record it from.
  const unrecorded = (game?.lobbies ?? []).some((lobby) => lobby.lineup_recorded === false);
```

Вставить контролы лобби в **первый** ряд карточки — между блоком `Manage access` и блоком `canDelete`; self-ряд A9 остаётся вторым рядом, ниже блока удаления:

```tsx
      {canWrite && onLobbyCountChange ? (
        <>
          <div
            role="group"
            aria-label={tl("countLabel")}
            className="flex h-9 shrink-0 items-center gap-0.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-1"
          >
            <span className={cn(EYEBROW_CLASS, "px-1")}>{tl("countLabel")}</span>
            {([1, 2] as const).map((count) => (
              <button
                key={count}
                type="button"
                aria-pressed={lobbyCount === count}
                disabled={game == null || settingLobbyCount}
                onClick={() => {
                  if (lobbyCount === count) return;
                  // Dropping B throws its balance away and clears every pin, so
                  // it is the direction that asks; opening one costs nothing.
                  if (count === 1) setDropLobbyOpen(true);
                  else onLobbyCountChange(2);
                }}
                className={cn(
                  "flex size-7 items-center justify-center rounded-md text-caption font-semibold tabular-nums transition-colors",
                  lobbyCount === count
                    ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                    : "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
                )}
              >
                {count}
              </button>
            ))}
          </div>
          <ConfirmDialog
            open={dropLobbyOpen}
            onOpenChange={setDropLobbyOpen}
            intent={{
              title: tl("dropTitle"),
              description: tl("dropDescription"),
              confirmLabel: tl("dropConfirm"),
              tone: "danger"
            }}
            pending={settingLobbyCount}
            onConfirm={() => {
              setDropLobbyOpen(false);
              onLobbyCountChange(1);
            }}
          />
        </>
      ) : null}

      {canWrite && onShuffleAll && lobbyCount === 2 ? (
        <>
          <Button
            type="button"
            variant="outline"
            className="h-9 shrink-0"
            disabled={game == null || shufflingAll}
            onClick={() => (unrecorded ? setShuffleOpen(true) : onShuffleAll())}
          >
            {shufflingAll ? (
              <Spinner className="mr-1.5 size-3.5" />
            ) : (
              <Shuffle className="mr-1.5 size-3.5" aria-hidden="true" />
            )}
            {tl("shuffleAll")}
          </Button>
          <ConfirmDialog
            open={shuffleOpen}
            onOpenChange={setShuffleOpen}
            intent={{
              title: tl("shuffleTitle"),
              description: tl("shuffleDescription"),
              confirmLabel: tl("shuffleConfirm"),
              tone: "danger"
            }}
            pending={shufflingAll}
            onConfirm={() => {
              setShuffleOpen(false);
              onShuffleAll();
            }}
          />
        </>
      ) : null}
```

**3.3 `frontend/src/app/balancer/mix/PickupLobbyPanel.tsx`.** Новая строка здесь одна — бейдж лобби; она идёт через `useTranslations("mixes.lobbies")`. Буквы `A`/`B` — глифы, а не копия: они одинаковы в обеих локалях, как номер команды, и остаются константой компонента.

Проп (в `PickupLobbyPanelProps`, после `rows`):

```tsx
  /** How many lobbies this mix runs: role demand scales with it, and rows gain a lobby badge. */
  lobbyCount?: 1 | 2;
```

Тело (строки 151-168):

```tsx
export function PickupLobbyPanel({
  canWrite,
  hasMix,
  rows,
  lobbyCount = 1,
  rotation = [],
  savingPlayerId,
  clearing,
  onPatchPlayer,
  onClear,
  onRemovePlayer,
  onOpenPlayer,
  onOpenPool,
  onApplyRotationHints,
  applyingHints,
}: Readonly<PickupLobbyPanelProps>) {
  const lineup = sortLineup(rows);
  const summary = summarizeLineup(rows);
  const supply = summarizeRoleSupply(rows, lobbyCount);
```

Прокинуть в колонку (строки 373-386): добавить `lobbyCount={lobbyCount}` в `<LineupColumn …>`, в её пропы (строки 409-420) — `lobbyCount: number;` и параметр, и дальше в `<LineupRow …>` (внутри `LineupColumn`) — `lobbyCount={lobbyCount}`.

`LineupRowProps` (строки 568-579) и `LineupRow` (строки 626-635):

```tsx
type LineupRowProps = {
  row: CustomGamePlayer;
  /** This member's rotation-fairness verdict, if the fetch has one. */
  rotationHint: RotationRecommendation | undefined;
  canWrite: boolean;
  /** Two lobbies: the row says which one seated this player, or that nobody did. */
  lobbyCount: number;
  saving: boolean;
  /** Benched rows read de-emphasised and freeze their role rail. */
  dimmed: boolean;
  onPatch: (patch: CustomGamePlayerPatch) => void;
  onOpen: () => void;
  onRemove: () => void;
};
```

И новый бейдж рядом с `RotationHintBadge`:

```tsx
/** A: 0, B: 1 -- glyphs, identical in every locale, like a team number. */
const LOBBY_LETTERS = ["A", "B"] as const;

/**
 * Which lobby seated this player, derived server-side from each lobby's
 * selected variant (`current_lobby`). `null` is "waiting" -- in the pool, in
 * nobody's teams this round -- which is exactly the state a host scans for
 * before rebalancing a lobby, so it is spelled out rather than left blank.
 */
function LineupLobbyBadge({ currentLobby }: Readonly<{ currentLobby: 0 | 1 | null | undefined }>) {
  const t = useTranslations("mixes.lobbies");
  const seated = currentLobby === 0 || currentLobby === 1;
  return (
    <span
      data-testid="lineup-lobby"
      title={
        seated
          ? t("seatedIn", { letter: LOBBY_LETTERS[currentLobby as number] })
          : t("waitingTitle")
      }
      className={cn(
        "flex h-[18px] shrink-0 items-center justify-center rounded px-1 text-label font-extrabold uppercase tracking-label",
        seated
          ? cn(teamAccent(currentLobby as number).bar, "text-[color:var(--aqt-bg)]")
          : "text-[color:var(--aqt-fg-faint)]",
      )}
    >
      {seated ? LOBBY_LETTERS[currentLobby as number] : t("waiting")}
    </span>
  );
}
```

В `LineupRow` принять `lobbyCount` и отрисовать бейдж сразу перед `<RotationHintBadge …>`:

```tsx
      {lobbyCount > 1 ? <LineupLobbyBadge currentLobby={row.current_lobby} /> : null}
      <RotationHintBadge hint={rotationHint} pinned={row.participation === "must_play"} />
```

Импорты: `teamAccent` — в блок из `@/app/balancer/mix/pickup-chrome` (строки 33-38 файла: `CAPTION_CLASS`, `CARD_TITLE_CLASS`, `EYEBROW_CLASS`, `ROLE_ICON_COLOR`); `ICON_BUTTON_CLASS` и `PANEL_CLASS` приходят из другого модуля (`@/components/balancer/balancer-page-helpers`, строки 29-33) и не трогаются; плюс `useTranslations`:

```tsx
import { useTranslations } from "next-intl";

import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  EYEBROW_CLASS,
  ROLE_ICON_COLOR,
  teamAccent,
} from "@/app/balancer/mix/pickup-chrome";
```

**3.4 `frontend/src/app/balancer/mix/PickupPlayerSheet.tsx`.** Пост-A файл: `SortableRoleCard`/`RoleCardBody` из него уже вынесены в `PickupRoleOrderEditor.tsx`, блок ролей заменён на `<PickupRoleOrderEditor …>`, `useTranslations` здесь ещё нет — имя `t` свободно. Все новые строки идут через `useTranslations("mixes.lobbies")`; `Status`, `Roles and ranks`, `Save` и всё, что рендерит редактор ролей, не трогаем. В пост-A блок импортов добавить строкой ниже `import { useState } from "react";`:

```tsx
import { useTranslations } from "next-intl";
```

Проп (в `PickupPlayerSheetProps`):

```tsx
  /** How many lobbies the mix runs. The pin only exists, and is only sent, at 2. */
  lobbyCount?: 1 | 2;
```

`type RoleDraft = { … }` получает пин — добавить поле после `isFlex`:

```tsx
  /** Which lobby the host tied this player to, or `null` for "wherever the balance puts them". */
  lobbyPin: 0 | 1 | null;
```

`buildDraft` и новая таблица опций рядом с ним:

```tsx
function buildDraft(row: CustomGamePlayer | null): RoleDraft {
  return {
    participation: row?.participation ?? "pool",
    order: row ? resolveRoleOrder(row) : [],
    rankEdits: {},
    isFlex: row?.is_flex ?? false,
    lobbyPin: row?.lobby_pin ?? null,
  };
}

/**
 * The lobby pin, in the order the tabs read: no tie, then A, then B. Each
 * option owns a key rather than an interpolated letter, so a locale can word
 * "Auto" and "Lobby A" independently of the tab label.
 */
const LOBBY_PIN_OPTIONS: readonly { value: 0 | 1 | null; labelKey: string }[] = [
  { value: null, labelKey: "pinAuto" },
  { value: 0, labelKey: "pinA" },
  { value: 1, labelKey: "pinB" },
];
```

Сигнатура `export function PickupPlayerSheet({ … })` — принять `lobbyCount = 1`; в теле, рядом с `const label = row ? playerLabel(row) : "";`, взять переводчик: `const t = useTranslations("mixes.lobbies");`.

`handleSave` — пин уходит только на двухлобби-миксе (заменить вызов `onSave(…)` внутри неё):

```tsx
    onSave(
      {
        participation: draft.participation,
        roles: draft.order,
        is_flex: draft.isFlex,
        // A one-lobby mix 422s this field, and there is no control to set it.
        ...(lobbyCount === 2 ? { lobby_pin: draft.lobbyPin } : {}),
      },
      Object.keys(draft.rankEdits).length > 0 ? { ranks, clear } : null,
    );
```

Секция контрола — вставить сразу после закрывающего `</section>` блока Status, перед секцией `Roles and ranks` (пост-A она начинается заголовком `<h3 …>Roles and ranks</h3>` и содержит `<PickupRoleOrderEditor …>`):

```tsx
            {lobbyCount === 2 ? (
              <section className="space-y-2.5 border-b border-[color:var(--aqt-border)] px-5 py-4">
                <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">
                  {t("pinHeading")}
                </h3>
                <div
                  role="radiogroup"
                  aria-label={t("pinGroup", { name: label })}
                  className="grid grid-cols-3 gap-1.5"
                >
                  {LOBBY_PIN_OPTIONS.map((option) => {
                    const selected = draft.lobbyPin === option.value;
                    const optionLabel = t(option.labelKey);
                    return (
                      <button
                        key={option.labelKey}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        aria-label={t("pinOption", { option: optionLabel, name: label })}
                        disabled={disabled}
                        onClick={() =>
                          setDraft((current) => ({ ...current, lobbyPin: option.value }))
                        }
                        className={cn(
                          "rounded-lg border px-2 py-2 text-center text-caption font-semibold transition-colors",
                          selected
                            ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-teal)]"
                            : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-3)]",
                          "disabled:cursor-default disabled:opacity-60",
                        )}
                      >
                        {optionLabel}
                      </button>
                    );
                  })}
                </div>
                <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("pinHint")}</p>
              </section>
            ) : null}
```

**3.5 `frontend/src/app/balancer/mix/PickupMixList.tsx`** — чип после блока `matches` (строка 152). Компонент уже держит `const t = useTranslations("mixes.list")` (строка 123); лобби живут в своём поддереве, поэтому рядом заводится второй хук:

```tsx
  const t = useTranslations("mixes.list");
  const tLobbies = useTranslations("mixes.lobbies");
```

```tsx
          {game.lobby_count > 1 ? (
            <span className="min-w-0 max-w-full tabular-nums">
              {tLobbies("count", { count: game.lobby_count })}
            </span>
          ) : null}
```

**3.6 i18n.** Задача B9 уже завела поддерево `mixes.lobbies` — последним ключом объекта `mixes`, сразу после `mixes.self` из A9. Здесь оно дополняется остальными ключами; порядок ключей внутри объекта значения не имеет.

`frontend/src/i18n/messages/en.json`, внутрь `mixes.lobbies`:

```json
      "count": "{count, plural, one {# lobby} other {# lobbies}}",
      "countLabel": "Lobbies",
      "shuffleAll": "Shuffle both lobbies",
      "shuffleTitle": "Shuffle both lobbies?",
      "shuffleDescription": "The result of a lineup on screen has not been recorded. Splitting the pool again replaces both lobbies, and there will be nothing left to record it from.",
      "shuffleConfirm": "Shuffle anyway",
      "dropTitle": "Go back to one lobby?",
      "dropDescription": "Lobby B's teams and every lobby pin are dropped. Matches lobby B already recorded stay in the history and in the leaderboard.",
      "dropConfirm": "Close lobby B",
      "seatedIn": "Playing in lobby {letter}",
      "waiting": "waiting",
      "waitingTitle": "Waiting for a seat",
      "pinHeading": "Lobby",
      "pinGroup": "Lobby for {name}",
      "pinOption": "{option} for {name}",
      "pinAuto": "Auto",
      "pinA": "Lobby A",
      "pinB": "Lobby B",
      "pinHint": "Takes effect at the next balance: a pinned player is never a candidate for the other lobby."
```

`frontend/src/i18n/messages/ru.json`, внутрь `mixes.lobbies`:

```json
      "count": "{count} лобби",
      "countLabel": "Лобби",
      "shuffleAll": "Перемешать оба лобби",
      "shuffleTitle": "Перемешать оба лобби?",
      "shuffleDescription": "Результат состава на экране ещё не записан. Общее деление заменит оба лобби, и записывать будет нечего.",
      "shuffleConfirm": "Всё равно перемешать",
      "dropTitle": "Вернуться к одному лобби?",
      "dropDescription": "Состав лобби B и все закрепления будут удалены. Уже записанные матчи лобби B останутся в истории и в лидерборде.",
      "dropConfirm": "Закрыть лобби B",
      "seatedIn": "Играет в лобби {letter}",
      "waiting": "ждёт",
      "waitingTitle": "Ждёт места",
      "pinHeading": "Лобби",
      "pinGroup": "Лобби для {name}",
      "pinOption": "{option} для {name}",
      "pinAuto": "Авто",
      "pinA": "Лобби A",
      "pinB": "Лобби B",
      "pinHint": "Вступает в силу при следующем делении: закреплённого за одним лобби другое не возьмёт."
```

**3.7 `frontend/src/app/balancer/mix/[gameId]/page.tsx`** — прокинуть `lobbyCount` в состав (`<PickupLobbyPanel …>`) и в лист игрока (`<PickupPlayerSheet …>`; пост-A он уже стоит там же, ниже `<PickupAccessDialog …>`):

```tsx
            <PickupLobbyPanel
              canWrite={canWrite}
              hasMix={selectedGameId != null}
              rows={rows}
              lobbyCount={game?.lobby_count ?? 1}
              rotation={rotationQuery.data ?? []}
```

```tsx
      <PickupPlayerSheet
        row={openRow}
        lobbyCount={game?.lobby_count ?? 1}
        mixStats={
```

- [ ] **Step 4: Run, expected PASS**

```bash
cd frontend && bunx vitest run src/app/balancer/mix/PickupMixHeader.behavior.test.tsx src/app/balancer/mix/PickupLobbyPanel.behavior.test.tsx src/app/balancer/mix/PickupPlayerSheet.behavior.test.tsx src/app/balancer/mix/PickupMixList.behavior.test.tsx src/app/balancer/mix/pickup-lineup.test.ts src/app/balancer/mix/PickupAddPlayersDialog.behavior.test.tsx
bun test src/i18n/messages.parity.test.ts
```

Expected: PASS обеих команд. (`PickupAddPlayersDialog` вызывает `summarizeRoleSupply(rows)` одним аргументом — значение по умолчанию `lobbyCount = 1` сохраняет его поведение; `pickup-lineup.test.ts:130-166` проверяет те же однолобби-числа. Парити-тест — `bun:test`, поэтому он запускается `bun test`, а не `vitest`.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/balancer/mix/PickupMixHeader.tsx \
        frontend/src/app/balancer/mix/PickupMixHeader.behavior.test.tsx \
        frontend/src/app/balancer/mix/PickupLobbyPanel.tsx \
        frontend/src/app/balancer/mix/PickupLobbyPanel.behavior.test.tsx \
        frontend/src/app/balancer/mix/PickupPlayerSheet.tsx \
        frontend/src/app/balancer/mix/PickupPlayerSheet.behavior.test.tsx \
        frontend/src/app/balancer/mix/PickupMixList.tsx \
        frontend/src/app/balancer/mix/PickupMixList.behavior.test.tsx \
        frontend/src/app/balancer/mix/pickup-lineup.ts \
        frontend/src/app/balancer/mix/[gameId]/page.tsx \
        frontend/src/i18n/messages/ru.json \
        frontend/src/i18n/messages/en.json \
        frontend/src/i18n/messages.parity.test.ts
git commit -m "feat(mix): host opens a second lobby, pins players to one and reads who is where"
```

---

### Task B11: Документация и финальный смоук

Чисто механическая задача плюс ручной прогон спецификационного смоука — тестовых шагов нет.

**Files:**
- Modify: `docs/business-logic-inventory.md` — секция `### Mix / custom game`, переписанная A11 (якорь — заголовок секции; строки сдвинулись). Docs здесь владеет только B11: задача B5 документацию не трогает.
- Modify: `docs/glossary.md:41-54`
- Modify: `frontend/src/app/(site)/docs/_content/ru/organizers/mixes.mdx:34-41`, `:71-78` — A эти статьи не трогает, номера актуальны
- Modify: `frontend/src/app/(site)/docs/_content/en/organizers/mixes.mdx` (те же две секции)
- Modify: `frontend/src/app/(site)/docs/_content/ru/players/mixes.mdx`, `frontend/src/app/(site)/docs/_content/en/players/mixes.mdx` — разделы «Как попасть в микс» / «Getting into a mix», переписанные A11 (якоря по тексту A, не по номерам)
- Modify: `frontend/src/app/(site)/docs/nav.ts:143-152`, `:318-327` (ключевые слова поиска)

**Interfaces:**
- Consumes: всё поведение задач B1–B10 и A1–A11; коды `split_into_lobbies` из B7 — `not_enough_for_two_lobbies`, `too_many_pinned`, `too_many_must_play`, `roles_infeasible`.
- Produces: документация; новых символов нет.

- [ ] **Step 1: Обновить `docs/business-logic-inventory.md`**

Секцию `### Mix / custom game` A11 уже переписал: в ней есть абзац Self-signup и строка Caps `8 teams, 16 co-hosts,
100 roster rows for a self-signup (roster_full)`. Заменить её на слитую версию — абзац Self-signup A11 сохранён
дословно, строка Caps дополнена потолком лобби:

```markdown
### Mix / custom game

`MixStatus`: draft / balanced / completed / cancelled. Participation: `must_play` / `pool` / `benched`.

**Lobbies.** A mix runs `lobby_count` lobbies (1 or 2, CHECK). Every per-match fact lives on
`balancer.custom_game_lobby` keyed `(custom_game_id, lobby_index)`: `balance_result_json`,
`balance_result_version`, `selected_variant_index`, `next_map_id`, `balanced_at`. The mix itself
carries none of them. Team names stay in `CustomGameTeamName` at the global index
`lobby_index * 2 + team` (A: 0-1, B: 2-3).

Lobby membership is **not stored**: a player's `current_lobby` is derived from the selected variant
of each lobby, `null` = waiting. Only the host's tie is stored — `custom_game_player.lobby_pin`
(422 while `lobby_count = 1`). `set_lobby_count(1)` drops lobby B's row and every pin; its recorded
matches stay.

`balance` takes `{scope: "lobby", lobby_index} | {scope: "all"}`. Scope `lobby` excludes players
seated in the other lobby and players pinned to it, then runs the unchanged `run_mix_balance` path.
Scope `all` needs `lobby_count = 2` (422 `single_lobby`), splits the pool with
`domain/mix_lobby_split.py` (422 `not_enough_for_two_lobbies` / `too_many_pinned` /
`too_many_must_play` — more `must_play` than both lobbies have seats — / `roles_infeasible`) and
solves each lobby. `set_variant_index` refuses a variant that would seat somebody the other lobby
already seated: 409 `seat_conflict`.

`record_outcome` stamps `casual.match.lobby_index` and writes one `casual.match_busy_player` row per
member seated in the other lobby's selected variant. `undo_match` rolls back the newest match **of
that match's lobby** (`newest_id_for_lobby`), not of the mix.

Rotation (`mix_rotation.py`): longest sit-out streak → shortest played streak → fewest games → input
order. `must_play` always seated. No history, or the whole pool fits → all `NEUTRAL` (do not invent
fairness). **A match whose `match_busy_player` set contains the member is skipped entirely** — he was
playing in the other lobby, which is neither "played" nor "sat out". An empty busy set reproduces the
one-lobby behaviour exactly, so no backfill was needed.

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

Caps: 2 lobbies, 8 teams, 16 co-hosts, 100 roster rows for a self-signup (`roster_full`). Host role required (`custom_game.*`).
```

- [ ] **Step 2: Обновить `docs/glossary.md`**

В таблицу «Rosters, registration, balancing» (строки 43-54) добавить строку сразу после **Balancer** (строка 51):

```markdown
| **Mix lobby** | One of the (at most two) matches a pickup mix runs at once — `balancer.custom_game_lobby`, keyed `(custom_game_id, lobby_index)`. Owns that match's balance document, pager position, next map and `balanced_at`; the mix itself owns none of them. Rendered as «лобби A / B» in the Russian UI. Membership is derived from the lobby's selected variant, never stored; only the host's `lobby_pin` is. |
```

- [ ] **Step 3: Обновить статьи для организаторов**

`frontend/src/app/(site)/docs/_content/ru/organizers/mixes.mdx` — вставить новую секцию между «## Деление на команды» и «## Очередь: кто сидит следующим» (после строки 40):

```mdx
## Два лобби

Переключатель **Lobbies: 1 / 2** в шапке микса открывает второе лобби. Лобби живут независимо: у каждого свои команды, своя карта, свой результат и свой темп — быстрое не ждёт медленное. Над матчапом появляются вкладки **Lobby A / Lobby B**; на экране всегда одно лобби, и всё, что под вкладкой (пейджер вариантов, ролл карты, запись результата, перетаскивание игроков, пост в Discord), относится именно к нему.

**Balance teams** под вкладкой делит только это лобби. В кандидаты не попадают те, кто уже сидит в соседнем лобби, и те, кто за соседнее лобби закреплён. Кнопка **Shuffle both lobbies** в шапке делит весь пул разом на два примерно равных по силе лобби — она есть только при двух лобби и требует, чтобы игроков хватило на оба состава.

Если у лобби есть собранный, но ещё не записанный состав, вкладка помечает его как **not recorded**, а любое действие, которое этот состав перезапишет, сначала спрашивает подтверждение.

В карточке игрока (**Advanced settings**) появляется блок **Lobby: Auto / Lobby A / Lobby B** — закрепление. Оно вступает в силу при следующем делении: закреплённого за A соседнее лобби не возьмёт. В строке состава рядом с именем видно, где игрок сейчас: **A**, **B** или **waiting** — ждёт места. Полоса ролей над составом при двух лобби просит вдвое больше людей на каждую роль.

В истории матчей каждый матч помечен буквой лобби, а отменить можно самый свежий матч **каждого** лобби — отмена в A не трогает B.

Возврат к одному лобби стирает состав лобби B и все закрепления; записанные лобби B матчи остаются в истории и в лидерборде.
```

И в секции «## Карта и результат» (строка 73) заменить первый абзац на:

```mdx
Блок **Next map** катает карту: **Any** — из всех соревновательных, либо можно ограничить режимом или выбрать карту руками. Выбранная карта общая: её видят все, кто смотрит микс. При двух лобби карта своя у каждого — она относится к тому лобби, чья вкладка открыта.
```

`frontend/src/app/(site)/docs/_content/en/organizers/mixes.mdx` — те же две правки на английском:

```mdx
## Two lobbies

The **Lobbies: 1 / 2** switch in the mix header opens a second lobby. Lobbies run independently: each has its own teams, its own map, its own result and its own pace — the quick one never waits for the slow one. **Lobby A / Lobby B** tabs appear above the matchup; exactly one lobby is on screen, and everything under the tab (the option pager, the map roll, recording a result, dragging players between teams, posting to Discord) belongs to it.

**Balance teams** under a tab balances that lobby alone. Its candidates exclude anyone already seated in the other lobby and anyone pinned to the other lobby. **Shuffle both lobbies** in the header splits the whole pool into two evenly matched lobbies at once — it only exists with two lobbies, and it needs enough players for both line-ups.

A lobby whose balanced line-up has not been played into the log yet is marked **not recorded** on its tab, and anything that would overwrite that line-up asks first.

A player's card (**Advanced settings**) gains **Lobby: Auto / Lobby A / Lobby B** — a pin. It takes effect at the next balance: a player pinned to A is never a candidate for B. Each lineup row shows where that player is right now: **A**, **B**, or **waiting** for a seat. With two lobbies the role-supply strip asks for twice as many people per role.

In the match history every match carries its lobby letter, and the undo is offered on the newest match of **each** lobby — undoing in A never touches B.

Going back to one lobby drops lobby B's teams and every pin; the matches lobby B already recorded stay in the history and in the leaderboard.
```

```mdx
The **Next map** strip rolls a map: **Any** picks from every competitive map, or you can narrow it to a mode or pick by hand. The chosen map is shared — everybody watching the mix sees it. With two lobbies each has its own map: the strip belongs to whichever lobby's tab is open.
```

- [ ] **Step 4: Обновить статьи для игроков и поиск**

`frontend/src/app/(site)/docs/_content/ru/players/mixes.mdx` — раздел «Как попасть в микс» A11 переписал целиком; наш абзац встаёт внутрь него, **между** строкой «Ваши роли и ранг берутся из данных сообщества, так что отдельную заявку заполнять не нужно.» и подзаголовком «### Свои роли»:

```mdx
В большом миксе ведущий может открыть **два лобби** — тогда над составами появятся вкладки **Lobby A / Lobby B**, и играть будут два матча одновременно. Где вы сейчас, видно в строке состава: **A**, **B** или **waiting**, если места в этом круге не хватило. Ведущий может закрепить вас за конкретным лобби — тогда при следующем делении вас возьмёт только оно.
```

и одна строка в таблицу «Если что-то не получается», под двумя строками, добавленными A11 («Кнопка «Записаться» не работает», «Свои роли не меняются»):

```mdx
| Вы в составе, но не в командах | При двух лобби мест хватает не всем сразу: в строке состава стоит **waiting**, ближайший баланс посадит вас первым |
```

`frontend/src/app/(site)/docs/_content/en/players/mixes.mdx` — то же место в разделе «Getting into a mix», между «Your roles and rank come from the community's own data, so there is no entry form to fill in.» и «### Your own roles»:

```mdx
A big mix may run **two lobbies** — **Lobby A / Lobby B** tabs appear above the teams, and two matches are played at once. Where you are right now is shown on your lineup row: **A**, **B**, or **waiting** if there was no seat this round. A host can pin you to one lobby, and from the next balance on only that lobby will take you.
```

и строка в Troubleshooting, под двумя строками A11:

```mdx
| You are in the lineup but not in a team | With two lobbies there are not always seats for everyone: your row says **waiting**, and the next balance seats you first |
```

В `frontend/src/app/(site)/docs/nav.ts` дополнить ключевые слова обеих записей `slug: "mixes"` (строки 146-149 и 321-324) словом «лобби» / «lobby»:

```ts
          keywords: {
            ru: "микс кастомка состав ротация скамейка лобби",
            en: "mix custom game lineup rotation bench lobby",
          },
```

```ts
          keywords: {
            ru: "микс хост кастомка ротация соведущий лобби два лобби",
            en: "mix host custom game rotation co-host lobby two lobbies",
          },
```

- [ ] **Step 5: Проверить ERD-гейт и прогнать смоук**

ERD и сгенерированная схема — ответственность задачи B1; здесь только проверка, что они уже перегенерированы:

```bash
cd backend && uv run python scripts/export_erd.py --check
```

Expected: PASS (`custom_game_lobby`, `custom_game.lobby_count`, `custom_game_player.lobby_pin`, `casual.match.lobby_index`, `casual.match_busy_player` уже в `docs/database_erd.md`). FAIL → задача B1 не доведена; перегенерацию делает она, руками файл не править.

Смоук по разделу Verification спеки — вручную, на поднятом стенде:

```bash
cd frontend && bun run dev
```

1. Открыть `/balancer/mix`, создать микс, добавить 24 игрока с рангами хотя бы на одну роль.
2. В шапке переключить **Lobbies** на **2** — появляются вкладки **Lobby A / Lobby B**, обе со статусом «not balanced».
3. Нажать **Shuffle both lobbies** — оба лобби получают составы; вкладки показывают «game 1»; в строках состава появляются бейджи **A**/**B**, у лишних — **waiting**.
4. На вкладке A: ролл карты, запись результата (**Team 1 win**). В истории появляется матч с чипом **A**; вкладка A переходит в «game 2»; карта лобби B не сброшена.
5. На вкладке A: **Balance teams** — состав A переcобран, состав B не изменился, а часть «waiting» зашла в A.
6. На вкладке B: запись результата. В истории два матча, чипы **A** и **B**, кнопка отмены есть у обоих (самый новый в каждом лобби).
7. Отменить матч B — матч A остаётся и сохраняет свою кнопку отмены.
8. Открыть карточку игрока, поставить **Lobby B**, сохранить; на вкладке A нажать **Balance teams** — закреплённый в A не появляется.
9. Открыть `/balancer/mix`: карточка микса показывает «2 lobbies»; лидерборд считает матчи обоих лобби.
10. Переключить **Lobbies** на **1**, подтвердить: вкладки исчезают, состав лобби A остаётся, бейджи и блок **Lobby** в карточке игрока пропадают, оба матча остаются в истории.

- [ ] **Step 6: Commit**

```bash
git add docs/business-logic-inventory.md \
        docs/glossary.md \
        frontend/src/app/\(site\)/docs/_content/ru/organizers/mixes.mdx \
        frontend/src/app/\(site\)/docs/_content/en/organizers/mixes.mdx \
        frontend/src/app/\(site\)/docs/_content/ru/players/mixes.mdx \
        frontend/src/app/\(site\)/docs/_content/en/players/mixes.mdx \
        frontend/src/app/\(site\)/docs/nav.ts
git commit -m "docs(mix): two lobbies, the pin, and the busy-player rotation rule"
```

---

## Self-review

### Покрытие: B6–B8

| Пункт спецификации | Задача |
|---|---|
| §Balance, «Одно лобби»: исключение сидящих в соседнем лобби и закреплённых за ним, `CustomGameBalanceRequest`, `Body: true` на маршруте | B6 |
| §Balance, «Оба лобби», алгоритм шагов 1–4, коды `LobbySplitError` | B7 |
| §Verification `test_mix_lobby_split.py` | B7 |
| `scope: "all"`, 422 `single_lobby`, `LobbySplitError` → 422, `_solve_lobby` на каждое лобби | B8 |
| §Verification `balance(lobby=1)` | B6 |

### Покрытие: B1, B3–B5

| Пункт спецификации | Задача |
|---|---|
| §Data model, шаги 1–6 миграции, downgrade | B1 |
| §Data model, инвариант «ровно `lobby_count` строк» | B1 (`create`), B3 (`set_lobby_count`) |
| §Derived state, «текущее лобби игрока» | B3 (`seated_member_ids` + `current_lobby`) |
| §Derived state, `lineup_recorded` | B3 (`_dump_lobby`) |
| §Per-lobby operations, таблица RPC | B4 |
| §Per-lobby operations, `set_lobby_count` и `lobby_pin` | B3 |
| §Per-lobby operations, клон копирует `lobby_count` и пины | B3 |
| §Per-lobby operations, realtime `change="lobby"` | B3 |
| §Rotation | B5 |
| §Wire shape | B1 (лобби, удаление верхнеуровневых полей), B3 (`current_lobby`, `lobby_pin`, `lineup_recorded`, `matches_count`), B4 (`lobby_index` у матча) |
| §Verification: миграционный инвариант | B1 (`test_custom_game_flow.py`, полный проход микса) |
| §Verification: `record_outcome(lobby=1)` | B4 |
| §Verification: `_rotation_histories` пропускает busy | B5 |
| §Verification: отмена самого нового матча своего лобби | B4 |
| §Verification: `set_variant_index` → 409 `seat_conflict` | B4 |
| §Verification: `set_lobby_count(1)` удаляет B и пины | B3 |
| §Phases 5 (`docs/business-logic-inventory.md` §Mix, `docs/glossary.md`, `docs/database_erd.md` — прозой) | не здесь — задача B11 (`plan-B-frontend`) владеет всей документацией; B1 только перегенерирует сам ERD-артефакт |
| §Balance (`scope`, `split_into_lobbies`), §Verification `test_mix_lobby_split.py`, `balance(lobby=1)` | не здесь — задачи B6–B8 |
| §Frontend | не здесь — задачи B2, B9–B11 |

### Покрытие: B2, B9–B11

**Покрытие спеки (разделы Wire shape / Frontend / Phases 4-5 / Verification):**

| Требование спеки | Задача |
|---|---|
| `CustomGameLobby`, `lobby_count`, `lobbies` | B2 |
| `CustomGamePlayer.current_lobby`, `lobby_pin`; `CustomGameMatch.lobby_index` | B9 (типы), B10 (UI) |
| `lobbyIndex` во всех пер-лобби вызовах; `setLobbyCount`; `balance({scope})` | B9 |
| `PickupLobbyTabs.tsx` (статус: игра N, не записано, карта; не рендерится при одном лобби) | B9 |
| `PickupTeamsPanel` получает одно лобби и `lobbyIndex`; пейджер, `NextMapStrip`, результат, DnD, захват, Discord внутри лобби; «Балансировать» с подтверждением при `lineup_recorded = false` | B9 |
| `onRenameTeam(lobbyIndex * 2 + team)` | B9 |
| `PickupMixHeader`: переключатель 1/2 и «Перемешать оба лобби» с подтверждением | B10 |
| `MatchHistoryList`: чип A/B, отмена у самого нового матча каждого лобби | B9 |
| `PickupLobbyPanel`: бейдж A/B/ждёт, спрос ролей × `lobby_count` | B10 |
| `PickupPlayerSheet`: контрол «Лобби: авто / A / B» (хост, `lobby_count = 2`) | B10 |
| `usePickupMix`: `activeLobby` в состоянии страницы, запросы прежние | B9 |
| i18n ru/en | B9 (`mixes.lobbies.*` для вкладок и панели матчапа), B10 (`mixes.lobbies.*` для шапки, бейджей, пина, чипа списка), B11 (MDX ru/en) + Deviation 1 |
| Frontend behavior-тесты из Verification (вкладки, `lobbyIndex` при записи, отмена по лобби, подтверждение) | B9 (все четыре), B10 (шапка) |
| Docs: §Mix, ERD, глоссарий | B11 (+ Deviations 2, 3) |
| Смоук на 24 игрока | B11 Step 5 |

**Согласованность имён:** `lobbyIndex` (camelCase) — во всех подписях фронта; `lobby_index` — только в телах запросов и в полях провода. `PickupRecordOutcomeInput` содержит `lobbyIndex` в B9 и читается панелью там же. `teamNamesByIndex(settings, lobbyIndex)` объявлена в B9 и используется только в B9. `summarizeRoleSupply(rows, lobbyCount)` и `ROLE_DEMAND` объявлены в B10 и там же используются (`PickupAddPlayersDialog` остаётся на одноаргументной форме). `lobbyRow` — имя фикстуры во всех тестах (имя `lobby` в `PickupTeamsPanel.behavior.test.tsx:121` уже занято документом баланса).
