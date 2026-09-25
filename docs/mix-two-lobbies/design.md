# Два лобби в одном миксе
**Status:** design approved

Companion implementation plan: [`plan.md`](./plan.md). Реализуется после [самозаписи](../mix-self-signup-discord/design.md).

**Goal:** Один микс (кастомка) ведёт два матча одновременно: общий пул, хост, кохосты, запись и лидерборд, но у
каждого лобби свои команды, карта, результат и темп. Лобби живут независимо — быстрое не ждёт медленное, — а когда
нужно, хост перемешивает оба разом, деля пул поровну по силе. Хост может закрепить игрока за лобби.
Сегодня «микс = одно лобби» зашито в модель, солвер, запись результата, ротацию, Discord и UI.

**Architecture:** Новая дочерняя таблица `balancer.custom_game_lobby` забирает у `custom_game` всё, что относится к
одному матчу (`balance_result_json`, `balance_result_version`, `selected_variant_index`, `next_map_id`); форма документа
баланса не меняется — у каждого лобби свой документ прежнего вида (2 команды на вариант). Членство игрока в лобби не
хранится: оно выводится из выбранного варианта лобби. Хранятся только пин (`custom_game_player.lobby_pin`) и, для
честной ротации, кто в момент записи матча играл в соседнем лобби (`casual.match_busy_player`). Общий перебаланс — чистый
делитель пула на два равных по силе лобби + прежний точный `mix_balancer` внутри каждого.

**Tech Stack:** Alembic (`balancer`, `casual`), balancer-service (service/domain/rpc), Go gateway routes, Next.js
(`/balancer/mix/[gameId]`), discord-service не меняется (пост — прежний `post_message`).

---

## Decision log

| Решение | Отклонено | Почему |
|---|---|---|
| Лобби независимы; «Перемешать оба» — отдельное действие | Раунды с общим перебалансом; только независимые | Выбор пользователя: «быстрое не ждём медленное… если нужно — сообща, для перемешивания» |
| Общее деление — поровну по силе | Сильное/слабое; вручную | Выбор пользователя; очки за победу в лидерборде сопоставимы между лобби |
| Пин игрока к лобби (`авто` / `A` / `B`) | Только обмен местами | Выбор пользователя: друзья вместе, стример в A |
| Дочерняя таблица `custom_game_lobby`, перенос четырёх колонок | Колонки `*_b` на `custom_game`; массив в JSON | Один путь кода для 1 и 2 лобби; лобби 0 — обычная строка, а не особый случай |
| Документ баланса лобби — прежний v1 (2 команды) | Один документ на 4 команды | `mix_balancer` умеет ровно 2 команды (`mix_balancer.py:173`); парсеры, `swap_seats`, `record_outcome`, фронтовый `parseVariants` работают без изменений |
| Членство в лобби выводится из выбранного варианта | Колонка «текущее лобби» | Нет второго источника правды, который надо синхронизировать с балансом |
| `casual.match_busy_player` для ротации | Раунды; явные строки «пропустил» | Без неё игрок из B во время матчей A выглядит «сидящим» и получает приоритет перед реально ждущими. Пустой набор = сегодняшнее поведение, бэкфилл не нужен |
| Потолок 2 лобби (CHECK `0..1`) | N лобби | Просили 2; поднять — сменить CHECK и UI |
| Вкладки «Лобби A / B» | Два матчапа рядом | Колонка матчапа ограничена 1180px рядом с колонкой лайнапа 568px (`page.tsx:172-179`) — два не влезут |

## Что уже есть

- `CustomGame` (`backend/shared/models/custom_game.py:20`): одна `next_map_id`, один `selected_variant_index`, один
  `balance_result_json`.
- `CustomGameService.balance` (`backend/balancer-service/src/services/custom_game.py:693`) — один вызов
  `run_mix_balance` на весь не-benched пул; лишних отсекает trim по `rotation_priority`.
- `record_outcome` (`:1185`) требует ровно 2 команды (`:1235-1239`), пишет `casual.match` + HOME/AWAY + места,
  очищает `next_map_id`. `undo_last_match` (`:1324`) — только самый новый матч микса.
