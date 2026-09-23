# Уведомления о событиях турнира: Discord-доставка и новые триггеры — дизайн

**Дата:** 2026-09-22
**Статус:** реализовано (все три фазы; 2026-09-23)
**Метод:** superpowers:brainstorming (архитектурный путь)
**Issue:** [#107 Event notifications (email / Discord)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/issues/107)
**Предшественник:** `docs/plans/2026-09-07-notifications.md` (in-app inbox; этот дизайн — его «out of scope: delivery outside the app»)
**Якоря сверены с:** `master` @ `1f1c826b`

---

## 1. Проблема

Участник узнаёт об открытии регистрации, чек-ина и о назначенном матче, только если сам зашёл на сайт.
Отсюда no-show на микс-кап-турнирах. Issue просит: триггеры от жизненного цикла турнира и расписания матчей,
доставку в email и/или Discord (настройка на воркспейс), opt-in/opt-out на пользователя, доставку через
существующий RabbitMQ.

### 1.1 Что уже есть

| Что | Где | Значение для дизайна |
|---|---|---|
| In-app inbox: `notification` + `notification_read`, 9 kinds, bell | `backend/shared/services/notifications.py:190-200` (`NOTIFICATION_KINDS`), `:242` `notify()` | Единственная точка записи уведомления. Новые события = новые kinds |
| `notify()` не коммитит и не flush'ит, только `session.add` | `notifications.py:289` | `id` строки до flush недоступен — нужен для события доставки (§4.2) |
| Модульный docstring: дедуп — «suppression window в `notify()`, не partial unique index» | `notifications.py:21-25` | `dedupe_key` делаем именно так (D4) |
| Workspace-строки видны в inbox членам воркспейса | `shared/repository/notification.py:92-132` `audience_clause` | `registration.opened` ложится в существующую audience `workspace` без правок чтения |
| Баннер — только `audience='global'` | `notification.py:345` `active_global` | Workspace-строка не превратится в баннер |
| Единственный писатель статуса турнира | `tournament-service/src/services/admin/tournament.py:522-599` `transition_status` (тик 30 с и ручной RPC) | Хук для REGISTRATION / CHECK_IN |
| Регистрация открыта ⇔ окно в `tournament_phase_schedule`, вычисляется лениво | `shared/services/registration_window.py:70` `is_registration_window_open` | Смена статуса ≠ открытое окно; проверяем окно при отправке |
| `scheduled_at` пишет только админ | `tournament-service/src/services/admin/encounter.py:258-337` (`setattr`-цикл перед `:325`), `create_encounter` | Хук для `encounter.scheduled` |
| Команды слотов становятся известны в продвижении сетки | `shared/services/encounter/finalize.py:101-110` (`post_advance`), подключается в `tournament-service/src/services/encounter/finalize.py:70` | Хук для «матч назначен, а команды появились позже» |
| Discord-бот (discord.py, gateway) умеет `post_message` | `discord-service/src/rabbit/gateway.py:151-181`, событие `shared/schemas/events.py:25-63` `DiscordCommandEvent` | Канальная доставка готова; DM нет |
| Discord ID пользователей | `shared/services/subscriptions/strategies.py:122` `load_provider_user_ids` | Резолв `auth_user_id → discord id` готов |
| Выбор канала + верифицированная гильдия | `rpc.app.workspaces.discord_channels` (`app-service/src/rpc/workspaces.py:779`), `DiscordChannelSelect.tsx`, `workspace.discord_guild_id` | UI и валидация канала переиспользуются |
| Transactional outbox, drain 1 с | `shared/messaging/outbox.py:28` `enqueue_outbox_event`; drain в `tournament-service/serve.py` | Транспорт доставки |
| Email-инфраструктуры нет; `is_verified` недостоверен; у OAuth-юзеров бывают `*@<provider>.oauth` | `shared/models/identity/auth_user.py:50,55`, `identity-service/.../oauth_accounts.py:448` | Email — отдельный issue (D2) |
| Шифрования секретов at-rest нет (`cryptography` не в `uv.lock`) | — | Webhook URL хранить негде безопасно (D1) |

---

## 2. Цель и границы v1

**v1 = in-app + Discord.** Три новых события приходят в колокольчик; broadcast-события постятся ботом в канал
воркспейса; персональные уведомления (все personal kinds, включая существующие инвайты/решения/диспуты)
уходят в личку Discord с возможностью отключения.

Вне v1 (§10): email, webhook, напоминания «до конца чек-ина N минут» / «матч через 15 минут», дайджест расписания,
кнопки в DM, локаль пользователя.

---

## 3. Решения

| # | Решение | Альтернатива | Почему |
|---|---|---|---|
| D1 | Discord через **существующего бота** (`discord_commands`), не webhook | webhook URL на воркспейс (как в тексте issue) | URL вебхука — секрет, а шифрования at-rest нет; бот уже в каждой верифицированной гильдии с правами Send Messages/Embed; пикер каналов есть; DM возможны только через бота. Webhook — fallback, если появится воркспейс без бота |
| D2 | **Email вне v1**, отдельный issue | включить в v1 | нет провайдера, шаблонов, верификации почты; `is_verified` не заслуживает доверия, часть адресов фейковые. Размер L, блокировал бы релиз |
| D3 | **Триггеры и доставка ортогональны**: новые события — новые kinds в `notify()`; доставка — один конвейер за `notify()` | по конвейеру на событие | 12 kinds получают Discord без per-kind работы; новый kind = payload-схема + шаблон |
| D4 | **`dedupe_key` в `notify()`** — явный ключ продюсера + SELECT-проверка + НЕуникальный индекс | partial unique index + `ON CONFLICT` | совпадает с upgrade path из docstring `notifications.py:21-25`; явный ключ не блокирует «пригласили снова» (инвайты ключ не передают); уникальный индекс превратил бы гонку двух переходов в `IntegrityError` посреди `transition_status`. Цена: редкий дубль при гонке |
| D5 | Два вида доставки: **personal** (`audience='user'` → DM по настройкам) и **broadcast** (явный `broadcast()` → канал по настройке воркспейса) | выводить канальный пост из workspace-строки | чек-ин — персональные строки + один пост в канал; workspace-строка про чек-ин засыпала бы колокольчик всем членам воркспейса |
| D6 | Хуки **инлайн** в `transition_status` / `update_encounter`, не консьюмер `tournament.state.changed` | подписаться на уже публикуемый, но никем не читаемый `tournament.state.changed` | тот же приём, что у всех 7 существующих продюсеров `notify()`; строка уведомления в той же транзакции, что и мутация; на один движущийся узел меньше |
| D7 | Отправка в discord-service **через outbox** из консьюмера доставки (ledger-строка и команда боту в одной транзакции) | прямой `broker.publish` из консьюмера | ledger и команда коммитятся атомарно: нет «записали, что отправили, но не отправили» и дубля при редоставке. Цена: +≤1 с латентности |
| D8 | DM по умолчанию **включены** для personal kinds; opt-out по трём группам | opt-in | решение владельца продукта: no-show лечится охватом. Группы вместо 12 чекбоксов |
| D9 | `registration.opened` → канал + in-app `audience='workspace'`; **без DM** | + DM прошлым участникам | нет концепта «подписки на воркспейс»; DM всем членам — спам |
| D10 | Время в Discord — `<t:UNIX:F>` / `<t:UNIX:R>` | форматировать в `workspace.timezone` | Discord рендерит в поясе читателя; таймзоны решаются бесплатно |
| D11 | Локаль: канал — из настройки воркспейса (`ru` по умолчанию); DM — `ru` в v1 | хранить локаль пользователя сейчас | сервер локаль юзера не знает (только cookie `NEXT_LOCALE`); сохранение локали — в email-issue, где она обязательна. `ponytail:`-комментарий |

---

## 4. Архитектура

```
tournament-service
  transition_status ──┐
  update/create_encounter ──┼─► LifecycleNotifier ──► notify(kind, payload, dedupe_key)   ─┐ та же
  post_advance (сетка) ─┘                       └─► broadcast(kind, payload, workspace) ─┘ транзакция
                                                          │
                          notify(): INSERT notification (inbox, как сейчас)
                                    + для audience='user': outbox NotificationCreatedEvent(notification_id)
                          broadcast(): outbox NotificationBroadcastEvent(workspace_id, kind, payload, dedupe_key)
                                                          │ drain 1 с (существующий)
                                                          ▼
                       exchange `notifications` (topic) → queue `notification_delivery` (+DLQ)
                                                          │
app-service  NotificationDeliveryService
  personal:  row → prefs(группа kind'а) → discord id → ledger INSERT … ON CONFLICT DO NOTHING
             → render(kind, payload, "ru") → outbox DiscordCommandEvent(send_dm)
  broadcast: workspace config (канал, kind включён?) → ledger → render(kind, payload, config.locale)
             → outbox DiscordCommandEvent(post_message)
                                                          │ drain
                                                          ▼
discord-service  discord_commands: send_dm (новое) / post_message (+ allow_mentions=False)
```

### 4.1 Новые kinds

В `NOTIFICATION_KINDS` (`shared/services/notifications.py:190`):

| kind | audience | payload | dedupe_key |
|---|---|---|---|
| `registration.opened` | `workspace` | `tournament_id`, `tournament_name`, `closes_at: datetime \| None` | `tournament:{id}` |
| `check_in.opened` | `user` | `tournament_id`, `tournament_name`, `closes_at: datetime \| None` | `tournament:{id}` |
| `encounter.scheduled` | `user` | `encounter_id`, `tournament_id`, `tournament_name`, `home_team_name`, `away_team_name`, `scheduled_at: datetime` | `encounter:{id}:{scheduled_at:isoformat}` |

`closes_at` — `ends_at` строки фазы из `tournament_phase_schedule` (для регистрации `None`, если
`allow_late_registration`). `datetime` в payload уже сериализуется `model_dump(mode="json")` (`notifications.py:282`).

Новое время матча — новый ключ ⇒ новое уведомление («перенесли»). То же время, сохранённое повторно (bulk-расписание
раунда шлёт N PATCH, `RoundScheduleSection.tsx:164-167`), — тот же ключ ⇒ тишина.

### 4.2 `notify()`: `dedupe_key` и событие доставки

Новый keyword-only параметр `dedupe_key: str | None = None`:

1. Если задан — `SELECT` строки с тем же `kind`, `dedupe_key` и получателем (`recipient_auth_user_id` для `user`,
   `workspace_id` для `workspace`), **без** фильтра по `expires_at` (ретайр оператором тоже блокирует повтор).
   Нашлась — вернуть её, ничего не добавлять, не эмитить, не ставить в outbox. Тип возврата не меняется.
2. Иначе — как сейчас `session.add(row)`; затем для `audience='user'`: `await session.flush()` (нужен `row.id`) и
   `enqueue_outbox_event(session, NotificationCreatedEvent(notification_id=row.id), exchange=NOTIFICATIONS_EXCHANGE,
   routing_key="notification.created")`.

Колонка `notification.dedupe_key varchar(128) null` + индекс `ix_notification_dedupe (kind, dedupe_key) where
dedupe_key is not null` — неуникальный (D4). `ponytail:` гонка двух транзакций даёт редкий дубль; upgrade —
`ON CONFLICT` по уникальному индексу, если дубли станут наблюдаемы.

Workspace- и global-строки события доставки не ставят: announcements наружу в v1 не уходят, канальные посты
идут через `broadcast()`.

### 4.3 `broadcast()`

Рядом с `notify()` в том же модуле, тот же реестр kinds:

```python
async def broadcast(session, *, kind: str, payload: dict, workspace_id: int, dedupe_key: str) -> None
```

Валидирует payload схемой kind'а (`audience="workspace"` в контексте), ставит в outbox
`NotificationBroadcastEvent(workspace_id, kind, payload, dedupe_key)` с `routing_key="notification.broadcast"`.
Строку уведомления не пишет. `BROADCASTABLE_KINDS = {"registration.opened", "check_in.opened", "encounter.scheduled"}` —
`broadcast()` с другим kind'ом — `ValueError`.

### 4.4 Продюсеры (tournament-service)

Новый `tournament-service/src/services/notifications/lifecycle.py`: класс `LifecycleNotifier` + синглтон
`lifecycle_notifier` (форма из `backend/ARCHITECTURE.md`, «class + singleton»). Запросы получателей — методы
репозиториев в `shared/repository/`.

**`on_status_entered(session, tournament)`** — вызывается в `transition_status` сразу после
`enqueue_tournament_state_changed(...)`, до `session.commit()`:

- `REGISTRATION`: загрузить расписание; если `is_registration_window_open(status, schedule, allow_late=...)` —
  `notify(audience="workspace", workspace_id=…, kind="registration.opened", dedupe_key=…)` и `broadcast(...)`.
  Окно закрыто (ручной переход без строки расписания, `starts_at` в будущем) — пропуск с `logger.info`: не зовём
  регистрироваться туда, где кнопка не работает.
- `CHECK_IN`: получатели — регистрации турнира `status='approved'`, `deleted_at is null`, `checked_in = false`,
  с `auth_user_id` (цепочка `workspace_member → players.user.auth_user_id`, как `_notify_registration_decision`,
  `tournament/events.py:162`; shadow-игрок — пропуск). `notify` каждому + один `broadcast`.
  Если окно чек-ина ещё не активно (`starts_at` в будущем) — пропуск.
- Любой другой статус — ничего.
- **Скрытый турнир** (`Tournament.is_hidden`): `broadcast` и workspace-строка не пишутся (иначе утечка в канал
  и в колокольчик всем членам); персональные — пишутся (получатель и так зарегистрирован).

`ponytail:` окно, открывшееся лениво без записи статуса (ручной переход в REGISTRATION или CHECK_IN раньше
`starts_at`, `set_schedule` с `starts_at` в прошлом, включение `allow_late_registration`), уведомления не даёт. Upgrade path — тик напоминаний
(§10), который детектирует пересечение окна.

**`on_encounter_changed(session, encounter)`** — вызывается из:
- `update_encounter` после `setattr`-цикла, если изменился `scheduled_at` или пара команд
  (`previous_teams` уже вычисляется там же);
- `create_encounter`, если `scheduled_at` задан;
- `post_advance` в `tournament-service/src/services/encounter/finalize.py:70` — композиция с существующим
  `sync_all_pick_ban_sessions_after_team_change` (команды появились у уже назначенного матча).

Guard'ы: `scheduled_at is not None and scheduled_at > now()`, обе команды известны, турнир не
COMPLETED/ARCHIVED. Получатели — игроки обеих команд с `auth_user_id` (`tournament.player.workspace_member_id →
… → auth_user_id`). `notify` каждому с ключом `encounter:{id}:{iso}` + `broadcast` (в канал уйдёт, только если
воркспейс включил `encounter.scheduled`). Дедуп по получателю ⇒ повторный вызов из другого пути безопасен: новые
игроки (сменилась команда) получат уведомление, старые — нет.

### 4.5 Конвейер доставки (app-service)

`shared/messaging/config.py`: `NOTIFICATIONS_EXCHANGE` (topic), `NOTIFICATION_DELIVERY_QUEUE` с биндингом
`notification.*` + DLQ через `declare_dead_letter_queue`. Схемы `NotificationCreatedEvent`,
`NotificationBroadcastEvent` — в `shared/schemas/events.py` (оба с `event_id`, как требует outbox).

`app-service/src/services/notification_delivery/`:
- `service.py` — `NotificationDeliveryService` (+ синглтон), методы `deliver_personal(session, event)` и
  `deliver_broadcast(session, event)`.
- `consumer.py` — `register(broker, logger)`: `@broker.subscriber(NOTIFICATION_DELIVERY_QUEUE, exchange=…)` на своём
  `Channel(prefetch_count=4)` (как `_INVALIDATION_CHANNEL`, `app-service/serve.py:89`), обёртка
  `observe_message_processing`, диспатч по `event_type`. Регистрация в `app-service/serve.py` рядом с
  `notifications.register` (`:138`).

**Personal:**
1. Строка по `notification_id`; нет или истекла — ack, пропуск.
2. `wants_discord_dm(prefs, kind)` — чистая функция: группа kind'а → значение из `notification_preference` или
   дефолт `True`.
3. `load_provider_user_ids(..., oauth_provider="discord")` → первый (earliest-linked) id. Нет Discord — пропуск.
4. `INSERT notification_delivery … ON CONFLICT DO NOTHING RETURNING id` (`channel='discord_dm'`, `target=<discord id>`,
   `dedupe_key=f"notification:{id}"`). Ничего не вставилось — редоставка, пропуск.
5. `render_discord(kind, payload, locale="ru", site_url=…, workspace_name=…, image_url=…, settings_link=True)` —
   имя воркспейса и картинка (логотип турнира, иначе иконка воркспейса) читаются на доставке, не из снапшота.
6. `enqueue_outbox_event(DiscordCommandEvent(action="send_dm", discord_user_id=…, card=…, allow_mentions=False),
   exchange="", routing_key=DISCORD_COMMANDS_QUEUE.name)` (`"discord_commands"`, `shared/messaging/config.py:17`) → `commit`.

**Broadcast:**
1. `notification_workspace_config` воркспейса; нет конфига, канал не задан или kind не в `broadcast_kinds` — пропуск.
2. Ledger (`channel='discord_channel'`, `target=<channel id>`, `dedupe_key=f"{kind}:{event.dedupe_key}"`).
3. `render_discord(kind, payload, locale=config.locale, workspace_name=…, image_url=…)` (без кнопки настроек) → outbox
   `post_message` с `card` и `allow_mentions=False` → `commit`.

Ошибка в обработчике — существующая семантика: `observe_message_processing` пробрасывает, FastStream
отправляет в DLQ без requeue. `ponytail:` ретраев нет, DLQ разбирается вручную.

Пропуски не пишутся в ledger — только лог + метка статуса в `observe_message_processing`
(`skipped_pref_off`, `skipped_no_discord`, `skipped_no_config`, `duplicate`).

### 4.6 discord-service

`DiscordCommandEvent` (`shared/schemas/events.py:25`):
- новый action `send_dm` + поле `discord_user_id: int | None` (обязательно для `send_dm`, валидация в `model_post_init`);
- новое поле `allow_mentions: bool = True` — дефолт сохраняет поведение существующего продюсера
  (`balancer-service/src/rpc/custom.py`), уведомления передают `False`.
- новое поле `card: DiscordCard | None` — Components V2 карточка (`accent_color`, `text`, `details`,
  `thumbnail_url`, `rows: list[list[DiscordLinkButton | DiscordActionButton]]`, дискриминатор `type`);
  несовместимо с `content` / `embed` / `image_b64`, текст ≤ 4000 символов, ≤ 5 рядов по ≤ 5 кнопок — правила
  Discord проверяются в модели, а не 400-кой на отправке. `DiscordActionButton(label, action, target, style)`:
  `action` — `DiscordAction` (Literal со списком действий §4.6.1), `target` — id объекта.

`src/interactions/cards.py`:
- `card_view(card)` — `LayoutView` с одним `Container(accent_colour)`: `Section(TextDisplay(text),
  accessory=Thumbnail)` (без картинки — просто `TextDisplay`), `Separator` + `TextDisplay(details)`, по
  `ActionRow` на ряд. Action-кнопка получает `custom_id = owt:<action>:<target>`. View отправляется
  остановленным: discord.py не хранит его в памяти, клики обрабатывает один слушатель по `custom_id`.

`gateway.py`:
- `send_dm`: `user = bot.get_user(id) or await bot.fetch_user(id)`; `await user.send(content=…, embed=…, view=…,
  allowed_mentions=AllowedMentions.none())`. `discord.Forbidden` (закрыта личка / нет общего сервера) и
  `discord.NotFound` — **ack** + статус `dm_closed` / `not_found`: повторять бессмысленно, DLQ засорять незачем.
- `post_message`: `allowed_mentions=AllowedMentions.none()` при `allow_mentions=False`.
- Любой другой `discord.HTTPException` в `send_dm` / `post_message` — **reject** в DLQ со статусом
  `discord_error`: 429 и 5xx discord.py уже перепробовал сам, а 400 на payload при requeue повторяется вечно.
- Rate limit — встроенный ratelimiter discord.py.

#### 4.6.1 Действия из Discord

Кнопки, которые бот обрабатывает сам, действуя от имени нажавшего. Только для привязавших Discord через OAuth.

| Карточка | Кнопки (`action:target`) | RPC |
|---|---|---|
| `team_invite.received` (DM) | `invite.accept:{invite_id}`, `invite.decline:{invite_id}` | `rpc.tournament.regteam_accept` / `regteam_decline` |
| `check_in.opened` (DM и канал) | `check_in:{tournament_id}`, `registration.view:{tournament_id}` | `rpc.tournament.reg_pub_check_in` / `reg_pub_get_me` |
| `registration.approved` / `rejected` (DM) | `registration.view:{tournament_id}` | `rpc.tournament.reg_pub_get_me` |
| любой DM | `notifications.menu:all` (маленькая «🔕») | без RPC: бот отвечает ephemeral-сообщением с «Отключить все» (`notifications.mute:all`) и ссылкой на настройки |
| ephemeral-ответ на «🔕» | `notifications.mute:all` | `rpc.app.notification_preferences_update` (`discord_dm` = все группы `false`); ответ заменяет само ephemeral-сообщение |

Поток (`src/interactions/dispatcher.py::ActionDispatcher`, слушатель `src/cogs/interactions.py`):
1. `defer()` — отложенное обновление сообщения, в пределах 3 секунд.
2. `rpc.identity.discord_identity {discord_user_id}` → `TokenPayload` привязанного аккаунта с
   `credential_type="discord"`; `not_found` — не привязан → ответ «привяжите Discord» со ссылкой на профиль,
   **никаких вызовов платформы**; `forbidden` — аккаунт отключён. Кэша нет: отвязка действует со следующего клика.
3. RPC действия с этим `identity` — тот же вызов, что сделал бы gateway для этого человека на сайте; права
   проверяет сервис (адресный инвайт — только своему аккаунту, чек-ин — только своей заявки).
4. Ephemeral-ответ на языке клиента нажавшего (`ru` → русский, иначе английский); отказы — по машинному коду
   (`invite_expired`, `check_in_closed`, …), остальное — сообщением сервиса.
5. В DM после успеха отработавшие кнопки снимаются (`Action.settles`) и добавляется строка статуса. Пост в канале
   не редактируется никогда.

Фиксированный список (`src/interactions/actions.py::ACTIONS`), а не мост «вызвать любой RPC»: кнопка несёт
только «что» и «над чем», пользователь берётся из подписанного Discord'ом `interaction.user`. Совпадение
`ACTIONS` и `DiscordAction` держит тест. Аудит: `record_audit` пишет такие строки с `source="discord"` и
суффиксом `(via Discord)`. Slash-команды — следующий вход в `ActionDispatcher.perform`, без изменений в
списке и в правиле идентичности.

### 4.7 Настройки пользователя

Таблица `notification_preference`:

```
auth_user_id   bigint primary key references auth.user(id) on delete cascade
discord_dm     jsonb  not null default '{}'   -- {"tournament": bool, "matches": bool, "team": bool}; нет ключа = дефолт
updated_at     timestamptz not null default now()
```

Группы (`NOTIFICATION_KIND_GROUPS` рядом с реестром kinds):

| Группа | kinds | Дефолт DM |
|---|---|---|
| `tournament` | `check_in.opened`, `registration.approved`, `registration.rejected` | вкл |
| `matches` | `encounter.scheduled`, `encounter.report_disputed` | вкл |
| `team` | `team_invite.received`, `team_invite.answered`, `team.kicked`, `team.disbanded`, `team.rejected` | вкл |

`registration.opened` и `announcement.published` — не personal, в группы не входят.

RPC (app-service): `rpc.app.notification_preferences_get` / `rpc.app.notification_preferences_update`; gateway
`GET/PUT /api/notifications/preferences`, `AuthRequired`. Пользователь — только из `data["identity"]`, никогда из
тела. Ответ несёт эффективные значения (с дефолтами) и `discord_linked: bool` для подсказки «привяжи Discord».

In-app не отключается — как в v1 inbox.

### 4.8 Настройки воркспейса

Таблица `notification_workspace_config`:

```
workspace_id        bigint primary key references workspace(id) on delete cascade
discord_channel_id  bigint null
locale              varchar(2) not null default 'ru'
broadcast_kinds     jsonb not null default '["registration.opened", "check_in.opened"]'
updated_at          timestamptz not null default now()
```

Отдельная таблица по образцу `balancer.workspace_config`, а не колонки на `workspace`: читается только
админкой, в публичный `WorkspaceRead` не попадает.

RPC: `rpc.app.workspaces.notification_config_get` / `…_update`, gate — `c.require_active(user)` +
`ensure_workspace_permission(user, workspace_id, "workspace", "update")`, как у `discord_guild_verify`
(`app-service/src/rpc/workspaces.py:547-548`). Валидация update:
- у воркспейса есть верифицированный `discord_guild_id`;
- `discord_channel_id` входит в каналы этой гильдии (`DiscordClient.guild_channels`, тот же lookup, что
  `rpc.app.workspaces.discord_channels`) и текстовый;
- `broadcast_kinds ⊆ BROADCASTABLE_KINDS`, `locale ∈ SUPPORTED_LOCALES`.

### 4.9 Рендер

`app-service/src/domain/notification_render.py` — чистая функция, без сессии:

```python
def render_discord(kind, payload, *, locale, site_url, workspace_name=None, image_url=None, personal=False) -> DiscordCard
```

- Шаблоны `TEMPLATES[locale][kind] = (heading, sentence, detail lines)` для каждого deliverable kind'а (все,
  кроме `announcement.published`), `ru` и `en`. Заголовок — ярлык kind'а из админки (`workspaceAdmin.kinds`).
