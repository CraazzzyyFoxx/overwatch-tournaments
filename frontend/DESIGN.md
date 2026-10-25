# OWT Design System

The single source of truth for how the OWT frontend looks and behaves. Read it
before you add or change anything a user sees: a page, a component, a row, a
label. When this file and the code disagree, the code is a bug or this file is
stale — say which, do not average the two.

- Tokens live in `src/app/globals.css`. Every value quoted here is copied from
  there; if a value moves, `globals.css` wins.
- The interactive token sheet is `public/docs/design-book.html` (served at
  `/docs/design-book.html`). It illustrates; it does not override this file.
- `npm run lint:design` (`scripts/check-design-compliance.mjs`) enforces the
  mechanical subset: no raw hex or Tailwind neutrals, the `color:` hint, an
  11px hard floor on type, no glyph icons, no fake buttons.

## 0. The five rules agents break most

1. **A chip is not a style.** Plain text is the default for every fact. A chip
   is allowed for exactly four jobs — see §4. "It looks nicer in a pill" is
   never one of them.
2. **Say a fact once.** If the card title says the round, the row does not.
   If the score is coloured, there is no "Winner" pill next to it. If a whole
   round is Bo3, "Bo3" goes in the round's header, not on each match.
3. **Show a control only when there is a choice.** One stage → no stage chips.
   One tab → no tab bar. A filter whose count equals the total → hidden.
4. **Reuse, do not re-roll.** Before writing markup, check §6. A new
   hand-rolled `rounded-full border px-2` span is the most common way this
   codebase got 30 chip implementations.
5. **Colour means something.** Colour comes from a token and encodes a result,
   a quality, a role, a status, a group or a medal (§2). Never decoration.

## 1. Atmosphere

**Editorial Tactical**, dark only. An analytics product for tournament
players: every screen answers a concrete question ("who won", "who carried",
"which maps get played") and the data is the interface.

- _Editorial_: hairline rules, open sections, mixed-case headings, whitespace
  as the grouping device.
- _Tactical_: a broadcast-overlay voice for data — small uppercase labels,
  tabular figures, a heavy display face on scores.
- Dials: **variance 3** (calm, grid-aligned, predictable), **motion 2**
  (colour/opacity transitions only), **density 6** ("analytics comfortable":
  denser than marketing, never cramped).
- One accent: teal. Everything else on screen is a neutral or a data colour.

## 2. Colour

Two token families coexist:

- `--aqt-*` hold **complete colours** (`hsl(220 22% 8%)`) and are used
  directly: `bg-[color:var(--aqt-card)]`.
- shadcn tokens (`--background`, `--card`, `--border`, `--primary`, …) hold
  **bare HSL triplets**, because Tailwind wraps them: `bg-card`.

Never redefine a shadcn token name inside a scoped block (`.x { --card: … }`
makes `hsl(var(--card))` resolve to `hsl(hsl(…))` and the surface silently
goes transparent). Scoped aliases take their own prefix (`--tn-*`, `--ed-*`).
Arbitrary Tailwind colours need the `color:` hint:
`text-[color:var(--aqt-fg)]`, never `text-[var(--aqt-fg)]`.

### Ground and text

| Token                  | Value                    | Role                                             |
| ---------------------- | ------------------------ | ------------------------------------------------ |
| `--aqt-bg`             | `hsl(220 21% 5%)`        | page background                                  |
| `--aqt-bg-2`           | `hsl(220 22% 7%)`        | hero frame, raised page band                     |
| `--aqt-card`           | `hsl(220 22% 8%)`        | section card                                     |
| `--aqt-card-2`         | `hsl(222 24% 11%)`       | nested surface, bar track on a card, floating panel fill |
| `--aqt-overlay-1`      | `hsl(0 0% 100% / 0.015)` | group card fill (`.team-card`)                   |
| `--aqt-overlay-2`      | `hsl(0 0% 100% / 0.025)` | **row hover**, bar track                         |
| `--aqt-overlay-3`      | `hsl(0 0% 100% / 0.05)`  | pressed / neutral tint, a tonal button at rest   |
| `--aqt-overlay-4`      | `hsl(0 0% 100% / 0.08)`  | a tonal button under the pointer, the cursor row of a floating panel |
| `--aqt-overlay-border` | `hsl(0 0% 100% / 0.06)`  | group card border, in-card dividers              |
| `--aqt-sheen`          | `hsl(0 0% 100% / 0.22)`  | the 1px light along a filled button's top edge   |
| `--aqt-border`         | `hsl(219 19% 15%)`       | hairline, section card border                    |
| `--aqt-border-2`       | `hsl(217 17% 21%)`       | control border                                   |
| `--aqt-border-3`       | `hsl(216 16% 26%)`       | hover / focus / active border                    |
| `--aqt-fg`             | `hsl(214 33% 96%)`       | primary text, values                             |
| `--aqt-fg-muted`       | `hsl(212 13% 65%)`       | secondary text, loser's score                    |
| `--aqt-fg-dim`         | `hsl(213 9% 58%)`        | meta lines, the `·` separator, muted rows        |
| `--aqt-fg-faint`       | `hsl(214 10% 52%)`       | labels, column heads, ranks — the floor for text |

Nesting is expressed with overlays, never a new grey. Exactly three borders.

### Accent and data colours

| Group    | Tokens                                                                                                                        | Used for                                                                                    |
| -------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Accent   | `--aqt-teal` `hsl(172 70% 49%)`                                                                                               | links on hover, active tab/filter, focus ring, a winner's score, bars with no other meaning |
| Featured | `--aqt-warm` (= `--aqt-amber`)                                                                                                | the featured tournament, titles, the captain crown. Rare.                                   |
| Roles    | `--aqt-tank` `hsl(209 82% 65%)`, `--aqt-damage` `hsl(337 81% 66%)`, `--aqt-support` `hsl(150 57% 52%)`, `--aqt-flex` (violet) | role icons, role bars, the role-share spectrum                                              |
| Results  | win `--aqt-emerald`, loss `--aqt-rose`, draw `--aqt-amber`                                                                    | a map score, W/L/D squares, form streak                                                     |
| Quality  | `winrateColor(pct, lowSample)` in `lib/colors.ts` (≥60 emerald, 50–59 amber, <50 rose; greyed on a low sample)                | winrate, deltas, impact                                                                     |
| Status   | `--aqt-status-live` / `-upcoming` / `-finished` / `-draft`                                                                    | `TournamentStatusPill` only                                                                 |
| Medals   | `--aqt-medal-gold` / `-silver` / `-bronze` (+ `-fg`)                                                                          | places 1–3 of a **finished** competition                                                    |
| Groups   | `groupHue(name)` in `lib/tournament/group.ts`                                                                                 | cycles teal → amber → violet → blue → rose → emerald                                        |
| Brands   | `--aqt-brand-*`                                                                                                               | social/provider icons only                                                                  |

