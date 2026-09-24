# Единая библиотека компонентов фронтенда — дизайн

**Дата:** 2026-09-24
**Статус:** фазы 1–2 реализованы (2026-09-24), фаза 3 — этот документ как план
**Метод:** superpowers:brainstorming (архитектурный путь)
**Якоря сверены с:** `develop` @ `a678f3e7`
**Связанные документы:** `frontend/DESIGN.md` (правила и таблица примитивов), `docs/design-book.md` (токены, типографика), `docs/frontend-zones.md` (слои и правила импорта)

---

## 1. Проблема

Одно и то же понятие интерфейса реализовано по-разному в каждой зоне (`(site)`, `admin`, `tools`). Сайт рисует
свои версии через CSS-модули и `--aqt-*` в arbitrary-классах, админка — через shadcn-токены и `components/kit`,
драфт и балансер — третьим способом. Пользователь видит разные табы, разные статус-пилюли, разные плитки метрик
на соседних страницах; разработчик каждый раз заново выбирает, какую из копий взять за образец.

Аудит (2026-09-24, шесть срезов: навигация, действия/индикаторы, контейнеры, оверлеи/формы, данные/состояния,
стилевой долг) нашёл по одному-двум хорошим каноническим компонентам почти на каждое понятие — и от 3 до 146 копий
рядом с ними. Задача — не написать новую библиотеку, а назначить канон, довести его до кросс-зонного и перевести
копии.

## 2. Принципы (действуют для всех фаз)

1. **Один компонент на понятие.** Понятие определяется работой, а не внешним видом: «переключить раздел» (табы),
   «переключить вид тех же данных» (ToggleGroup), «переключить маршрут» (ссылочные табы) — три компонента,
   даже если два из них похожи.
2. **Слои не меняются** (`docs/frontend-zones.md`): `components/ui` — примитивы без домена; `components/kit` —
   прикладной кит без зоны; `components/<feature>` — фичи. Канон кладётся на самый нижний слой, куда он
   помещается без доменного знания.
3. **`className` у канона — только лейаут** (ширина, `flex-1`, отступы, мобильный `min-h-11`). Цвет, радиус,
   фон, типографика задаются вариантом компонента. Нужен новый вид — это новый вариант в каноне, а не строка
   классов у вызова.
4. **CSS-класс допустим только как реализация одного React-компонента** (прецедент — `ui/filter-chip.tsx`
   поверх `.aqt-filter-chip`). Сырой `className="status-pill live"` у вызова — копия.
5. **Чистый переход.** Копии удаляются вместе с их CSS; без алиасов и реэкспортов.
6. **Регрессию держит линтер**, а не память: каждая завершённая унификация добавляет правило в
   `scripts/check-design-compliance.mjs` (§5).

## 3. Реализовано в фазах 1–2 (2026-09-24)

| Понятие | Канон | Что заменено |
|---|---|---|
| Табы (разделы, состояние) | `ui/tabs.tsx`: Radix, вид underline по умолчанию, `variant="pill"` для переключателя режима с панелями, `TabsTrigger` с `badge` и `dot`, горизонтальный скролл и удержание активного таба в видимой области | 11 вызовов с собственными стилями (бирюзовая пилюля профиля, серый бокс драфта, shadcn-бокс OWAL/матча) |
| Табы (маршруты) | `kit/LinkTabs.tsx` (бывший `AdminTabs`) — те же классы из `ui/tabs.tsx` (`tabsListVariants`/`tabsTriggerVariants`, `TabBadge`, `TabDot`, `revealTab`) | — (стиль стал общим источником) |
| Переключатель вида | `ui/toggle-group.tsx` (pill) | 3 самописных `role="tablist"` с неверной семантикой: `MasterDetail`, `StandingsList`, `UsersClient` |
| Подтверждение | `kit/ConfirmDialog.tsx` (i18n вместо захардкоженного английского; одна монтировка с подменой `intent` на экран) | сырые `AlertDialog`-копии в 15 файлах site/admin/tools. Оставлены сознательно: check-in в `TournamentParticipantsPage` (внутри форма) и resume-prompt в `admin/tournaments/page.tsx` (Cancel — навигация, не отказ) |
| Статус-точка | `ui/status-dot.tsx` (`tone`, `pulse`, `style` для рантайм-цвета) | точки в `StatusPill`, `FilterChip`, табах, `LiveIndicator`, `ConnectionIndicator`, `RoomHeader`, `PregameHeader` и ещё ~12 местах. Легенды графиков и точки с `animate-ping`-соседом — не статус, оставлены |
| Спиннер | `ui/spinner.tsx` (`label` → `role="status"`) | `Loader2`/`LoaderCircle animate-spin` в ~85 файлах и два одинаковых полноэкранных лоадера. Иконки, которые крутятся как сам смысл кнопки (`RefreshCw`, `Play`), оставлены |
| Статус турнира/матча | `components/tournaments/StatusPill.tsx` → `TournamentStatusPill` (`live/upcoming/finished/draft/open/upset`, точка у `live` встроена), токены `--aqt-status-*` в `globals.css` | сырой `.status-pill` у вызовов, копии в `EncountersTable.module.css` и `Analytics.module.css`. `.tn-status` (безрамочный вариант в таблице турниров) — кандидат на слияние |
| Инициалы, даты | `initials()` в `lib/utils.ts`; `useFormatter()` на сайте/в tools, `kit/format-time.ts` в админке | 8 копий `initials`, голые `toLocale*String()` в ~20 файлах, два самописных `relativeTime` (относительное время теперь `Intl.RelativeTimeFormat`, как в остальном сайте) |
| Префикс `Admin*` в `kit/` | `LinkTabs`, `Combobox`, `FilterBar`, `Inspector`, `SectionNav`, `useFilters`/`FilterState`, `DateFormatter` | исторические имена (`docs/frontend-zones.md` §Historical names). `AdminDataTable` оставлен до 4.4 — имя `DataTable` занято |