- Карточка: `-# <воркспейс>`, `### <заголовок>`, фраза с **жирными** названиями; под разделителем — детали
  («Слот», «Причина», «Начало», «Закрытие»). Строка деталей без значения (нет `closes_at`, пустой `reason`)
  выпадает.
- Цвет полосы — палитра инбокса (`getKindConfig`): зелёный — одобрено/принято, красный — отклонено/исключён/
  распущена, янтарный — оспорено/чек-ин, синий — приглашение/матч, teal — регистрация открыта.
- Даты — `<t:{unix}:F> (<t:{unix}:R>)` (D10).
- Весь интерполированный пользовательский текст (названия команд/турниров/воркспейса, `responder_name`,
  `reason`) обрезается (200 / 1000 символов) и экранируется, включая `[ ] < # -`: в V2-карточке markdown везде,
  а `[текст](url)` в названии команды иначе стал бы кликабельной ссылкой в официальном DM. Пинги отключены
  на уровне бота (§4.6).
- Кнопки — два ряда: сначала действия бота (§4.6.1), затем переход и выход. Переход — `site_url` + путь,
  повторяющий `frontend/src/lib/notifications/href.ts:10`: участники — `/tournaments/{id}/participants`, диспут и
  `encounter.scheduled` — `/tournaments/{id}/pregame/{encounter_id}`, `registration.opened` / `check_in.opened` —
  `/tournaments/{id}`. `ponytail:` пути продублированы с фронтом вручную. В DM (`personal=True`) рядом —
  маленькая `notifications.menu:all` («🔕»). Кнопки «отключить» на самой карточке нет: Discord разрешает
  ephemeral только в ответ на нажатие, поэтому переключатель показывается нажавшему отдельно.