- `_rotation_histories` (`:1461`) строит `played` по всем матчам микса после вступления игрока в пул.
- `swap_seats` (`:1085`), `set_variant_index` (`:867`), `set_next_map` (`:836`), `discord_lineup` (`:922`) — всё
  относительно одного документа/одной карты.
- `CustomGameTeamName.team_index` уже `0..7`.
- `domain/matching.py:maximum_bipartite_matching` — двудольное сопоставление, пригодно для проверки «роли лобби
  заполнимы».
- Статистика и лидерборд (`mix_stats`) считают каждую строку `casual.match` — лобби им не мешает.

---

## Data model

Миграция `mixlobby01`:

```python
class CustomGameLobby(db.Base):
    __tablename__ = "custom_game_lobby"
    # PK (custom_game_id, lobby_index); CHECK lobby_index BETWEEN 0 AND 1
    custom_game_id: Mapped[int]            # FK balancer.custom_game.id ON DELETE CASCADE
    lobby_index: Mapped[int]               # 0 = A, 1 = B
    balance_result_json: Mapped[dict | None]
    balance_result_version: Mapped[int]    # default 1
    selected_variant_index: Mapped[int]    # default 0
    next_map_id: Mapped[int | None]        # FK overwatch.map.id ON DELETE SET NULL
    balanced_at: Mapped[datetime | None]   # когда лобби последний раз балансили
```

1. Создать `balancer.custom_game_lobby`; для каждого `custom_game` вставить строку `lobby_index=0` с его четырьмя
   колонками (`balanced_at = updated_at`, если баланс есть).
2. Удалить эти четыре колонки из `custom_game`.
3. `custom_game.lobby_count smallint NOT NULL DEFAULT 1 CHECK (lobby_count BETWEEN 1 AND 2)`.
4. `custom_game_player.lobby_pin smallint NULL CHECK (lobby_pin BETWEEN 0 AND 1)`.
5. `casual.match.lobby_index smallint NOT NULL DEFAULT 0 CHECK (lobby_index BETWEEN 0 AND 1)`.
6. `casual.match_busy_player(match_id FK casual.match CASCADE, workspace_member_id FK workspace_member CASCADE,
   PK (match_id, workspace_member_id))` — кто сидел в выбранном варианте соседнего лобби в момент записи матча.

Downgrade — обратный перенос из строки `lobby_index=0`.

Инвариант: у микса ровно `lobby_count` строк лобби. `set_lobby_count` создаёт/удаляет строку `1`.

Названия команд: глобальный индекс = `lobby_index * 2 + team` (A: 0-1, B: 2-3) в существующей `CustomGameTeamName`.

## Derived state

- **Текущее лобби игрока** — `L`, если он сидит в выбранном варианте лобби `L`; иначе `null` («ждёт»). Сервер
  отдаёт `current_lobby` в каждой строке ростера (`_dump_row`), чтобы доска, панель игрока и Discord не считали сами.
- **Лайнап лобби не записан** — `balanced_at IS NOT NULL` и нет матча этого лобби с `created_at >= balanced_at`.
  Отдаётся как `lineup_recorded: bool`; UI спрашивает подтверждение перед действием, которое этот лайнап перезапишет.

## Balance

`rpc.balancer.custom.balance` получает тело `{scope: "lobby", lobby_index: 0|1} | {scope: "all"}`
(по умолчанию `{scope: "lobby", lobby_index: 0}` — для однолобби-микса это сегодняшнее поведение).

### Одно лобби (`scope: "lobby"`)

Кандидаты = не-benched строки ростера, **кроме**:
- сидящих в выбранном варианте другого лобби (они играют);
- закреплённых за другим лобби.

Дальше — сегодняшний путь без изменений: ранги, `rotation_priority` из `_rotation_histories`, `run_mix_balance`,
trim лишних. Результат пишется в документ этого лобби, `selected_variant_index = 0`, `balanced_at = now()`.
Второе лобби не трогается.

### Оба лобби (`scope: "all"`, только при `lobby_count = 2`)

1. Кандидаты = все не-benched строки.
2. `split_into_lobbies(...)` — новый чистый модуль `backend/balancer-service/src/domain/mix_lobby_split.py` (ниже).
3. Для каждого лобби — `run_mix_balance` ровно на его игроках (trim внутри движка становится no-op).
4. Оба документа заменяются, `selected_variant_index = 0`, `balanced_at = now()` у обоих.