## 4. Фаза 3 — крупные унификации

Порядок — по отношению «видимая несогласованность × число копий» к риску миграции. Каждый пункт — отдельный
PR с собственной проверкой; пункты 4.1 и 4.2 блокируют остальные визуально (от них зависят поверхности).

### 4.1 Одна семья токенов на понятие

**Сейчас.** Для одного и того же понятия используются обе семьи: `text-muted-foreground` (~258 файлов) и
`text-[color:var(--aqt-fg-muted)]` (~240 файлов), иногда в одном файле (`AnalyticsStandings.tsx`,
`ForecastChip.tsx`). Плюс пять собственных семей алиасов в CSS-модулях: `--c-*` (`Analytics.module.css`),
`--u-*` (`Users.module.css`), `--enc-*` (`Encounters.module.css`), `--ed-*`
(`EncounterDetail.module.css`), `--tn-*`.

**Факт, снимающий страх.** `WorkspaceThemeSync` → `lib/workspace/theme.ts` пишет **обе** семьи из одной палитры
(`--aqt-fg-muted` и `--muted-foreground` из `fgMuted`, `--aqt-card` и `--card` из `surface` и т. д.), так что
выбор — вопрос читаемости и единообразия, а не темизации.

**Решение.** В TSX — shadcn-утилиты там, где у понятия есть shadcn-имя (`bg-card`, `bg-background`,
`border-border`, `text-foreground`, `text-muted-foreground`, `text-primary`); `--aqt-*` — только для понятий без
shadcn-эквивалента (роли, результаты, статусы, `fg-dim`/`fg-faint`, `card-2`, `border-2/3`, оверлеи). Семьи
алиасов в CSS-модулях удаляются при переводе модуля (4.3–4.7).

**Миграция.** Кодмод через `ast_edit`/регулярку по таблице соответствий (`text-[color:var(--aqt-fg)]` →
`text-foreground`, `text-[color:var(--aqt-fg-muted)]` → `text-muted-foreground`,
`bg-[color:var(--aqt-card)]` → `bg-card`, `border-[color:var(--aqt-border)]` → `border-border`,
`text-[color:var(--aqt-teal)]` → `text-primary`), затем визуальная сверка ключевых страниц (профиль, турнир,
драфт) — значения совпадают, скриншоты должны совпасть попиксельно.

**Правило линтера.** R8: arbitrary-класс с `--aqt-*`, у которого есть shadcn-эквивалент из таблицы.

### 4.2 Карточка / панель

**Сейчас.** `ui/card.tsx` обходят ~103 самописные панели `rounded-* border bg-card` (худшие — шаги мастера
драфта `DraftCaptainsStep`…`DraftSetupPreview`), ~32 панели на `--aqt-border`/`--aqt-card` (сайт, `PlayerPool`,
`TeamsPanel`), константа `PANEL_CLASS` в `balancer/balancer-page-helpers.ts`, система классов
`.aqt-card-surface/-head/-title/-body` в `globals.css` (~245–288) без маркера `data-ui="card"`, на который
опирается тематизация, и карточные классы в 10 CSS-модулях.