- `site_url` — новая настройка `PUBLIC_SITE_URL` в `app-service/src/core/config.py` (платформенная зона; фронт
  держит её в `NEXT_PUBLIC_PLATFORM_ZONE`, `frontend/src/lib/site/host.ts:5`). Ссылки на поддомен/кастомный домен
  воркспейса — вне v1.

### 4.10 Frontend

- **Inbox:** новые kinds в `KindMessageKey` и `getKindConfig` (`NotificationList.tsx:25-35`), в `notificationHref`,
  ключи `notifications.kinds.*` в `ru.json` и `en.json` в одном коммите (`messages.parity.test.ts`).
  `messageValues` отбрасывает не-скаляры, а ISO-строки дат нужно форматировать: для `scheduled_at` / `closes_at`
  — `format.dateTime` до интерполяции.
- **Аккаунт:** вкладка `notifications` в `AccountSettingsModal` (`stores/account-settings-modal.store.ts`),
  `components/account-settings/NotificationsSection.tsx`: три переключателя + подсказка «привяжи Discord»,
  если `discord_linked=false`. Ссылка «Настроить» из поповера колокольчика — `?settings=notifications`.
- **Админка:** секция `notifications` в `components/admin/workspace-settings/sections.ts`, страница
  `app/admin/settings/notifications/page.tsx` (+ суперюзерский путь `/admin/workspaces/[id]/…`),
  `DiscordChannelSelect`, чекбоксы `broadcast_kinds`, выбор локали. Без привязанной гильдии — пустое состояние
  со ссылкой на секцию `discord`.