Rules:

- Never raw hex, `white/N`, `slate-*` or `zinc-*`: workspace theming
  (`WorkspaceThemeSync`) cannot reach them.
- Results, roles and statuses are separate meanings even where they share a
  hue: paint a win with `--aqt-emerald`, never `--aqt-support`; a live state
  with `--aqt-status-live`, never `--aqt-rose` directly.
- Never colour-only: a W/L square carries its letter, a status pill its word,
  a pip strip an `aria-label` summary.
- The role spectrum (tank→damage→support gradient) is data: a role
  distribution bar, or the profile header hairline. Never a decorative
  gradient.

## 3. Typography

Two faces, self-hosted with `next/font/local` in `src/app/layout.tsx`, their
`.variable` classes mounted on `<html>` (not `<body>`: `globals.css` aliases
them from `:root`, which cannot see a variable defined below it).

| Face        | Token / utility                                                 | Use                                                                              |
| ----------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| **Inter**   | `font-sans`, `--aqt-data`, `.aqt-tnum` (Inter + `tabular-nums`) | all text, labels, table cells, numbers in rows                                   |
| **Onest**   | `font-display`, `--aqt-display`                                 | page titles, section titles, scores (`.score`, `.boardScore`), large KPI figures |
| system mono | `font-mono`                                                     | code and identifiers only (API keys, log output). Never a UI label.              |

**Type roles are the only sizes** (`@theme static` in `globals.css`; each
carries its line-height, weight stays explicit):

| Utility         | Size / lh           | Use                                                                                                |
| --------------- | ------------------- | -------------------------------------------------------------------------------------------------- |
| `text-label`    | 12 / 1.25           | eyebrows, column heads, fact labels, counters — with `uppercase tracking-label` when it is a label |
| `text-caption`  | 13 / 1.4            | secondary text, meta lines, table cells                                                            |
| `text-body`     | 14 / 1.5            | body copy                                                                                          |
| `text-ui`       | 15 / 1.5            | row primary text, stage headings (`font-semibold`)                                                 |
| `text-heading`  | 18 / 1.3            | card and block sub-headings                                                                        |
| `text-title`    | 22 / 1.15 / −0.01em | section `h2`, mixed case, display face                                                             |
| `text-headline` | 30 / 1.1 / −0.02em  | compact hero titles                                                                                |
| `text-display`  | clamp(32–56) / 1.03 | page-hero `h1`                                                                                     |

- `tracking-label` (0.08em) is the only tracking for uppercase text. Not
  `tracking-[0.06em]`, not 0.04em.
- No `text-[Npx]`, no `font-size: 11px`. Missing a size? Add a role.
- Numbers that line up use `.aqt-tnum`.
- Uppercase is for labels the product writes ("ROLE", "AVG SR"), never for
  user content (team names, tournament names, nicknames).
- `cn()` (`lib/utils.ts`) knows these role names; keep using it, or
  tailwind-merge files `text-label` under colour and drops it.

### Control text

A control's text is set by its primitive, never at the call site. The `size`
prop picks the row; the text follows the row height:

| Row                  | `size`           | Text                 |
| -------------------- | ---------------- | -------------------- |
| 32px (toolbar row)   | `sm`             | 13px `text-caption`  |
| 36 / 40px (form row) | `default` / `lg` | 14px `text-sm`       |

- Weight follows the role: what you press (`Button`, `SelectTrigger`,
  `FilterChip`, `ToggleGroupItem`, `TabsTrigger`, date and combobox
  triggers) is 500; what you type into (`Input`, `NumberInput`, `TimeInput`,
  `Textarea`, `SearchField`) is 400.
- A filled button (`default`, `destructive`, `positive`) is 600; its text is
  its row's size and sentence case, like every control. The fill and its
  sheen carry the emphasis, not the type.
- Text-entry fields stay 16px below `sm`: iOS Safari zooms into any smaller
  focused field. The primitives carry this; do not undo it.
- No `text-*` or `font-*` on a control, no `h-8`/`h-9` where `size` says it.
  `Button`, `SelectTrigger`, `Input`, `NumberInput` and `TimeInput` take
  `size="sm"`; a smaller box (`h-7`) still takes `size="sm"` for its text.

## 4. Chips — the policy

A chip is a small bordered or tinted label. The codebase has about 30
implementations and about 150 uses on the public site; most of them wrap a
plain fact. That ends here.

### A chip is allowed for exactly four jobs

| #   | Job                                       | Component                                                                                                           | Notes                                                                                                                                                                                                     |
| --- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Interactive filter / toggle**           | `FilterChip` in `FilterChipGroup` (`ui/filter-chip.tsx`)                                                            | A real `<button aria-pressed>`. Only when there is more than one option; hide a chip whose count is 0 or equals the total. A chosen entity (a team, a map) becomes a removable `active` chip with `×`.    |
| 2   | **Lifecycle status that wants attention** | `TournamentStatusPill` (`tournaments/StatusPill.tsx`); admin: `kit/StatusPill`                                      | Live, upcoming, draft, disputed, pending confirmation, an active session. **Not** "finished/completed" on a list where most items are finished — the absence of a pill says finished. One status per row. |
| 3   | **Categorical colour key**                | group: `.group-chip` + `groupHue()`; medal: `PlaceBadge` (`ui/place-badge.tsx`); W/L/D: `ResTag` / `.aqt-form-chip` | Only where the colour distinguishes items within the same view (Group A vs Group B rows in one Swiss round). A medal only for places 1–3 of a finished competition.                                       |
| 4   | **Count**                                 | `FilterChip count`, `TabsTrigger badge` (`ui/tabs.tsx`)                                                             | A count attached to a control. A standalone count is text.                                                                                                                                                |

### Everything else is text — use these instead