**Канон.** `ui/card.tsx` с вариантом плотности:

```tsx
<Card variant="default" | "subtle" | "flush">…</Card>
// default — текущий; subtle — card-2 фон без тени (вложенная панель);
// flush — без радиуса и рамки (секция внутри уже обрамлённого контейнера)
```

Design book §«Air over boxes»: карточка — только для плотных данных. Часть самописных панелей при переводе
должна стать не `Card`, а секцией с hairline-разделителем — решение по месту, фиксируется в PR.

**Миграция.** Шаги мастера драфта (~10 файлов) → панели сайта (~20) → `PANEL_CLASS` → удаление
`.aqt-card-*` из `globals.css`. **Линтер:** R9 — `rounded-(lg|xl|2xl) border` + `bg-card`/`--aqt-card` вне
`ui/card.tsx`.

### 4.3 Плитка метрики

**Сейчас.** ~10 реализаций одного и того же (подпись uppercase + крупное tabular-число + подстрока):
`admin/StatTile.tsx` (+`StatTileGrid`, уже заменил 7 админских копий), `StatisticsCard.tsx` (+
`stats/PlatformStatsGrid.tsx`), `TournamentsKpiStrip.tsx` `KpiCard`, `users/.../maps/atoms.tsx` `KPI`,
`OverviewLastTournamentCard.tsx` `PercentileTile`, `HeroSpotlight.tsx` `QuickStat`, `UserHeader.tsx` `PfStat`,
`OverviewCareerList.tsx` `StatCell`, `tournaments-history.atoms.tsx` `SummaryStrip`, `site/PageHero.tsx`
`HeroStat`. Design book §10 прямо называет это задачей.

**Канон.** `admin/StatTile.tsx` переезжает в `components/kit/MetricTile.tsx` (он не админский по содержанию):

```tsx
<MetricTile label value detail? icon? tone? size?: "sm" | "lg" />
<MetricTileGrid columns?: 2 | 3 | 4>…</MetricTileGrid>
```

Шрифт значения — `font-display` (Onest) и `tabular-nums` по design book §2; low-sample gate (§5 design book)
остаётся у вызова — плитка получает уже готовое `value`/`detail`.

**Миграция.** ~13 файлов. **Линтер:** не нужен (компоненты локальные, после удаления возвращаться не к чему).

### 4.4 Таблица

**Сейчас.** 26 самописных `<table>` в 24 файлах трёх стилей: utility-классы (14 файлов — `MatchesTable`,
`HeroStatsTable`, `OverviewTopHeroesTable`, `LobbyLeaderboardModal`…), CSS-модули (6 — `StandingsTable`,
`EncountersTable`, `AnalyticsStandings`, `UsersClient`, `EncounterSeriesStats`, `TournamentTeamCard`),
без классов (5). Две параллельные обёртки над TanStack: `ui/data-table.tsx` (почти без потребителей) и
`data-table/AdminDataTable.tsx` (~1500 строк, реально используется).

**Канон.** Два уровня, без третьего:

- `ui/table.tsx` — разметка и стили (`Table`, `TableHead` с `scope`, `TableCell` с `numeric` →
  `text-right tabular-nums` по design book §7, sticky-заголовок, `.tblw`-скролл-контейнер) — для **всех**
  read-only таблиц статистики. Им не нужен TanStack: колонки статичны, сортировка — через `useQueryParams`.
- `AdminDataTable` → `data-table/DataTable` (данные с пагинацией, выбором, kebab-колонкой). `ui/data-table.tsx`
  удаляется, его потребители переходят на `DataTable`.

**Миграция.** 26 таблиц → `ui/table.tsx` (по одной странице за PR, визуальная сверка каждой); затем
переименование и слияние обёрток. **Линтер:** R10 — `<table` вне `ui/table.tsx`, `Markdown.tsx`, `mdx.tsx`.

### 4.5 Комбобокс и поиск-селект