Workspace-строка `registration.opened` не шлёт realtime-сигнал (`notify()` эмитит только для `user`,
`notifications.py:291`), колокольчик увидит её на следующем рефетче. Принимаем.

---

## 5. Модель данных

Одна Alembic-ревизия (голову сверить при реализации):

| Изменение | Суть |
|---|---|
| `notification.dedupe_key` | `varchar(128) null` + `ix_notification_dedupe (kind, dedupe_key) where dedupe_key is not null` |
| `notification_delivery` | `id bigserial pk`, `channel varchar(32)`, `target varchar(64)`, `dedupe_key varchar(128)`, `notification_id bigint null`, `workspace_id bigint null`, `kind varchar(64)`, `created_at timestamptz default now()`; `unique (channel, target, dedupe_key)`. Без FK — журнал, как `notification`/`audit_log` |
| `notification_preference` | §4.7 |
| `notification_workspace_config` | §4.8 |

Модели — `backend/shared/models/platform/`, в default-схеме рядом с `notification` (Ruling R1 предшественника).
`ponytail:` ретеншена `notification_delivery` нет — объём = число отправленных сообщений; добавить в существующий
purge-тик, когда таблица станет заметной.

---

## 6. Безопасность

- **Канал только из своей гильдии.** Без проверки §4.8 админ воркспейса A заставил бы бота постить в гильдию B, где бот тоже есть.
- **Никаких пингов.** Названия команд — пользовательский текст; `@everyone` в имени команды пингнул бы сервер.
  `allowed_mentions=none` для всех уведомлений (§4.6).
