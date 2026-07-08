# (site) Hardcoded-String Inventory & Coverage Plan

Source of truth for Phase 3 (translation coverage) of the next-intl migration.
Built from a 6-agent parallel audit of `frontend/src` on 2026-07-08.

## Magnitude

~600–800 user-facing hardcoded strings across ~70 files. Several `(site)` areas
have **zero** i18n today (no `t()` at all): `users/**`, `teams/**`,
`(home)`, `workspace/[slug]`, `statistics`, `owal`, `encounters` redesign,
`matches` list. Others are partially wired (draft, tournament detail,
analytics) with stray leftovers.

## Scope decisions

INCLUDE:
- All visible UI text on `(site)` pages + shared components rendered on `(site)`.
- Metadata/SEO (`layout.tsx` titles/descriptions, `generateMetadata`) — via
  `getTranslations()` in server components. Lower priority but in scope.
- `analytics/MLAdminToolbar.tsx` (organizer-gated but under `(site)`).
- DraftBoard `label(t, key, "EN")` fallbacks — ~45 `draft.*` keys MISSING from
  both catalogs; adding the keys "lights them up" with NO call-site change.

EXCLUDE / special-handling:
- admin-mode branches of shared registration components (admin, out of scope).
- Dead code (strings never rendered): `analytics/RanksPage.tsx` (not imported),
  `analytics.helpers.ts` unused `getConfidenceBreakdownLines`,
  `compare/CompareSummaryBadges.tsx` + `CompareMetricsCard.tsx` (not rendered by
  compare/page), `HeroesView.tsx` L287-315 commented strip.
- `"TBD"` in `BracketView`/`FeaturedLive`/`encounters` — also a **logic
  sentinel** (compared as a string). Do NOT blindly replace; keep the sentinel,
  translate only the rendered fallback OR leave as universal abbreviation.
- Achievements force Russian via `description_ru` / `descriptionLocale="ru"`
  (data-level, needs backend en/ru descriptions) — flag, do not fake in FE.
- Borderline single-letter/acronym headers (W/L/D, KDA, MVP, WR, PRS, FB…) —
  keep as-is where they are universal; key only where a full word.
- Hero/map/team names, hardcoded `en` in `toLocaleString("en")` /
  `Intl.DateTimeFormat("en")` — the latter should use the active locale
  (fold into Phase 4 date/number unification).

## Shared `common.*` additions (author once, reuse everywhere)

Add to both dicts (esports register, RU per GLOSSARY.md):
`analytics` (Аналитика), `live` (Live), `open` (Открыть), `view` (Открыть),
`champions` (Чемпионы), `loadError` ("Не удалось загрузить данные."),
`noResults` ("Ничего не найдено."), `tbd` (TBD), `overview` (Обзор),
`tournament` (Турнир), `stage` (Этап), `updated` (Обновлён), `players` (Игроки),
`prev` (Назад), `next` exists, `close` (Закрыть), `search` (Поиск),
`add`/`remove` (Добавить/Убрать), `collapse`/`expand` (Свернуть/Развернуть),
`loadMore` (Загрузить ещё), `unknown` (Неизвестно), `any` (Любой),
`homeTeam`/`awayTeam` (Хозяева/Гости), `selectPlaceholder` ("Выберите…"),
`required` (Обязательно), `sortBy` (Сортировка), `system`/`custom`,
`vs` (vs), `liveCount`/`upcomingCount` (ICU-ish, count+word),
`role.{tank,dps,support,flex}` (canonical role labels — unify the 3 hardcoded
copies), `subroleShort.*`, `checkedIn`/`notCheckedIn`,
`profileOpen`/`profileClosed`/`profileNotChecked`, `time.{justNow,minutes,hours,days,soon}`
(relative-time; ICU where count-bearing), `divisionWithId`, `stageWithId`.

## Per-area namespaces & files (execution units)

Priority order = public traffic first, self-contained first.

### P1 — tournaments list  (`tournamentsList.*`)  ~40 strings
Files: `app/(site)/tournaments/page.tsx`, `components/TournamentsHero.tsx`,
`TournamentsFilters.tsx`, `TournamentsTable.tsx`, `TournamentCard.tsx`,
`FeaturedLive.tsx`, `tournaments-helpers.ts`, `layout.tsx` (meta),
`[id]/components/TournamentProfileTabs.tsx`.

### P2 — tournament detail leftovers  (`tournamentDetail.*` + `common.role.*`)  ~30
Files: `[id]/layout.tsx` (meta), `_components/TournamentSectionNav.tsx`,
`pages/TournamentStandingsPage.tsx`, `TournamentTeamsPage.tsx`,
`TournamentParticipantsPage.tsx` (incl. L865 locale ternary),
`pages/_components/ColumnPicker.tsx`, `participantsColumns.tsx`,
`TournamentHistoryCell.tsx`, 6× `[id]/{bracket,standings,matches,teams,participants,heroes}/page.tsx`
(all duplicate `common.tournamentNotFound`).