**Сейчас.** `kit/Combobox` (бывший `AdminCombobox`) + `kit/useSearchComboboxQuery` уже держат 7 типизированных
обёрток и работают вне админки (`PickupAccessDialog`, `PickupCreateMixDialog`). Рядом ~14 ручных сборок
`Popover`+`Command`: `users/compare/.../UserSearchCombobox.tsx` (дубль имени и смысла админского),
`HeaderCombobox`/`HeaderMultiCombobox`, `PlayerSearchCommandList` (+`MobilePlayerSearchSheet`, `UserSearch`),
`AccountCombobox`, `CataloguePicker`, три в `admin/members/page.tsx`, `StatusForm`, `PlayerPool`. И
`ui/searchable-image-select.tsx` (5 потребителей) с тем же открытием/фильтром/выбором плюс миниатюра.

**Канон.** `kit/Combobox` с `renderItem` для миниатюр (поглощает `searchable-image-select`) и `multiple` для
мульти-выбора (поглощает `HeaderMultiCombobox`). Командная палитра (`AdminCommandPalette`) и строка фильтров
остаются отдельными — у них другая работа.

**Миграция.** ~14 файлов. **Линтер:** R11 — импорт `@/components/ui/command` вне `kit/Combobox.tsx`,
`AdminCommandPalette.tsx`, `kit/FilterBar.tsx`.

### 4.6 Поле формы

**Сейчас.** Три стека подписи/ошибки/подсказки: `ui/field.tsx` (5 потребителей), `registration/FormField.tsx`
(+ хелперы `fieldControlClass`/`fieldInvalidClass`, используемые в обход компонента в 5 файлах),
`forms/GenericField.tsx` (поверх второго, для схемных форм). Плюс ~35 компонентов с голыми
`<label>`/`<input>`/`<select>` (`MyTeamPanel.tsx` — нативный `<select>` и повторяющиеся пары).

**Канон.** `ui/field.tsx` (`Field`/`FieldLabel`/`FieldContent`/`FieldDescription`/`FieldError`) — он уже
shadcn-стандарт и связывает `aria-describedby`/`aria-invalid`. `registration/FormField` становится тонкой
композицией над ним или удаляется; `GenericField` рендерит через `Field`.

**Миграция.** Сначала регистрация и схемные формы (одна поверхность, есть тесты), затем голые поля по
экранам. **Линтер:** R12 — нативный `<select` вне `ui/select.tsx`.

### 4.7 Кнопка

**Сейчас.** 146 голых `<button>` в обход `ui/button.tsx`, в основном на сайте: текстовые действия
(`TOURNAMENT_TEXT_ACTION_CLASS`, `TOURNAMENT_PRIMARY_ACTION_CLASS` в `TournamentRegisterButton.tsx`),
иконочные (`ACTION_BUTTON` в `MobileBracket.tsx`), сегмент-кнопки с `aria-pressed`
(`EncountersClient`, `AnalyticsStandings`, `achievements/page.tsx`), строки-кнопки (законно).

**Канон.** `ui/button.tsx` с вариантами сайта в том же `cva` (не второй компонент): существующие
`default/outline/ghost/link` + размеры `icon-sm`. Сегмент-кнопки с `aria-pressed` — это фильтр-пресеты →
`FilterChip`; строки-кнопки остаются как есть.

**Миграция.** Именованные константы (~15 файлов) → остальное по экранам. **Линтер:** расширение существующего
R7 (fake-button) на `<button className=` с цветовыми классами.

### 4.8 Заголовки: страница, сущность, секция

**Сейчас.** `admin/AdminPageHeader.tsx` и `kit/EntityHubHeader.tsx` с разными API для одной работы;
`site/PageHero.tsx` — отдельный уровень (лендинговый герой, законно); самописные заголовки сущностей:
`UserHeader`, `ComparePageHero`, `HeroCompareHero`, `WorkspaceHeader`, `AchievementDetailHeader`,
`PregameHeader`, `draft/RoomHeader`. Секционный заголовок (эйбров + `h2` + «Смотреть все →») не выделен:
~10–15 настоящих секций, `SectionLabel` в `StatisticsPage.tsx` и `TournamentDossier.tsx`.

**Канон.** Два компонента:

```tsx
<PageHeader title status? meta? actions? backHref? level? />   // слияние AdminPageHeader + EntityHubHeader
<SectionHeader eyebrow? title action?: { label, href } />      // «View all →» из design book §6
```

`PageHero` остаётся отдельным уровнем. Заголовки драфта/прегейма (live-состояние, таймеры) переводятся только
в части мета-строки и статуса — их тело доменное.

**Миграция.** ~9 файлов на `PageHeader`, ~12 на `SectionHeader`.

### 4.9 Навигация разделов (вертикальная)