- **Скрытые турниры** не попадают ни в канал, ни в workspace-строку (§4.4).
- **Идентичность** для prefs — только JWT (`data["identity"]`); получатели всегда вычисляются сервером из доменных
  объектов (контракт `notify()`, `notifications.py:260-262`).
- **Анти-спам Discord.** Массовые DM ботом Discord может счесть спамом. Смягчение: DM только про собственные
  регистрации/матчи получателя, opt-out на группу, никаких DM для `registration.opened` (D9).

---

## 7. Крайние случаи и ошибки

| Случай | Поведение |
|---|---|
| Shadow-игрок без аккаунта | нет строки, нет ошибки (как сейчас) |
| Нет привязанного Discord | in-app есть, DM — пропуск `skipped_no_discord` |
| Несколько Discord-аккаунтов | earliest-linked (`load_provider_user_ids` возвращает в этом порядке) |
| Закрытая личка / нет общего сервера с ботом | discord-service: ack + `dm_closed` |
| Флап статуса REGISTRATION → ANNOUNCEMENT → REGISTRATION | `dedupe_key` — одно уведомление и один пост |
| Bulk-расписание раунда (N PATCH) | каждое уведомление — только игрокам своего матча; канальный пост по умолчанию выключен |
| Время матча в прошлом (бэкфилл) | guard `scheduled_at > now()` — тишина |
| Команды назначены после времени | `post_advance`-хук (§4.4) |
| Редоставка события (at-least-once outbox) | уникальность ledger — одна отправка |
| Ретайр уведомления оператором до доставки | шаг 1 personal-флоу видит `expires_at` — пропуск |
| Большой fan-out чек-ина (сотни DM) | `discord_commands` имеет TTL 5 мин; при просадке — выделить очередь без TTL (§11 R2) |