### P3 — home / workspace / statistics / owal  (`home.*`,`workspace.*`,`statistics.*`,`owal.*`,`notConfigured.*`)  ~110
Files: `(home)/page.tsx`, `workspace/[slug]/page.tsx`, `statistics/page.tsx`
+ `statistics/layout.tsx`, `not-configured/page.tsx`, `owal/components/*` (3),
`owal/layout.tsx`. NOTE: StatisticsCard labels + live/upcoming/view duplicated
across home+workspace+statistics → shared keys.

### P4 — shared components on (site)  (`standings.*`,`bracket.*`,`rankHistory.*`)  ~35 (excl. admin-mode)
Files: `components/StandingsTable.tsx`, `BracketView.tsx` (RU title/aria +
headers; TBD sentinel care), `RankHistoryChart.tsx`, `UserRankHistory.tsx`,
`BattleTagRankHistory.tsx` (all 3 share `rankHistory.*`, kill locale-ternary),
`LanguageSwitcher.tsx` (title ternary → `common.switchLanguage`),
`registration/{FieldLabel,CustomField,AccountCombobox,AccountStep(public bits),VerifiedAccountSelect}.tsx`,
`tournaments/{EncounterEditDialog,MatchReportDialog}.tsx` (RU aria/fallbacks),
`status/RegistrationBadges.tsx`.

### P5 — matches  (`matches.*`)  ~40
Files: `matches/page.tsx`, `matches/layout.tsx`, `matches/[id]/page.tsx`,
`matches/[id]/components/MatchTeamTable.tsx`.

### P6 — encounters  (`encounters.*`)  ~130  (LARGEST single file: EncountersRedesignClient.tsx)
Files: `encounters/page.tsx`, `layout.tsx`,
`_components/encounters-redesign.helpers.ts`, `_components/EncountersRedesignClient.tsx`,
`[id]/page.tsx`, `[id]/components/{EncounterMatch,EncounterTeamCard,MatchStatsChart,MapVeto,ResultSubmission}.tsx`.
Note MapVeto/ResultSubmission also render raw enum values needing translation.

### P7 — draft leftovers  (`draft.*`)  ~90 (incl. ~45 missing `label()` keys)
Files: `[id]/draft/page.tsx`, `_components/DraftClock.tsx`, `DraftBoard.tsx`.
Bulk = add missing `draft.*` keys to both catalogs (no call-site change) +
replace pure literals (You, PAUSED, round-rule labels, pool UI, player fallback).

### P8 — achievements  (`achievements.*`)  ~40
Files: `achievements/page.tsx`, `[id]/page.tsx`, `components/ConditionTreeView.tsx`,
`[id]/components/AchiementUsers.tsx`. Flag `description_ru` (data-level).

### P9 — users + teams  (`users.*`,`teams.*`)  ~250  (LARGEST area, ZERO coverage)
Files: `teams/page.tsx`+`layout.tsx`; `users/**` — `[slug]/page.tsx`(meta),
`opengraph-image.tsx`, `layout.tsx`, `_components/UsersRedesignClient.tsx`(~90),
`components/users-overview/*`, `components/header/*`, `components/tabs/*`,
`components/overview/*`, `components/heroes/*`, `components/maps/*`,
`components/matches/*`, `components/tournaments/*`, `components/achievements/*`,
`compare/**`, `heroes-compare/**`. Fold shared repeats (division/role labels,
"All roles/tournaments/heroes", pagination "Showing…of…", vs, playtime fmt)
into `common.*`/`users.*` not per-file dupes.

### P10 — analytics leftovers  (`analytics.*`)  ~40
Files: `analytics/components/MLAdminToolbar.tsx` (organizer-gated, ~30),
`AnalyticsStandings.tsx` (expert-table modal + title tooltips),
`MatchQualityCard.tsx` (" vs "), `ExplanationPopover.tsx` (" / 10 min"),
`analytics/layout.tsx` (meta). Skip dead `RanksPage.tsx`.

## Execution method

Per area: (1) author new keys in BOTH `en.json`/`ru.json` (quality-critical,
esports RU per glossary), (2) wire call-sites — client → `useTranslations(ns)`,
server → `getTranslations(ns)`; handle dynamic keys, sentinels, enum labels,
(3) `bun test src/i18n/messages.parity.test.ts` + `bun run build`, (4) commit
`feat(i18n): translate <area>`. Parity test guards en/ru key symmetry each step.