| You want to show                                 | Do this instead of a chip                                                                                                              |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| A format (`Bo3`), a round, a stage               | the card/section header that groups the rows (`metricValue`, `.sectionMeta`) — said once                                               |
| A label:value fact ("Teams 16", "Format League") | a `<dl>` fact (label `text-label uppercase tracking-label`, value below) or `Label value` text                                         |
| A qualifier of a title ("Tank · 19.7%")          | muted inline text: `<span class="text-[color:var(--aqt-fg-dim)] font-normal">· 19.7%</span>`                                           |
| A list of meta facts                             | one `text-caption text-[color:var(--aqt-fg-muted)]` line joined with `·` (dot in `--aqt-fg-dim`)                                       |
| Winner / loser                                   | colour the score (teal winner, muted loser) and weight the name                                                                        |
| Home / away                                      | position (home left, away right). Nothing else.                                                                                        |
| A placement outside the medals                   | `#7` in `.aqt-tnum` text                                                                                                               |
| A BattleTag discriminator                        | `#1234` in `--aqt-fg-faint` text after the nick                                                                                        |
| "League", "Preview", "New", "Sub", "Late" flags  | a word in the meta line, or an icon with `aria-label` + `title`; a status pill only if it is the one state on that row worth attention |
| A boolean state (checked-in, verified)           | an icon (`StatusIconBadge`, `role="img"` + `aria-label`), no "Yes/No" word                                                             |
| A role                                           | `PlayerRoleIcon` (icon only in rows; icon + word only in a role split)                                                                 |
| A division                                       | `DivisionIcon`, name in `title`                                                                                                        |

### Limits

- At most **two chips in a header**, at most **one per row** of a list.
- No chips inside table cells, except a status column.
- Never a chip whose content repeats text already visible nearby (a "Final"
  pill under a 3:0 board, "1st place" beside `#1`).
- Never stack chips inside a chip, or a chip inside a card header that
  already carries the same meaning in its title.
- Uppercase chips only for product-written words; never for user content.
- Before adding one, answer: _which of the four jobs is this?_ If none, it is
  text.

## 5. Shape, surfaces, elevation

| Element                        | Radius                  | Surface                                               |
| ------------------------------ | ----------------------- | ----------------------------------------------------- |
| Group card (`.team-card`)      | 12px                    | `--aqt-overlay-1` fill, `--aqt-overlay-border` border |
| Section card (`Card`, `.card`) | 12px (`rounded-xl`)     | `--aqt-card` fill, `--aqt-border` border              |
| Page hero (`HeroFrame`)        | 14px (`--aqt-radius`)   | `--aqt-bg-2`, one teal hairline, one corner glow      |
| Controls, filter chip          | 8px (`--aqt-radius-sm`) | `--aqt-overlay-2`, `--aqt-border-2`                   |
| Button (`ui/button.tsx`)       | 8px (`rounded-lg`)      | filled: its tone + `--aqt-sheen` top line; `outline`: `--aqt-overlay-3` + `--aqt-border-2` + an `--aqt-overlay-3` top line |
| Select / combobox trigger      | 8px (`rounded-lg`)      | the `outline` button's surface (`outlineSurfaceClass`); `--aqt-border-3` while its panel is open; public forms take `variant="surface"` |
| Floating panel (`floatingPanelClass`) | 10px, rows 6px   | `--aqt-card-2` fill, `--aqt-border-2` rim, an `--aqt-overlay-3` top line; every select and combobox list, menu, popover and (at 6px) tooltip |
| Status pill, `Badge`           | `rounded-md`            | tone tint (`TONE_CLASS`)                              |
| Bars                           | `rounded-full`          | `--aqt-overlay-2` / `--aqt-card-2` track              |

- **One level of framing.** A card never contains a card. Inside a card,
  group with `tc-divider` / `divide-y` hairlines and whitespace — no tiles,
  no tinted callouts, no coloured left borders.
- **When to frame.** Frame a group of rows that belong together (a team, a
  round, a role column, a day of matches) or a dense data block. A page
  section is open: a heading, then its content. Admin settings (T5) and the
  person, team and achievement hubs (T3) are the exception: each section
  there is a `SettingGroup` card, and a table, chart or list inside one drops
  its own frame (`DataTable framed={false}`, `RankHistory framed={false}`, a
  `LoadErrorNote` for a failed read, never a `PageStateCard`).
- No shadows on dark surfaces; elevation is fill + border. The one exception
  is the inset 1px top line of a button and a floating panel (`--aqt-sheen`
  on a filled button, `--aqt-overlay-3` on a tonal one and on a panel): a lit
  edge, not a drop shadow.