**Сейчас.** `kit/SectionNav.tsx` (бывший `AdminSectionNav`: rail на `md+`, `Select` ниже),
`(site)/tournaments/[slug]/_components/TournamentSectionNav.tsx` (свой rail со сворачиванием, закрытыми
пунктами и скелетоном, ~250 строк CSS в `TournamentDetail.module.css`), боковая колонка табов в
`AccountSettingsModal.tsx` (Radix Tabs со своими стилями — оставлена в фазе 1 сознательно: это вертикальный
rail, а не ряд табов).

**Канон.** `kit/SectionNav` с опциями `collapsible` и `lockedReason(item)`; вариант «state» (кнопки с
`role=tab` через Radix `orientation="vertical"`) для модалки настроек — появляется только вместе с переводом
`AccountSettingsModal`, не раньше.

**Миграция.** 3 файла + чистка CSS-модуля; нужен паритет поведения (сворачивание, закрытые пункты).

### 4.10 Мелочи, закрываемые по пути

- Пилюли-тоны в `EncounterDetail.module.css` (`.pill/.pillAccent/.pillWarn/.pillDanger/.pillGood`) →
  `Badge tone=`.
- Фильтр-чипы в `Users.module.css`, `Encounters.module.css`, `docs.module.css` → `FilterChip`;
  `AdminFilterBar`/`RadarAxisPicker`, применяющие сырой класс `aqt-filter-chip`, → `<FilterChip>`.
- W/L/D-чип (`users/.../shared/atoms.tsx` `FormStreak`) → `kit/ResultChip` при появлении второго DOM-потребителя
  (канвас-версия в `SharePlayerCard.tsx` законно отдельна).
- `EditableAvatar` рисует превью голым `<img>` → `AvatarImage`.
- `title=` как единственное объяснение «почему выключено» (~15 мест: `MyRegistrationCard`, `PregameHeader`,
  `AdminAuditPage`) → `Tooltip` (design book §4: всплывашки открываются и с фокуса).
- Пустые состояния админки: сырой текст (`AchievementDetailPage.tsx` «Achievement not found») и `emptyMessage`
  таблицы на ошибке → `PageStateCard state="error"`.

## 5. Защита от регрессии

`scripts/check-design-compliance.mjs` получает правило вместе с каждой завершённой унификацией (иначе копия
вернётся в следующем PR):

| Правило | Ловит | Исключения |
|---|---|---|
| R8 | `--aqt-*` в arbitrary-классе при наличии shadcn-имени (4.1) | `globals.css`, `lib/workspace/theme.ts` |
| R9 | самописная панель `rounded-* border bg-card` (4.2) | `ui/card.tsx` |
| R10 | `<table` (4.4) | `ui/table.tsx`, `Markdown.tsx`, `mdx.tsx` |
| R11 | импорт `ui/command` (4.5) | `kit/Combobox.tsx`, `AdminCommandPalette.tsx`, `kit/FilterBar.tsx` |
| R12 | нативный `<select` (4.6) | `ui/select.tsx` |
| R13 | `role="tablist"` вне канона, импорт `Loader2`/`LoaderCircle` вне спиннера, сырой класс `status-pill` (фазы 1–2, можно включить сразу) | `ui/tabs.tsx`, `ui/toggle-group.tsx`, `ui/spinner.tsx`; таблицы статус→иконка `TournamentLogsTab.tsx` (`STATUS_META.processing`) и `EvaluationRunSummary.tsx` (`STATUS_ICON.running`) |

## 6. Проверка каждого PR фазы 3

- `bun run typecheck`, `bun run lint`, `bun run lint:zones`, `bun run lint:design`, `bun run test:vitest`.
- Визуальная сверка затронутых экранов в браузере на 375 / 1024 / 1440 px (DESIGN.md §Breakpoints) —
  до/после; для 4.1 скриншоты обязаны совпасть.
- Обновление таблицы «Shared primitives» в `frontend/DESIGN.md`: канон вписывается, копии не упоминаются.

## 7. Не входит

- Светлая тема (design book: dark-only).
- Storybook/каталог компонентов: таблица примитивов в `DESIGN.md` и интерактивная design book
  (`public/docs/design-book.html`) закрывают потребность; вернуться, если число примитивов в `ui/` + `kit/`
  перевалит за ~80.
- Вынос библиотеки в отдельный пакет: один деплой, одна команда (`docs/frontend-zones.md` §«What a split would
  still have to solve»).