```python
@dataclass(frozen=True, slots=True)
class SplitCandidate:
    member_id: int
    ratings: Mapping[str, int]         # только роли с найденным рангом; пусто = не играбелен
    strength: int                      # рейтинг роли с высшим приоритетом (all_ranked -> максимум)
    pin: int | None                    # 0 | 1 | None
    must_play: bool
    rotation_priority: float           # меньше = больше должен место

@dataclass(frozen=True, slots=True)
class LobbySplit:
    lobbies: tuple[tuple[int, ...], tuple[int, ...]]
    waiting: tuple[int, ...]

def split_into_lobbies(candidates: Sequence[SplitCandidate], *, mask: Mapping[str, int]) -> LobbySplit: ...
```

Алгоритм (детерминированный, без RNG):
1. **Кто играет.** `seats = 2 * sum(mask)` на лобби. Порядок: `must_play` → `rotation_priority` ↑ → входной порядок;
   берём первые `2 * seats`, остальные — `waiting`. Играбельных меньше `2 * seats` → 422
   `not_enough_for_two_lobbies`; `must_play` больше `2 * seats` → 422 `too_many_must_play`.
2. **Пины.** Закреплённые ставятся в своё лобби; больше `seats` в одном лобби → 422 `too_many_pinned`.
3. **Жадное деление.** Остальные по `strength` ↓ идут в лобби с меньшей суммой `strength` среди лобби со
   свободными местами — если после хода роли **обоих** лобби ещё заполнимы (двудольное сопоставление
   `maximum_bipartite_matching`: игрок → слот роли, ребро = у игрока есть ранг на эту роль; уже поставленные
   привязаны к слотам своего лобби). Не заполнимо ни одним ходом → 422 `roles_infeasible`.
4. **Улучшение.** Пока есть пара незакреплённых `a∈A`, `b∈B`, обмен которых уменьшает `|ΣA − ΣB|` и сохраняет
   заполнимость — меняем лучшую такую пару. Не больше `seats²` итераций.

`strength` — приближение: точный подбор ролей делает `mix_balancer` на шаге 3. Фактический разрыв между лобби UI
показывает из `average_mmr` двух выбранных вариантов.

**Потолок:** жадное деление + локальные обмены — не глобальный оптимум. Если разрыв между лобби на практике окажется
заметным — точный перебор делений 20 игроков на две половины.

## Per-lobby operations

Всё, что сегодня относится к «матчу», получает `lobby_index` (по умолчанию `0`) и работает с документом этого лобби:

| RPC | Изменение |
|---|---|
| `custom.set_next_map` | `{lobby_index, map_id}` → `custom_game_lobby.next_map_id` |
| `custom.set_variant_index` | `{lobby_index, variant_index}`; вариант, сажающий кого-то из выбранного варианта другого лобби → 409 `seat_conflict` |
| `custom.swap_seats` | `{lobby_index, …}` — обмен внутри лобби, как сейчас |
| `custom.record_outcome` | `{lobby_index, …}`: лайнап из выбранного варианта лобби, карта лобби; `casual.match.lobby_index`; `match_busy_player` = места выбранного варианта другого лобби; очищается `next_map_id` только этого лобби |
| `custom.undo_match` | отменяется только самый новый матч **своего** лобби (`newest_id_for_game` → `newest_id_for_lobby`) |
| `custom.post_discord` | `{lobby_index, variant_index, image_b64}`; при `lobby_count = 2` заголовок эмбеда «Лобби A · игра N», N — по матчам лобби |
| `custom.rotation` | `?lobby_index=`: ранжирует кандидатов этого лобби (как в «Одно лобби»), `usable_count` = места одного лобби |

Новое:

| RPC | Маршрут (`…/custom-games/{game_id}`) | Что |
|---|---|---|
| `custom.set_lobby_count` | `PUT …/lobbies` `{lobby_count: 1\|2}` | `_writable`; 1→2 создаёт пустое лобби B; 2→1 удаляет строку B (баланс B теряется, матчи B остаются в истории) и обнуляет все `lobby_pin` |
| — | `PUT …/players/{member_id}` | `CustomGamePlayerPatch.lobby_pin: 0\|1\|null`; при `lobby_count = 1` → 422; в самостоятельной правке игрока ([самозапись](../mix-self-signup-discord/design.md)) поля нет |