---

## 8. Тестирование

- **shared:** `test_notify.py` — `dedupe_key` возвращает существующую строку и не пишет outbox; personal-строка ставит
  `NotificationCreatedEvent` с её id; workspace-строка — не ставит. `broadcast()` валидирует payload и отвергает
  не-broadcastable kind.
- **domain (без БД):** паритет — каждый deliverable kind имеет шаблон в `ru` и `en`; каждый personal kind входит
  ровно в одну группу; экранирование markdown; формат `<t:…>`; дефолты `wants_discord_dm`.
- **tournament-service** (`test_notification_producers.py`-стиль, проверяем строки, а не вызовы):
  `registration.opened` при открытом окне и не при закрытом; чек-ин — только approved / не отмеченным / не shadow;
  скрытый турнир — без broadcast; `encounter.scheduled` — новое время уведомляет, то же — нет, прошлое — нет,
  без одной из команд — нет; `post_advance`-путь.
- **app-service:** prefs off → нет outbox-команды; без Discord → пропуск; редоставка → одна ledger-строка;
  broadcast без конфига / kind выключен → пропуск; update конфига с чужим каналом → 4xx; prefs RPC без identity →
  `unauthorized`.
- **discord-service:** `send_dm` с `Forbidden` → ack; `allow_mentions=False` → `AllowedMentions.none()`.
- **Контракт:** `backend/tests/test_rpc_route_parity.py` (новые маршруты), openapi-записи.
- **frontend:** behavior-тесты вкладки аккаунта и админ-секции; `NotificationList` рендерит новые kinds с датами;
  `messages.parity.test.ts`.

