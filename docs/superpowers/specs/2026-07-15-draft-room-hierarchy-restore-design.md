# Draft live-room: иерархия + восстановление регрессий редизайна

**Дата:** 2026-07-15
**Область:** `frontend/src/app/draft/[id]` + `frontend/src/app/(site)/tournaments/[id]/draft/_components/*`
**Тип:** UI/UX (только фронт). Бэкенд/API/типы не меняются — все нужные поля уже есть.

## Проблема

После редизайна (`e6e5f96b` «Redesign draft flow», `07ebde35` «Move public board into standalone room») публичная live-комната драфта стала плоской: каждая панель — один рецепт (`HeroCoord` + `text-lg font-semibold` + нижний бордюр), монохром, teal только точечно в иконках. Жалоба пользователя: **«информация в блоках без выделения, непонятно на что смотреть»**.

Редизайн заменил старую доску (`DraftBoard.tsx` −2394 строки, `DraftBoard.module.css` −1799 строк) на набор минималистичных компонентов и по дороге потерял почти все сигналы внимания и часть данных. Подтверждённые регрессии:

1. **Ранги мимо DivisionGrid.** Старая доска везде рисовала `PlayerDivisionIcon` через `resolveDivisionFromRank(tournamentGrid, …)`. Новые `PlayerPool` (`rank_value ?? "—"`) и `PlayerInspector` (`role_ranks[role]`) печатают сырое SR-число. `DraftOrder` вообще без ранга. Уцелел только `TeamRosters` — но и он резолвит дивизион от `primary_role`/`rank_value` вместо **сыгранной** роли (`pick.target_role`), поэтому off-role пики показывают неверный ранг.
2. **Sticky-панель сломалась.** Старый bottom-bar: `position: sticky; bottom: 14px` + `padding-bottom: 110px` (работал в site-layout). Новый `PickCommandBar` — `sticky bottom-2`, но у `.room` (`DraftRoom.module.css`) стоит `overflow-x: hidden`, что по спеке вычисляет `overflow-y: auto` → `.room` становится scroll-контейнером для sticky; т.к. `.room` растёт под контент и сам не скроллится, у `sticky bottom` нет диапазона — панель просто оседает в конце контента.
3. **Потеря плотности и акцентов** (флаттенинг): роль-цветные карточки с тенями/hover-lift/selected-glow, кольцо таймера, on-clock подсветка команды, pips прогресса, hero-аватары, per-role SR, sub_role/is_flex, ссылки на профиль — всё убрано; ведущий цвет состояния (teal→amber→rose) не задействован.

## Цели

- Вернуть **чёткую иерархию внимания**: доминантный фокус состояния → рабочая зона → справочные панели.
- Починить обе конкретные регрессии (ранги через DivisionGrid турнира; sticky command bar).
- Восстановить утраченную плотность и OW-контекст **без** ломки редизайна и с уважением к дизайн-системе.

## Не-цели / вне области

- **Админ-контролы драфта** — НЕ восстанавливаем в публичной комнате. Они переехали в `admin/.../draft/AdminControlRoom.tsx` + `LifecycleControls.tsx` намеренно; публичная комната = только капитан/зритель.
- **Мульти-цветная палитра команд** (teal/amber/rose/violet на команду) — конфликтует с правилом дизайн-книги «one teal leads». Используем роль-тинты + единый акцент состояния.
- Бэкенд, схемы, миграции, RPC — без изменений.
- Возможность админа пикать за on-clock капитана **из публичной комнаты** — вне области (есть автопик + admin control room).

## Принципы