Клон (`clone_from_game_id`) копирует `lobby_count` и `lobby_pin`; баланс, карты и историю — нет, как сейчас.

Realtime — прежний `emit_pickup_mix_updated`; `change="lobby"` для `set_lobby_count`.

## Rotation

`_rotation_histories` получает одну новую фильтрацию: матч, в `match_busy_player` которого есть игрок, в его
`played` не входит вовсе — он в это время играл в другом лобби, это не «сыграл» и не «пропустил».

```python
played=tuple(
    member_id in participants_of[match.id]
    for match in matches
    if (row.created_at is None or match.created_at >= row.created_at)
    and member_id not in busy_of[match.id]
)
```

Для однолобби-миксов `busy_of[...]` пуст — результат совпадает с сегодняшним. `mix_rotation.py` не меняется.

## Wire shape

```json
{
  "id": 42, "lobby_count": 2,
  "lobbies": [
    {"lobby_index": 0, "balance_result": {"variants": ["…как сейчас…"]}, "selected_variant_index": 0,
     "next_map_id": 17, "balanced_at": "…", "lineup_recorded": true, "matches_count": 5},
    {"lobby_index": 1, "balance_result": null, "selected_variant_index": 0,
     "next_map_id": null, "balanced_at": null, "lineup_recorded": true, "matches_count": 3}
  ],
  "players": [{"workspace_member_id": 7, "current_lobby": 0, "lobby_pin": null, "…": "…"}],
  "settings": {"team_names": {"0": "…", "2": "…"}}
}
```

Поля `balance_result`, `selected_variant_index`, `next_map_id` верхнего уровня удаляются (clean cutover). Как и
сегодня, `balance_result` и `players` есть только в детальном ответе (`custom.get`); `lineup_recorded`, `matches_count`
лобби и `current_lobby` — тоже только там. Матч в истории получает `lobby_index`.

## Frontend

`frontend/src/app/balancer/mix/`:

- `custom-game.service.ts`: тип `CustomGameLobby`; `CustomGame.lobby_count`, `lobbies`; `CustomGamePlayer.current_lobby`,
  `lobby_pin`; `CustomGameMatch.lobby_index`; `lobbyIndex` во всех per-lobby вызовах; `setLobbyCount`;
  `balance({scope})`.
- `PickupMixHeader.tsx`: переключатель «Лобби: 1 / 2»; при 2 — кнопка «Перемешать оба лобби» (`scope: "all"`),
  подтверждение, если у какого-то лобби `lineup_recorded = false`.
- `PickupLobbyTabs.tsx` (новый): вкладки «Лобби A / B» со статусом («игра N», «не записано», карта). При одном лобби
  не рендерится.
- `PickupTeamsPanel.tsx`: получает одно лобби и `lobbyIndex`; пейджер, `NextMapStrip`, `PickupResultControls`,
  DnD-обмен, захват скриншота, пост в Discord — внутри лобби; «Балансировать» = `scope: "lobby"` с подтверждением
  при `lineup_recorded = false`. Палитра `TEAM_ACCENTS` (2 цвета) остаётся: на экране всегда одно лобби.
- Названия команд: `onRenameTeam(lobbyIndex * 2 + team)`.
- `MatchHistoryList`: чип «A/B» у матча при `lobby_count = 2` или если в истории есть `lobby_index = 1`; отмена — у
  самого нового матча каждого лобби.
- `PickupLobbyPanel.tsx`: бейдж «A / B / ждёт» по `current_lobby`; спрос в полосе ролей = `ROLE_DEMAND × lobby_count`.
- `PickupPlayerSheet.tsx`: контрол «Лобби: авто / A / B» (хост, `lobby_count = 2`).
- `usePickupMix.ts`: `activeLobby` в состоянии страницы; запросы прежние (лобби внутри одного `CustomGame`).
- i18n ru/en.