---

## 9. Фазы выката

Каждая фаза — свой релизный тег; фаза 1 полезна сама по себе.

| Фаза | Содержание | Приёмка |
|---|---|---|
| 1. Триггеры → in-app | kinds §4.1, `dedupe_key` (§4.2 п.1), `LifecycleNotifier` без `broadcast`, фронт inbox + i18n | переход в REGISTRATION/CHECK_IN и назначение матча видны в колокольчике на dev |
| 2. Конвейер + канал | outbox-событие в `notify()`, `broadcast()`, exchange/queue/DLQ, consumer, ledger, рендер, `notification_workspace_config` + админ-секция, `allow_mentions` в discord-service | пост в тестовый канал dev-гильдии; повтор перехода не дублирует пост |
| 3. DM + настройки | `send_dm`, `notification_preference` + RPC + вкладка | DM приходит; выключенная группа — не приходит; закрытая личка не копит DLQ |

С фазой 3 существующие personal kinds (инвайты, решения по регистрации, диспуты) тоже начинают уходить в DM —
стоит анонсировать пользователям (через существующие announcements).

---

## 10. Вне скоупа

- **Email** — отдельный issue: провайдер, подтверждение почты, фильтр `*.oauth`, List-Unsubscribe (RFC 8058),
  шаблоны, сохранение локали пользователя.