- A floating panel is lighter than whatever it opens over (page, card,
  dialog). Its rows: the cursor (pointer or arrow keys) is `--aqt-overlay-4`;
  the chosen value is a teal check (right in a select or combobox, left in a
  menu's checkbox or radio item), never a fill; a group label is an eyebrow.
- A button sits above its surface, never below it: its fill is lighter than
  the page, card or dialog it is on. A fill darker than the surface reads as
  a hole, not as something to press.
- Hover on a row is `bg-[color:var(--aqt-overlay-2)]`; on a card it is the
  border moving to `--aqt-border-3` (or teal for a whole-card link). Never a
  scale or size change.

## 6. Components — reuse these, do not re-roll them

### Foundations

| Need                       | Use                                                                                                                                                                                                                                                                                                    |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Titled group card          | `TournamentTeamCardFrame` (`components/TournamentTeamCard.tsx`): `name`, optional `leadingTag` / `positionTag`, `metricLabel` + `metricValue` on the right, `side` for a home/away top edge. Teams, match rounds, map-pool rounds and stat role columns all use it. Do not retype its classes by hand. |
| Section card               | `Card` (`ui/card.tsx`, keeps `data-ui="card"`); `variant="flat"` for a list or table frame with no shadow — never a hand-typed `rounded-xl border bg-card` |
| Page hero                  | `PageHero` / `HeroFrame` (`components/site/PageHero.tsx`); `variant="plain"` on `/` and `/get-workspace`                                                                                                                                                                                               |
| Profile section / open KPI | `CardSurface`, `ProfileStat`, `SummaryCellBox` (`components/profile/atoms.tsx`): uppercase label, Onest figure, dim sub line, colour only for quality                                                                                                                                                  |
| Empty / error / not-found  | `PageStateCard` (`ui/page-state-card.tsx`); on tournament sections `TournamentPageState` (adds `refresh-error` under stale content); inside a card, `EmptyNote` and, for a failed read, `LoadErrorNote` (`kit/EmptyNote.tsx`)                                                                         |
| Skeletons                  | `ui/skeleton.tsx` (`variant="text"` for one line of text; stops pulsing under reduced motion); tournament sections `_components/TournamentSkeletons.tsx`; open sections draw their own skeleton beside the section (`LeadersSkeleton`, `statistics/_components/*Skeleton`)            |
| Link with hover prefetch   | `HoverPrefetchLink`; "← Back to …" text link `BackLink` (`components/site/BackLink.tsx`)                                                                                                                                                                                                              |
| Team identity              | `TeamName` / `TeamLogo` (`components/TeamName.tsx`) — no fallback glyph when a team has no image                                                                                                                                                                                                       |
| Player identity            | `PlayerName` (profile link); a bare handle `HandleLabel` (`components/HandleLabel.tsx`: name + faint `#tag`, the tag truncates first) over `splitHandle` (`lib/player.ts`) — never `split("#")`; avatar `PlayerAvatar`; roster rows `RosterPlayer` / `RosterRole` / `RosterRank` (`TournamentTeamCard.tsx`) |
| Role / division marker     | `PlayerRoleIcon`; `DivisionIcon` (`tooltip` names the division); a crest from a rank or a division `RankCrest` (`components/RankCrest.tsx`)                                                                                                                                                          |
| Hero / map images          | `CatalogEntityImage` (`components/catalog/CatalogEntityImage.tsx`): hero faces square, map stills `shape="wide"` (4:3); initials when there is no image                                                                                                                                             |
| Group colour               | `groupHue(name)`, `groupIndex(name)`, `groupDisplayName(name, word)` (`lib/tournament/group.ts`)                                                                                                                                                                                                       |
| Media queries              | `useMediaQuery(query)` (`hooks/useMediaQuery.ts`), `usePrefersReducedMotion()` — never a hand-rolled `matchMedia` listener                                                                                                                                                                         |

### Controls

**Library controls only.** Native `<button>`, `<input>`, `<select>`,
`<textarea>` and `<img>` appear only inside `components/ui/*`. Feature code
uses the primitives below; when none fits, add a variant or a primitive to
`components/ui/` rather than hand-rolling one. `lint:design` (R8, R9)
enforces it; its few exemptions (OG renderer, user markdown, image capture,
the last-resort `global-error`) are listed in the script with their reason.

| Need                        | Use                                                                                                                     |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Filter chip                 | `FilterChip` in `FilterChipGroup` (`ui/filter-chip.tsx`), `accent` for a role-tinted chip                               |
| Filter + controls row       | `SectionToolbar` (tournament sections): chips at the start, search/sort/view at the end                                 |
| Search                      | `SearchField` (`ui/search-field.tsx`), `label` required                                                                 |
| Text / number / time field  | `ui/input.tsx`, `ui/number-input.tsx`, `ui/time-input.tsx`, `ui/textarea.tsx`; the public form skin is `variant="surface"` (also on `SelectTrigger` and `Checkbox`) |
| Labelled form field         | `FieldShell` (`components/forms/FieldShell.tsx`): label, help and error wired by id; `FieldError` / `FieldDescription` (`ui/field.tsx`) for a bare error or hint |
| Checkbox / switch / radio   | `ui/checkbox.tsx`, `ui/switch.tsx` (`size="sm"`), `ui/radio-group.tsx` (`RadioGroupItem variant="card"` for option cards) |
| Colour                      | `ui/color-swatch.tsx` — the one native `<input type="color">`; a blank value paints its fallback, dashed                |
| File                        | `FileButton` / `useFilePicker` (`ui/file-button.tsx`) — the one hidden `<input type="file">`                            |
| Select                      | `ui/select.tsx` — never a native `<select>`; its trigger, the `Combobox` trigger and the date picker share the outline surface and a chevron that turns while open (`triggerChevronClass` under a `group/trigger`) |
| Searchable picker           | `ui/combobox.tsx`; with images or multi-select `ui/searchable-image-select.tsx`; server search `kit/ServerSearchCombobox` |
| Floating panel              | `floatingPanelClass` (`ui/popover.tsx`), already on `PopoverContent`, `SelectContent`, `DropdownMenuContent`, `ContextMenuContent`, `TooltipContent`; a call site sets width and padding only |
| Panels of different content | `ui/tabs.tsx` (Radix), `TabsTrigger badge` for a count; `variant="rail"` for a vertical section list beside its panels (the account settings dialog: overlay fill + teal bar on the active row, 44px rows below `md`) |
| Tabs that are addresses     | `kit/LinkTabs.tsx` (`aria-current="page"`, `level={2}` for sub-tabs, `variant="pill"` for a segmented look)             |
| View/mode of the same data  | `ui/toggle-group.tsx` pill (`accent` per item; `variant="card"` for option cards); on tournament sections `ViewSegment` (`?view=` / `?tab=`, default never written to the URL) |
| Pagination                  | `ui/data-pagination.tsx` (`leading` slot for the range or rows-per-page)                                                |
| Data table                  | `components/data-table/DataTable.tsx`                                                                                   |
| URL state                   | `hooks/useQueryParams.ts`                                                                                               |
| Button                      | `ui/button.tsx`. Filled, semibold: `default` (teal, the screen's main action) · `destructive` · `positive` (check in). Tonal: `outline` (the everyday button, raised off any surface). Quiet: `ghost` · `ghost-destructive` (icon remove) · `link`. Tinted: `accent` (teal row action, and the chosen option of a choice, so picking never changes its shape). `dashed` (add one more). Sizes `default` · `sm` · `lg` · `xs` · `icon` · `icon-sm` (28px, icon beside text) · `icon-xs` · `inline` (a link in a sentence) · `label` (sortable header). Every button sinks on press (§10) |
| Row that is one action      | `RowButton` (`ui/row-button.tsx`): row hover, `aria-current="true"` selected fill, inset focus ring; the caller lays out |
| Dialog / sheet chrome       | `DialogContent` / `SheetContent` + their headers, `variant="panel"` for the edge-to-edge panel with a bordered header |
| Range                       | `ui/slider.tsx`, `accent` for a role-tinted track                                                                       |

### Status and data

| Need               | Use                                                                        |
| ------------------ | -------------------------------------------------------------------------- |
| Lifecycle status   | `TournamentStatusPill` (public), `kit/StatusPill` (admin)                  |
| Boolean state icon | `StatusIconBadge` (`components/status/StatusIconBadge.tsx`)                |
| Live / recency dot | `StatusDot` (`ui/status-dot.tsx`), always `aria-hidden`                    |
| Placement medal    | `PlaceBadge` (`ui/place-badge.tsx`, `--aqt-medal-*`); `size` `sm`/`md`/`lg` for the 28/36/44px squares, `null` draws "—" |
| Tinted label chip  | `Badge` (`ui/badge.tsx`): `tone` + `palette="aqt"` for `--aqt-*` hues, `voice="label"` for the uppercase data voice, `size="sm"` for dense tables |
| Eyebrow / uppercase label | `Eyebrow` / `eyebrowClass(tone)` (`ui/eyebrow.tsx`), tone `faint` (default) · `dim` · `muted` |
| W/L/D square       | `ResTag` (`components/match/cells.tsx`)                                    |
| MVP placement      | `MvpOrdinal` (`disciplines/overwatch/match/MvpOrdinal.tsx`): gold for 1st only |
| Platform totals    | `LeadersContent` (`components/site/leaders.tsx`) on `/` and the community page; `KpiFigure` from the same file for totals that sit beside another block (the `/get-workspace` community row); `HeroStat` figures in the `/statistics` hero (`statistics/_components/OverallFigures.tsx`) |
| Markdown           | `components/Markdown.tsx`; editing `components/admin/MarkdownEditor.tsx`   |
| Spinner (rare)     | `ui/spinner.tsx` — prefer a skeleton                                       |

## 7. Layout

- App container: `max-w-screen-3xl` (1720px), gutters `px-4 md:px-6 xl:px-10`.
- Breakpoints (`--breakpoint-*` in `globals.css`): `xs` 320, `xs1` 540,
  `sm` 640, `md` 768, `lg` 1024, `xl` 1280, `2xl` 1520, `3xl` 1720.
- Verify every change at **390, 768, 1024, 1440**. The page body never
  scrolls sideways; measure `document.documentElement.scrollWidth` against
  `innerWidth`, do not eyeball it.

### Grids

| Content                        | Grid                                                      |
| ------------------------------ | --------------------------------------------------------- |
| Group cards (rounds, days)     | `grid gap-3 lg:grid-cols-2 lg:items-start`                |
| Three parallel columns (roles) | `grid gap-3 lg:grid-cols-3 lg:items-start`                |
| Team cards                     | `grid gap-4 md:grid-cols-2 xl:grid-cols-3`                |
| Tournament cards               | `grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4` |
| Expandable list                | `space-y-2` of group cards                                |

Grids keep their shape while loading and on error: the skeleton draws the
same columns.

### Section shape (tournament sections)

`<section class={styles.publicDataPage} aria-label>` →
`UpdatingBadge` (refetching) → `SectionToolbar` (only if it has a choice) →
optional caption line (`EYEBROW` title + lede on **one** line) →
stage heading `h2/h3` (`text-ui font-semibold`) → grid of group cards.

### Responsive

- Multi-column grids collapse to one column below their breakpoint.
- A row that reads as a scoreboard on desktop restacks on phones from **one
  DOM** with `grid-template-areas` (`.matchRow` in
  `tournaments/[slug]/TournamentDetail.module.css`, `.mapRow` in
  `components/match/EncounterDetail.module.css`). Do not render two trees.
- Below `sm`, drop secondary columns (`hidden sm:block`): trailing text,
  thumbnails, bars when the number is shown, chips. Keep the number.
- A horizontal strip is allowed **inside** a row for items of one kind (map
  candidates, filter chips): `-mx-3.5 flex snap-x snap-mandatory
scroll-px-3.5 overflow-x-auto px-3.5`, the next item half visible.
- Touch targets: 44px for primary actions on mobile; small icon links grow
  their hit area with `-m-2 p-2 md:m-0 md:p-0` instead of growing the row.

## 8. Canonical patterns

Copy these from the reference implementations; they were built on this
system.

| Pattern                             | How                                                                                                                                                                                                                                              | Reference                                                                               |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| **Group card with header meta**     | `TournamentTeamCardFrame name={heading} metricValue={"Bo3 · 2 matches"}`; what every row shares is said in the header once                                                                                                                       | `_views/TournamentEncountersPage.tsx`, `tournamentMatches.model.ts` (`MatchBlock.meta`) |
| **Scoreboard row**                  | `home · score – score · away`, winner's score teal, loser's muted; stacked as a bracket node under 640px                                                                                                                                         | `tournaments/[slug]/_components/MatchRow.tsx`                                           |
| **Whole-row link**                  | in a div/grid row: an `absolute inset-0` link under the cells (or `after:absolute after:inset-0` on the name link); secondary links get `relative` to sit above it. In a `<table>`: link the name cell only — a `<tr>` is not a containing block | `MatchRow.tsx`; `tournaments/components/TournamentsTable.tsx`                           |
| **Expanding row**                   | native `<details>` + `summary list-none [&::-webkit-details-marker]:hidden`, `ChevronDown group-open:rotate-180`, focus ring inset; several can be open                                                                                          | `MatchRow.tsx`, `_views/_components/TeamListRow.tsx`                                    |
| **Leader-scaled bar**               | `h-1.5 rounded-full` track `--aqt-overlay-2`, fill = value / leader, exact value printed beside it; `role="progressbar"` with `aria-valuetext`                                                                                                   | `_views/TournamentStatsPage.tsx` (`getHeroPlaytimeMetric`)                              |
| **Ranked column**                   | zero-padded rank (`01`) in `text-label text-[color:var(--aqt-fg-faint)]`, icon, name, value right-aligned `.aqt-tnum`                                                                                                                            | `TournamentStatsPage.tsx`                                                               |
| **Header with board + facts**       | crumbs and actions → board (team · display score · team) → pills (≤2 states) + `<dl>` facts; an `sr-only` `h1` names the matchup; a fact with no data is omitted, not dashed                                                                     | `encounters/[id]/components/EncounterHeader.tsx`                                        |
| **Tabs only with content**          | build the tab list from what has data; one tab → no tab bar; first tab is the bare URL                                                                                                                                                           | `encounters/[id]/page.tsx`                                                              |
| **Collapsed empties**               | unplayed slots become one line ("2 more maps not played"), not a ghost row each                                                                                                                                                                  | `encounters/[id]/page.tsx` (`mapRowNote`)                                               |
| **Card that drops what is obvious** | a finished tournament card shows no status pill and no progress bar                                                                                                                                                                              | `tournaments/components/TournamentCard.tsx`                                             |
| **Search highlight**                | `<mark className={MARK_CLASS}>` on the matched token                                                                                                                                                                                             | `_views/tournamentTeams.model.ts`                                                       |
| **Inline roster**                   | role glyph + nick, captain crown, in one truncating caption line                                                                                                                                                                                 | `TeamListRow.tsx`                                                                       |
| **Add at the list's foot**          | a `<form>` row closing the list it adds to: `Plus` glyph, borderless input, outline Add; Enter submits, the field clears and keeps focus; what the list already fixes (game, parent) is never asked; a refusal shows under the field             | `admin/settings/sub-roles/page.tsx` (`AddSubRole`)                                      |
| **Event overview**                  | hero: name → status pill under it → ONE phase fact (`HeroPhaseFact`: the next boundary, or the stage being played) with one caption line, counts only once the field is set; then a full-width lead (timeline before the start, now-playing while live, podium after) → `OverviewColumns` 2:1, the phase's story left and a reference stack right split by hairlines; sections open (`OverviewSection`: `text-title`, `text-heading` in the narrow column), only dense blocks framed | `tournaments/[slug]/_views/_components/OverviewCards.tsx`, `OverviewRegistrationView.tsx` |
| **Timeline with a "now"**           | the phase the tournament is in is always a step, scheduled or not (no time → "Now"); teal marks that step only; the countdown lives in the hero, never repeated on the step                                                                     | `_views/tournamentSchedule.model.ts`, `_components/PhaseTimeline.tsx`                   |

## 9. States

- **Skeleton first.** The skeleton draws the final layout (same grid, same
  rows) so nothing reflows when data lands.
- **Three states, always.** `empty` (nothing exists), `error` (could not load)
  and `filtered-empty` (filters exclude everything, always with a reset). A
  query that can fail destructures `isError`; showing `empty` on failure is a
  lie.
- A background refetch shows `UpdatingBadge`; a failed refetch keeps the stale
  content and shows the error above it.
- Copy defaults come from `common.pageState.*`; override only when the page
  can say something more specific.

## 10. Motion

- Transitions: colour, border, opacity, `transform` for a chevron. ~150ms.
- A floating panel fades in and out (~150ms): no zoom, no slide.
- No entrance animations, no staggered reveals, no perpetual loops — except
  the live pulse (`StatusDot pulse`, `.livePulse`) on something that is live,
  and the settings page change through `kit/SettingsContinuation` (the old
  page lifts away in 180ms, the new one rises from where its ghost was in
  320ms; reversed going back), which says which way the reader went. A pick
  in `kit/SectionNav` plays the same 320ms entrance on the content column,
  from below for a section under the open one, from above for one over it.
- The mix match room (`app/balancer/mix/_room`) moves what the server moved,
  through view transitions: a drafted player flies from the pool into their
  slot, a banned or picked hero from the grid into its team's ban row or
  beside its player, and the centre hands over to the next phase (the old
  one lifts away in 180ms, the new one rises in 320ms). Only named elements
  animate; the page itself is never captured, so it stays clickable.
  Going in from the mix page, the lobby's card (its desk, while open) grows
  into the room in 320ms and a player on the desk flies to their side;
  "Back to the mix" shrinks the room back into it in 260ms, and the pages
  crossfade. The browser's own back is not animated.
- No hover that changes size or shifts layout.
- The one press: every `Button` sinks 1px while pressed
  (`active:[transform:translateY(1px)]`, `motion-safe` only), the same on every
  width, and adding to a centring `-translate-y-1/2` rather than replacing it;
  the `inline` and `label` sizes, which are text, do not.
- `prefers-reduced-motion` mutes all of it; the static cue (colour, border,
  word) always remains.

## 11. Content and data honesty

- **Numbers and dates** go through next-intl (`useFormatter()`,
  `getFormatter()` on the server). Never `Intl.NumberFormat("en-US")` or
  `toLocaleDateString("en-US")`: the default locale is `ru`.
- **Dates**: relative (`2d ago`) with the absolute date in `title`.
- **Low-sample gate**: percentiles and vs-average comparisons hide below 10
  games (`LOW_SAMPLE_GAMES`): an em dash, the rule in `title`.
- **No invented data**: no SR/MMR where the system has none, no fabricated
  per-hero stats, no "seasons" — tournaments only.
- **Encounter ⊃ matches**: an encounter is the series (3–1), its matches are
  maps. Never label an encounter with one map's name. A parsed log's score is
  oriented to the encounter's sides (`encounterSideScore` in
  `lib/encounter/detail.ts`) before it is shown or compared.
- **Mix tournaments**: a player has no permanent team.
- **Truncation**: `truncate` plus the full value in `title`.
- **Roles**: icon only in rows and tables (name in `title`/`aria-label`); icon
  - word only in a role split; text only in a meta line. Divisions: icon only,
    name in `title`.
- **Hero avatar sizes**: 30px stacks, 24px compact rows, 26px in tables, 32px
  single, 56px as the identity of a hero hover card (`CharacterCard`).
- **No encoding captions** ("bar = …", "lower is better"): if the encoding
  needs a caption, change the encoding.
- One term per metric (Closeness, not Proximity).

## 12. Accessibility floor

- Visible `:focus-visible` on everything interactive (2px teal, inset inside
  rows and cards).
- Every icon-only control has an accessible name; decorative icons are
  `aria-hidden`.
- No emoji or bare glyphs (`←`, `✓`, `×`) as icons — `lucide-react` with
  `aria-hidden` (lint rule R5).
- No `<div onClick>` / `<span role="button">`: a link is `<a>`, an action is
  `<button>` (lint rule R7).
- Every hover popover also opens on focus and tap.
- `--aqt-fg-faint` is the minimum text colour on `--aqt-bg`; 12px is the
  minimum size for anything meant to be read.
- A wide table gets its own labelled `overflow-x-auto` region (`tabIndex={0}`),
  never `overflow: hidden`.
- Verify names with the browser's accessibility tree, not by reading JSX.

## 13. Public marketing pages

`/` and `/get-workspace` keep the dark theme and teal accent. `SectionStack` is
contained at `max-w-7xl` with responsive 56–96px section gaps. `HeroFrame
variant="plain"` uses `--aqt-bg-2` without the accent hairline or corner glow;
the home hero adds a near-black `135deg` gradient from `--aqt-bg-2` to
`--aqt-bg` inside the same 1px frame.

`/` is the platform's portal, in this order: hero, the "now" block, the
community directory, platform totals, the organizer banner. It shows no product
screenshots: those sell to organizers on `/get-workspace`. With nothing active
(an announcement or an open registration counts as active) the "now" block is
titled "Recent tournaments" and its cards drop the status pill, which would say
"finished" on every one.

The directory is a static grid of every public community: four across from
1100px, two from 640px, below that one row per community with its totals at
the row's end. It closes with a dashed "Your community here" cell linking to
`/get-workspace`. `#directory` is its anchor, the footer's "Communities" link.

`/get-workspace`, in order: the hero with the community form, the community row
(verified communities beside two platform totals; absent when its reads fail),
the feature tour (one screenshot window under `ui/tabs.tsx` tabs, then a grid of
what the tabs do not show), the custom-domain walk-through, the facts strip,
the FAQ, the closing CTA. Screenshots are real production captures under
`public/showcase/`, one window ratio on every tab so switching never moves the
page, the bottom fading from 75%. `OrganizerQuotes` is built and not mounted:
it goes under the community row once there are real quotes with names.

The community form keeps its name/slug contract: the host and `/workspace/`
prefix sit in a wrapping URL preview below the slug input. What was typed
before "sign in and create" survives the OAuth round trip in `sessionStorage`.
Inputs use 16px text, 48px shells, visible focus/invalid states. Repeated
section eyebrows are omitted.

Share cards: `lib/og/landing.tsx` draws both. `/` names its `og` route from the
apex metadata only, since an `opengraph-image` file would also cover every
community host's `/`; `/get-workspace` names its own `og` route.

## 14. Admin kit

`/admin` is one product with one shape. Every screen is an instance of exactly
one of seven templates, assembled from `components/kit/*`,
`components/data-table/*` and `components/ui/*`. Pages do not write layout or
colour of their own. A screen that needs a shape no template has is a sign
the IA is wrong — say so before inventing a surface.

| #   | Template      | Structure                                                                                                                                | Used by                                                                                                                           |
| --- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| T1  | Dashboard     | greeting → two columns from the top: "work" (a card per tournament in work, with its phase body and next action; next 7 days; trends; backlog; platform health) / "attention" (to do, activity) | `/admin`                                                                                                                          |
| T2  | Browser       | header → filter bar (search + chips) → table with an always-visible kebab → Inspector (`?id=`) with "Open page" when the row has a route | Tournaments, People, Teams, Matches, Achievements, Members, `content/*`, `access/*`, Audit, hub Registration entries, hub Matches |
| T3  | Hub           | entity header (name, status, metrics, 1–2 actions) → routed tabs → optional routed sub-tabs → body; a person, team or achievement body is a stack of `SettingGroup` cards, as on T5 (the tournament hub's tabs are templates of their own) | tournament hub, `people/[id]`, `teams/[id]`, `achievements/[id]`                                                                  |
| T4  | Master-detail | sortable list left (`+ Add`) → editor right; destructive actions in a menu, one parameterised confirm                                    | bracket stages, pre-game phase scopes, access roles; Divisions draft editor (full-screen variant)                                 |
| T5  | Settings      | sticky section nav left → page header (h1, one-line description, actions) → routed tabs when a page groups sections → a stack of `SettingGroup` cards → sticky save bar while dirty | `/admin/settings/*`, tournament `settings/*`, `workspaces/[id]/*`, collector settings                                             |
| T6  | Wizard        | step rail → step body → footer (Back · Save draft · Continue)                                                                            | new workspace, new tournament, draft setup, divisions import, Challonge sync                                                      |
| T7  | Control room  | status hero (phase, timer, connection) → current action + lifecycle buttons → right column (presence, feasibility)                       | live draft                                                                                                                        |

Rules on every admin screen:

- **Row detail has one answer per case.** Up to ~6 editable fields →
  `EntityFormDialog`. Read-only investigation → `Inspector`. Editable _and_
  shareable → its own route. T2 defaults to the Inspector.
- **One filter surface.** `FilterBar` above the table; nothing in the header,
  no `<Select>` in the toolbar. The one filter a page's actions depend on (the
  game on a per-game page) is an `inline` def: a visible select in the bar,
  not a "+ Filter" entry.
- **One tab look.** Routed tabs are `LinkTabs`; non-address tabs are
  `ui/tabs.tsx`; a view switch is a `ToggleGroup`, never a hand-rolled
  `<nav>` of pills.
- **One row-actions convention.** `createKebabColumn`
  (`data-table/kebab-column.tsx`); the menu is always visible. The one or two
  actions a reader uses on most rows (change a slot, reorder, "only this
  actor") stay inline as labelled or titled buttons; rare and destructive
  ones go in the menu, or, where the row opens an `EntityFormDialog`, at its
  footer's start (`footerStart`: switch off, delete). A list that already
  separates on and off rows (active above, the rest folded) puts no switch
  on each row: the place says the state, the fold offers "Restore".
- **One command zone.** A command over a list — create, sync, upload, open a
  tool — is a `TableCommand` in that table's `commands`: outline buttons, the
  one `primary` last; on a narrow table the secondary ones fold into the
  table's "View" menu and the primary keeps its icon. Never JSX in the
  toolbar, never in the `FilterBar` (filters only: its `extraFilters` are
  range pickers and filter shortcuts), never in the page header. A table that
  is a `SettingGroup flush` body keeps its commands on the card's title line;
  a view switch that swaps the table for another view sits above both. How
  the rows are shown (CSV, density, grouping, saved views, columns) is the
  "View" menu's; a total or an average is the table's `summary`, at its foot.
- **Permission hides, state disables.** An action the reader may _never_
  perform (no grant) is absent. An action they may perform once something
  else is true (pick a tournament, a game, resolve the blockers, finish the
  draft) is shown disabled with the reason as visible text beside it, not
  only in a tooltip.
- **Header actions.** A hub header leads with the next step as its primary
  button (`→ Live`), then a menu for the rest. A menu groups what differs in
  kind or risk (allowed vs forced transitions, a flag vs a status) under
  labels; it never lists them as one flat run.
- **At most three dialogs per screen**: `EntityFormDialog`, one
  `ConfirmDialog` with a swapped `intent`, at most one domain dialog.
- **All three page states**, through `PageStateCard`; the first load is a
  skeleton, never the empty state.
- **State lives in the URL** (`useQueryParams` / `kit/useFilters.ts`). Depth
  stays at three: sidebar → screen → (sub-tab | inspector).
- **Chips in admin follow §4 exactly.** A lifecycle state that needs
  attention → `kit/StatusPill`; the default or finished state of a row
  (active, verified, published, done, processed, completed, accepted,
  connected, monitoring) renders _nothing_, because on a list where most rows
  are in that state the absence of a pill says it. One pill per row, in the
  status column only. A boolean → `StatusIcon`, shown for the exception, not
  the norm. A category (role, kind, scope, provider, format, type, mode,
  class, direction) is plain text; a count beside a heading is plain text; an
  id is plain text. `Badge` is not an admin primitive: the only chip that is
  not a status is a chosen entity shown as a removable `FilterChip`.
- **No metric strip above a table.** `StatTile` lives on the dashboard (T1)
  and on a collector's health page. A count that restates the table below, a
  filter chip's count or a checklist row is said once, there.
- **A fact is shown once per screen.** The hub header carries the status;
  the body does not repeat it in a pill, a `Select` value, a strip and a
  checklist row. An inspector repeats nothing the row already shows.
- **Helper copy earns its line.** No `description` under a heading that
  restates the heading or lists the tabs below it; no placeholder equal to its
  label; no "Yes/No" for a boolean; no `—` or `-` for a missing value (render
  nothing); no raw API enum on screen.

| Component                                    | Owns                                                           |
| -------------------------------------------- | -------------------------------------------------------------- |
| `kit/LinkTabs.tsx`                           | routed tabs and sub-tabs                                       |
| `kit/FilterBar.tsx` + `kit/useFilters.ts`    | the filter surface and its URL state                           |
| `kit/Inspector.tsx`                          | row detail: right panel at `lg`+, a sheet below                |
| `kit/InspectorField.tsx`                     | a labelled fact and a titled group inside an inspector or detail dialog; no local `Field` copies |
| `kit/ConfirmDialog.tsx`                      | every confirmation                                             |
| `kit/SectionNav.tsx`                         | T5 navigation (sticky `<nav>` at `lg`+, `Select` below); a rail item is a page, small related sections are its `LinkTabs`, never extra rail items. Under the active item it lists the open page's groups (`kit/SettingsOutline.tsx`, mounted by the T5 shells) once there are three or more: `#id` links, scroll-spy highlight, a fragment URL lands on its group |
| `kit/SettingRow.tsx`                         | T5 and T3 bodies: `SettingGroup` is one card per group, with a stable locale-free `id` (its anchor and outline entry; `immediate` when its controls act without the save bar), a `summary` count or verdict beside the title, its own `actions` at the end of the title line, and `flush` for a body that runs edge to edge (a table with its own toolbar and rules); a body that renders nothing leaves the header alone. `SettingRow` is label + hint left, control right once the group is `@xl` (36rem) wide. Text a reader types (names, links, domains) and long text are `stacked`; switches, selects and radios stay two-column. `error` renders under the control with an icon (pair it with `invalidProps` on the control); `count` puts a `value / max` counter on the label line, `soft` for advice rather than a cap. A switch points `aria-describedby` at `settingHintId(id)`. `level` lowers the group heading where a dialog title and a section heading sit above it (the account settings dialog uses `4`; its sections are these groups too). Never wrap a group in another `Card` |
| `workspace-settings/WorkspaceSettingsShell.tsx` | the workspace hub's header and tabs; `SettingsHeaderActions` puts a section's page-level controls (audit trail, discipline picker) beside the h1. Forms are capped at `max-w-3xl`, tables and list/detail pages take the column |
| `kit/SaveBar.tsx` + `kit/useUnsavedGuard.ts` | dirty-form save/discard and the leave guard. A refused or failed save is the bar's `error`, never a toast (a toast covers the bar's own Discard). `useScopedSettingsForm` `validate` gives field errors, shown once the reader leaves the field or tries to save; a 422's per-field reasons land on the same fields |
| `kit/SettingsContinuation.tsx`               | a T5 page between its neighbours. Below it the next page's ghost: its real render, inert and faded, under a "Next" link; scrolling on past the end fills a bar and opens it at its top. Scrolling up past the top fills a pill naming the previous page and opens it at its end (wheel and keys only: a downward swipe at the top is the browser's pull-to-refresh). Both off while unsaved and under reduced motion; a wheel gesture that opened a page does not carry into the next. Inside the ghost `useInSettingsPreview()` is true: groups stay out of the outline, header actions, page headers and polling stay off. Chains: workspace hub Overview → General → Branding → Visibility → Domain → Discord; tournament settings run through the form sections the caller may open, in rail order, skipping the editors (pre-game, report form, links) and Danger zone |
| `kit/WizardShell.tsx`                        | T6 frame                                                       |
| `kit/EntityHubHeader.tsx`                    | T3 header (back link, `leading` avatar/logo, title, status pill, middot-joined metrics, actions) |
| `kit/PhaseStrip.tsx`                         | lifecycle position, indicator only; `variant="compact"`: unlabelled segments on a card whose heading already names the phase (each name in `title` and for screen readers) |
| `kit/MasterDetail.tsx`                       | T4 split with the narrow-viewport switch; `MasterList` / `MasterListSkeleton` for the plain list column |
| `kit/NextActionHero.tsx`                     | the single "do this next" on the hub Overview                  |
| `admin/PermissionGate.tsx`                   | a page's permission gate: skeleton while permissions load, "No access" `PageStateCard` when refused |
| `admin/AdminTabbedPage.tsx`                  | T2 page header plus level-1 `LinkTabs` for a tabbed admin section |
| `tournaments/[id]/sub-tabs.tsx`              | hub sub-tabs: `useSubTabSegment` (active segment from the path), `SubTabShell`, `useTabAccess` |
| `kit/FactList.tsx`                           | a `<dl>` strip of labelled facts in a header or summary          |
| `kit/ServerSearchCombobox.tsx`               | pickers over a server search (`UserSearchCombobox`, `AuthUserSearchCombobox`) |
| `ui/tone.ts`                                 | `Tone`, `TONE_CLASS` / `TONE_TEXT` tint recipes                |
| `admin/AdminDetailTable.tsx`                 | styling for a dense table inside an editor, not a browser      |