- **Editorial-Tactical сохраняем.** Токены `--aqt-*`, `HeroFrame`/`HeroCoord`/`HeroStat`, шрифты Onest/mono, hairline-разделители. Меняем вес/цвет/элевацию, не язык.
- **One teal leads, но акцент ведёт состояние.** Единственный доминантный акцент в каждый момент = состояние сессии: `live`→teal, `paused`→amber, `blocked`/`urgent`→rose (`--aqt-live`/`--aqt-rose`), `done`/`safe`→`--aqt-support`. Роль-тинты (`--aqt-tank/damage/support`) — только вспомогательные штрихи, не заливка.
- **Grid рангов = grid турнира.** Источник — `tournament.division_grid_version` (как в старой доске); fallback `DEFAULT_DIVISION_GRID`. `TeamRosters` тоже переводим на него (сейчас `useDivisionGrid()`), чтобы во всей комнате один источник.
- **Hero-аватары через стандарт.** `AvatarStack` (`components/ui/avatar.tsx`) + `getHeroIconUrl` (`utils/player.ts`). `HeroStatsPopover` не применяем — в пуле нет per-hero статов.
- **shadcn/примитивы** предпочитаем самоделкам ([[feedback_prefer_shadcn_components]]).

## Ярусная модель внимания

- **Ярус 1 — Фокус:** состояние драфта (чей ход + таймер + что делать). Один на экран, громче всех.
- **Ярус 2 — Рабочая зона:** пул игроков (капитан) / ростеры (зритель) + досье выбранного игрока.
- **Ярус 3 — Справка (отступает):** порядок пиков, лента событий, шортлист, presence, чужие ростеры. Тихие мелкие приглушённые шапки, ниже контраст.

## Дизайн по областям

### A. Room shell — fix sticky
`DraftRoom.module.css`: `.room { overflow-x: hidden }` → `overflow-x: clip`. `clip` обрезает glow/grid по горизонтали, но **не** создаёт scroll-контейнер → `sticky bottom` в `PickCommandBar` снова работает. Проверить, что `.stage` (`animation: stage-in … both`, transform в кейфрейме) не остаётся с transform после анимации (fill `both` держит финальный кадр без transform — ок; при желании убрать transform из финального состояния).
**Проверка:** прокрутить длинный пул на десктопе и мобиле — command bar прилипает к низу вьюпорта.

### B. Фокальная карточка состояния + кольцо таймера (главный рычаг)
- **`CurrentPick`** становится единственной фокальной карточкой (Ярус 1): приподнятая `--aqt-card` поверхность, ведущий цвет = состояние. Состояния: `LIVE` (teal), `YOUR TURN` (усиленный teal + явный сигнал «выбери игрока ниже»), `PAUSED` (amber, крупная причина), `BLOCKED`/`role_shortage` (rose, причина крупно, не сноской), `URGENT` (<~10с: rose-пульс + тонкое rose-кольцо карточки), `COMPLETED` (support).
- **`DraftClock` → добавить кольцевой вариант** (новый маленький пресентационный `DraftClockRing`, SVG-кольцо) переиспользуя `remainingMs`/`isUrgent` из `_lib/draft-logic`. Цвет прогресса по состоянию. Живёт **внутри** фокальной карточки — туда же переезжает единственный таймер.
- **Дедуп таймера:** сейчас таймер дублируется в `DraftPageHero` (стат `timeLeft`) и в `CurrentPick`. Оставляем один — в фокальной карточке. В hero стат `timeLeft` убираем.
- **`DraftPageHero`**: стат-слот, освободившийся от таймера, отдаём **pick-map pips** — полоска точек по пикам (done/on-clock/upcoming) с тултипом; статус-pill делаем «живым» (пульс live-точки). Это возвращает прогресс «одним взглядом».