Связь с планом самозаписи: `self_get` отдаёт `seat.current_lobby`; бот и панель игрока пишут «Вы в лобби A» / «Ждёте
места».

---

## Edge cases

- **Лобби B играет, хост перебалансирует A** — B не трогается; кандидаты A не включают сидящих в B.
- **«Перемешать оба», пока B не записано** — подтверждение «результат текущего состава B не записан»; после
  подтверждения лайнап B заменяется.
- **Пин к A у игрока, который сейчас в B** — вступает в силу при следующем балансе: B его не возьмёт (закреплён за A),
  он станет «ждёт», A возьмёт при своём балансе.
- **Пейджер A выбрал вариант с игроком, которого B уже посадил** — 409 `seat_conflict`; UI показывает, кто конфликтует.
- **`must_play` при балансе одного лобби** — обязателен для этого лобби, если не сидит в другом и не закреплён за ним;
  `must_play` больше мест → прежняя ошибка; при `scope: "all"` — 422 `too_many_must_play`.
- **2→1** — строка B удаляется, пины сбрасываются, матчи B остаются в истории и статистике.
- **Двойная запись одного лобби / одновременная запись A и B двумя кохостами** — разные лобби пишут разные строки; повтор
  в одном лобби ведёт себя как сейчас.
- **Мало игроков для двух лобби** — `scope: "all"` → 422 `not_enough_for_two_lobbies`; баланс одного лобби работает как
  сейчас.

## Phases

1. **Модель.** Миграция `mixlobby01`, `CustomGameLobby` + репозиторий, перенос чтений/записей четырёх колонок во все
   методы `CustomGameService` и `_dump_game` (лобби 0), `lobby_index` у `casual.match` — поведение однолобби-миксов не
   меняется. Обновить существующие тесты под новое место колонок.
2. **Лобби.** `lobby_count`, `lobby_pin`, per-lobby RPC, `seat_conflict`, `match_busy_player`, фильтр в
   `_rotation_histories`, `newest_id_for_lobby`, заголовок эмбеда, gateway routes/openapi.
3. **Общий перебаланс.** `mix_lobby_split.py`, `scope: "all"`.
4. **Frontend.** Вкладки, панель лобби, шапка, лист игрока, история, i18n.
5. **Docs.** §Mix в `docs/business-logic-inventory.md` (лобби, правило ротации), `docs/database_erd.md`, термин
   «Лобби (микса)» в `docs/glossary.md`.

Миграция `mixlobby01` идёт после `mixself01`: самозапись реализуется первой, `down_revision = "mixself01"`.

## Verification

- `tests/test_mix_lobby_split.py`: пины соблюдены; `too_many_pinned`; `too_many_must_play`; `not_enough_for_two_lobbies`; `roles_infeasible`
  (5 игроков с рангом только на танка при 4 танковых слотах); `must_play` всегда играет; `waiting` — самые «недолжные» по
  `rotation_priority`; разрыв после улучшения не больше, чем после жадного шага; детерминизм.
- `test_custom_game.py`:
  - миграционный инвариант: однолобби-микс после переноса балансирует, записывает и отменяет как раньше;
  - `balance(lobby=1)` не берёт сидящих в A и закреплённых за A;
  - `record_outcome(lobby=1)` очищает карту только B, пишет `lobby_index=1` и `busy` = места A;
  - `_rotation_histories` пропускает матчи, где игрок busy;
  - `undo` отменяет самый новый матч своего лобби, не чужого;
  - `set_variant_index` → 409 `seat_conflict`;
  - `set_lobby_count(1)` удаляет B и пины.
- Frontend behavior-тесты: вкладки переключают лобби; запись результата уходит с `lobbyIndex`; отмена доступна у
  самого нового матча каждого лобби; подтверждение при `lineup_recorded = false`.
- Смоук: микс на 24 игрока → «Перемешать оба» → запись A → перебаланс A (сидящие в B не тронуты, ждавшие
  зашли) → запись B → доска и лидерборд.

## Out of scope

Больше двух лобби; деление «сильное/слабое»; обмен местами между лобби (пин + перебаланс покрывают); свой in-game
хост/инвайтер у лобби; отдельные Discord-каналы/голосовые на лобби; фильтр лидерборда по лобби.