## 15. Never

- A chip outside the four jobs in §4, more than two in a header, or one that
  repeats nearby text.
- The same fact twice in one view (title and row, score and "Winner" pill,
  `#1` and "1st place").
- A card inside a card; a tinted callout or coloured left border inside a
  card.
- A control with no choice (one filter, one tab, one view). Table utilities
  are not choices about the data and always stay: saved Views, rows per page,
  CSV (disabled while there is nothing to export).
- A state-gated action that vanishes: it is disabled with a visible reason
  (see "Permission hides, state disables" in §14).
- A banner's action dropped as "a repeated fact": "Draft live → Open draft
  board", "N failed → Show failed" are the shortest path to the work, not a
  restatement.
- Raw hex, Tailwind neutrals, `text-[Npx]`, a font size below 12px, a
  tracking other than `tracking-label` on uppercase text.
- A `text-*`, `font-*` or height override on a control (§3, Control text).
- A fill, border, radius or shadow on a select trigger or a floating panel at
  the call site; the primitive owns the surface.
- Uppercase user content; `font-mono` on UI labels.
- A "finished/completed" status pill on a list of mostly finished items.
- Colour as decoration: gradient text, decorative glows, the role spectrum as
  a background.
- Emoji or glyphs as icons; `<div onClick>`; a native `<button>`, `<input>`,
  `<select>` or `<textarea>` outside `components/ui/`.
- Hover that scales or shifts layout; entrance animations; perpetual loops
  on anything that is not live.
- A button filled darker than the surface it sits on (`bg-background` on a
  card or a dialog).
- A spinner where a skeleton fits; `empty` shown for a failed load.
- Hand-rolling a primitive listed in §6.

## 16. Before you open a PR

- [ ] Every chip on the screen maps to one of the four jobs in §4.
- [ ] No fact appears twice in one view.
- [ ] Every control offers a real choice.
- [ ] Tokens only; type roles only; `bun run lint:design` passes (it also
      fails a native control or `<img>` outside `components/ui/`).
- [ ] Skeleton matches the layout; `empty`, `error`, `filtered-empty` all
      render.
- [ ] Checked at 390 / 768 / 1024 / 1440; no horizontal page scroll.
- [ ] Everything interactive has hover, visible focus and an accessible name.
- [ ] Reused the §6 primitives; nothing hand-rolled that already exists.
- [ ] No native control outside `components/ui/`; no font or height override
      on a control.