### C. Пул игроков — акцент + плотность + фильтры (`PlayerPool`)
- **Выделение выбора:** выбранная строка = заливка `--aqt-teal`/10 + роль-тинт слева, а не только 2px бордюр.
- **Ранг → дивизион:** справа чип с `PlayerDivisionIcon` (grid турнира) + `getDivisionLabel` в тултипе, вместо `rank_value` текстом.
- **Hero-аватары:** `AvatarStack` из `role_top_heroes` (нормализовать `string | {slug,image_path}` → `getHeroIconUrl`). Для primary-роли (и per-role в досье).
- **Роли:** primary-роль заметнее (крупнее), secondary — отдельными мелкими бейджами; `sub_role`-бейдж, `is_flex`-метка.
- **Ссылка на профиль:** battle_tag → `/users/{slug}` (как в старой доске).
- **Фильтры (T3):** hero-фильтр (поповер с мультивыбором по `role_top_heroes`), счётчики доступных по ролям на кнопках фильтра, расширить `filterDraftPlayers` (`_lib/draft-workspace-model.ts`) на поиск по `sub_role`/лейблам ролей/secondary, а не только `battle_tag`.
- Safe/blocked-состояние читаемее (сейчас blocked гаснет до 55% + мелкий текст) — оставить логику, усилить визуал (rose-иконка + подпись причины).

### D. Досье выбранного игрока (`PlayerInspector`) — «подробный блок» (явный запрос)
Обогащаем инспектор до полноценного досье (Ярус 2, правый рельс):
- Шапка: имя (ссылка на профиль), `#id`, captain-маркер, дивизион-иконка + лейбл (grid турнира).
- **Per-role разбивка:** каждая роль игрока — своя строка: роль-иконка (роль-тинт) + `role_ranks[role]` как «`{SR}` + дивизион-иконка» + hero-аватары этой роли (`AvatarStack`).
- Бейджи `sub_role`, `is_flex`, secondary-роли.
- Заметка `additional_info.notes` (если есть).
- Существующий выбор роли (safe/blocked-гейтинг) — сохраняем, встраиваем в per-role строки.

### E. Ростеры команд (`TeamRosters`)
- **Дивизион по сыгранной роли:** резолвить от `pick.target_role`/соответствующего `role_ranks`, а не `primary_role`; grid = турнирный. (Правит текущую off-role регрессию.)
- **Средний дивизион команды:** стат с `PlayerDivisionIcon` (avg rank → division) + тултип.
- **Слоты по ролям:** индикатор заполнения `tank/dps/support` `{counts}/{targets}` (targets из session).
- **Пустые слоты:** добивать ростер до `team_size` нумерованными «Open slot».
- **On-clock подсветка:** активная команда — teal-подсветка + метка «на часах» (не только my-team бордюр).
- Стат «Roster X/team_size».

### F. Порядок пиков (`DraftOrder`)
- Группировка по раундам + метка правила раунда (snake/custom: forward/reverse/weakest/strongest/lowAvg/highAvg).
- Role-pill целевой роли (`target_role`) на строке пика.
- Дивизион-иконка выбранного игрока (grid турнира).

### G. Presence (`DraftConnectionStatus`)
Per-captain пузыри (T3): по каждому капитану — онлайн/оффлайн точка, имя, инициалы, метка «вы». Агрегат «captains online X/total» + viewer count оставить как сводку.

### H. Command bar (`PickCommandBar`)
- Ready-детали: имя + роль + **SR/дивизион** выбранного (сейчас только `battle_tag · role`).
- Элевация: приподнятая панель (тень) — первичное действие однозначно.
- Цвет по готовности: ready (teal) / blocked (rose/amber).
- **Enter = быстрый пик** (микро-решение, включаю по умолчанию): глобальный `keydown` Enter → open review dialog (сохраняем safety-диалог из редизайна; Enter только ускоряет доступ). Чип-подсказка «Enter».

### I. Ярусность шапок + sticky боковые панели
- Ввести 2 уровня шапок: первичные (`PlayerPool`, `TeamRosters`) — реальный заголовок; справочные (`DraftOrder`, `DraftEventFeed`, `CaptainShortlist`) — тихая мелкая приглушённая шапка. Убрать лишние `HeroCoord`-«координаты» (шум), оставить на фокальной карточке.
- Боковые `<aside>` (order/team) в `CaptainDraftWorkspace` — `position: sticky` (top), чтобы оставались в виду при скролле пула.