- **Напоминания** — следующий спек: тик рядом с `run_due_transitions`, «чек-ин закрывается через 30 мин, а ты не
  отметился», «матч через 15 минут». Тот же `dedupe_key`, тот же конвейер. Заодно закрывает ленивое открытие окон (§4.4).
- **Webhook** как fallback для воркспейсов без бота.
- **Дайджест расписания раунда** в канал вместо N постов; коалесинг переносов (доставка с задержкой, последнее значение).
- **Кнопка «Чек-ин» в DM** (discord.py views + interaction handler).
- Переопределение канала на турнир; ссылки на поддомен/кастомный домен воркспейса; delivery receipts и ретраи вне DLQ.

---

## 11. Риски (skeptic pass)

| # | Риск | Severity | Резолюция |
|---|---|---|---|
| R1 | `notify()` начинает делать `flush` — у 26 вызовов ошибки констрейнтов всплывут раньше, spy-сессия в `test_notify.py` может не уметь `flush` | Significant | flush только для `audience='user'` и только для новой строки; существующие тесты продюсеров — часть приёмки фазы 2 |
| R2 | Fan-out чек-ина упирается в TTL 5 мин очереди `discord_commands` | Significant | метрика задержки; если упрёмся — отдельная очередь `discord_notifications` без TTL |
| R3 | Discord помечает бота как спамера | Significant | §6: DM только про собственные события получателя + opt-out |
| R4 | Outbox дренит только tournament-service — его падение стопорит доставку | Minor | так же стоит весь outbox сегодня; отдельной меры не нужно |
| R5 | Пути ссылок продублированы между Python-рендером и `lib/notifications/href.ts` | Minor | `ponytail:` в рендере; upgrade — общий манифест маршрутов |
| R6 | Outbox-публикация в default exchange (`exchange=""`) — не проверена на текущем `publish_pending_outbox_events` | Minor | проверено: FastStream `declare_exchange` отдаёт `channel.default_exchange` для пустого имени — fallback не нужен |
| R7 | Гонка двух переходов даёт дубль уведомления (D4) | Minor | принято; upgrade — уникальный индекс + `ON CONFLICT` |

---

## 12. Побочные находки (не в скоупе)

- `tournament.state.changed` публикуется при каждой смене статуса, но **никем не потребляется**:
  `TOURNAMENT_STATE_CHANGED_QUEUE` и `TOURNAMENT_REGISTRATION_REJECTED_QUEUE` объявлены в
  `shared/messaging/config.py` и не подписаны — сообщения дропаются как unroutable.
- Outbox повторяет неудачную публикацию бесконечно: нет ни cap'а попыток, ни dead-статуса (`outbox.py:113`).
- `post_message` не отключает пинги — для существующих mix-постов балансера это та же дыра с `@everyone` в названиях.
- `backend/ARCHITECTURE.md` ссылается на удалённый `app-service/src/services/tournament_events.py`.