### J. Зритель (`SpectatorDraftWorkspace`)
Тот же фокус (чей ход + кольцо таймера) и та же ярусность, чтобы капитан/зритель читались одинаково. Контекстный баннер зрителя — оставить, привести к тихому Ярусу 3.

## Grid-плумбинг
`DraftBoard` уже получает `tournament`. Резолвим `tournamentGrid = tournament.division_grid_version ?? DEFAULT_DIVISION_GRID` один раз и прокидываем вниз (проп `divisionGrid`) в `PlayerPool`, `PlayerInspector`, `TeamRosters`, `DraftOrder`. Убираем локальный `useDivisionGrid()` в `TeamRosters`.

## Данные / API
Изменений нет. Используемые существующие поля: `DraftPlayer.{role_ranks, role_top_heroes, sub_role, is_flex, secondary_roles_json, additional_info, division_number, rank_value, primary_role, is_captain}`; `DraftPick.{target_role, round_no, pick_in_round}`; `DraftSession.{team_size, format, settings_json}`; `Tournament.division_grid_version`. Хелперы: `resolveDivisionFromRank`, `getDivisionLabel`, `DEFAULT_DIVISION_GRID` (`lib/division-grid`), `getHeroIconUrl` (`utils/player`), `AvatarStack` (`ui/avatar`), `PlayerDivisionIcon`, `PlayerRoleIcon`.

## Визуальный язык (маппинг)
- Акцент состояния: `live`→`--aqt-teal`, `paused`→`--aqt-amber`, `blocked`/`urgent`→`--aqt-live`(rose), `done`/`safe`→`--aqt-support`.
- Роль-тинты (вспомогательно): `--aqt-tank` / `--aqt-damage` / `--aqt-support`.
- Элевация: `bg → card → card-2`; фокальная карточка и command bar — единственные с заметной тенью. Радиусы `--aqt-radius`/`--aqt-radius-sm`.
- `prefers-reduced-motion`: пульс/кольцо/scan отключаемы (уже паттерн в проекте).

## Тестирование
- **Юнит (vitest, `bun test <path>`):** чистые хелперы — расширенный `filterDraftPlayers` (поиск по sub_role/ролям), нормализация `role_top_heroes`, группировка пиков по раундам, резолв off-role дивизиона в ростере, маппинг состояние→акцент. Логика гейтинга (`draft-logic`) уже покрыта — не ломать.
- **Ручная проверка:** sticky command bar при длинном пуле (desktop+mobile); состояния фокальной карточки (live/your-turn/paused/blocked/urgent/completed); ранги-иконки во всех 4 местах; off-role ранг в ростере; Enter-подтверждение + safety-диалог; reduced-motion.
- Презентационные компоненты глубоким юнит-тестом не покрываем (YAGNI).

## Риски / открытые вопросы
- `overflow-x: clip` — поддержка во всех целевых браузерах (Chrome 90+/FF81+/Safari16+); ок для веб-приложения 2026. Если внезапно нужен старый Safari — фолбэк на `position: fixed` command bar (как во второй половине старого CSS).
- Плотность на мобиле: hero-аватары + per-role строки могут перегрузить узкие экраны — на мобиле досье/аватары компактнее (ограничить кол-во аватаров, свернуть per-role в основную роль).
- Grid турнира vs workspace: если `tournament.division_grid_version` = null, fallback `DEFAULT_DIVISION_GRID` (не workspace) — сознательно, ради единого источника в комнате.
- Enter-подтверждение: не должно срабатывать при фокусе в поле поиска/инпутах — гардить `target`.

## Итог по объёму (согласовано)
T0 (фиксы) + T1 (акценты/иерархия) + T2 (плотность/OW) + T3 (фильтры пула; порядок+presence) + досье выбранного игрока. Grid = турнирный. Enter-confirm — включаю. Админ-контролы и мульти-цвет команд — вне области.
