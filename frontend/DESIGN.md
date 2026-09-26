# AQT: Design Approach

This document describes the UI/UX principles used in AQT (Anak tournament statistics) and acts as the reference when adding new pages and components.

Anchor pages that define the product's visual language:

- `frontend/src/app/(site)/(home)/page.tsx` - Dashboard home: modular analytics, stable grids, predictable states.
- `frontend/src/app/(site)/users/[slug]/page.tsx` - User profile: a richer hero header.
- `frontend/src/app/(site)/tournaments/page.tsx` - List page: hero + filters + one scrollable table.

**Related references:**

- Interactive Design Book (site, real `--aqt-*` tokens, verified/specified/divergences): [`/docs/design-book.html`](public/docs/design-book.html)
- Design Book source spec (Russian, tokens/type/roles/content/patterns): [`../docs/design-book.md`](../docs/design-book.md)

## TL;DR

- Data-first UI: every screen answers a concrete question.
- Card-first layout: `Card` is the default container for blocks.
- States over effects: skeleton-first loading, clear error/empty states, minimal layout shift.
- Dark theme by default; colors come from tokens (CSS variables), not ad-hoc hex values.
- Liquid Glass is used selectively (profiles), not as a global style.

## Why this approach

AQT is an analytics product. Users typically want to:

- understand the overall picture quickly (home dashboard)
- drill down from metrics into details (charts/tables -> tournaments/matches)
- evaluate a specific player (user profile)

Design priorities follow those goals:

- readability of numbers, tables, and charts
- predictable navigation and layout
- minimal decoration where it would compete with data

## Foundations: tokens, theme, typography

### Theme and tokens

- Tokens live in `frontend/src/app/globals.css` (CSS variables for background/foreground/card/border/etc).
- Tailwind maps to those tokens in the same file: there is no `tailwind.config.ts`. Tailwind 4 is configured CSS-first, with `@theme` (breakpoints, fonts, animations) and `@theme inline` (colours, radii) at the top of `globals.css`.
- `globals.css` holds only tokens, base rules and app-wide primitives. Feature stylesheets sit next to the code that renders them and are imported from there: `app/(site)/tournaments/tournaments.css` (`.aqt-tn`), `app/(site)/achievements/achievements.css` (`.aqt-ach-*`, `.aqt-rar-*`), `app/(site)/users/user-profile.css`, `components/TournamentTeamCard.css`, `components/EncountersTable.css` (`.aqt-matches`), `components/data-table/data-table.css` (`.admin-*`).
- Dark theme is enabled by default (class `dark` on body) in `frontend/src/app/layout.tsx`.

Principle: components should rely on semantic tokens (`bg-background`, `bg-card`, `text-muted-foreground`, `border-border`, ...) instead of inventing new colors.

Two token families coexist and must not be confused:

- shadcn tokens (`--background`, `--card`, `--border`, ...) hold bare **HSL
  triplets**, because Tailwind wraps them as `hsl(var(--card))`.
- `--aqt-*` tokens hold **complete colors** (`hsl(220 22% 8%)`), used directly.

Never redefine a shadcn token name inside a scoped block. A rule like
`.my-scope { --card: var(--aqt-card) }` makes `hsl(var(--card))` resolve to
`hsl(hsl(...))`, which is invalid — every shadcn surface inside that scope
silently renders transparent with a `currentColor` border. Scoped aliases must
use their own prefix (`--tn-card`, `--u-fg`, ...).

Never use raw hex, `white/N`, `slate-*` or `zinc-*`: workspace theming
(`WorkspaceThemeSync`) cannot reach them, so white-label tenants render
half-themed. Arbitrary Tailwind color values need the `color:` hint —
`text-[color:var(--aqt-fg)]`, never `text-[var(--aqt-fg)]`, which is ambiguous
with `font-size` in Tailwind v4.

### Typography

- Two faces, both self-hosted via `next/font/local` in `frontend/src/app/layout.tsx` (not `next/font/google` — that fetches from `fonts.gstatic.com` at build time and a production build once died on rotated hashes): **Inter** for everything textual, including the data/label voice (`--aqt-data`, `.aqt-tnum` = Inter + `tabular-nums`), and **Onest** for display titles (`--aqt-display`, `font-display`). JetBrains Mono was retired: `font-mono` is now Tailwind's system monospace and is reserved for code and identifiers (API keys, usernames, log output), never for UI labels.
- **Type roles are the only sizes.** Defined once in `globals.css` (`@theme static`); each carries size + line-height (+ tracking where relevant), weight stays explicit:

  | Utility | CSS var | Size / lh | Use |
  | --- | --- | --- | --- |
  | `text-label` | `--text-label` | 12 / 1.25 | eyebrows, table heads, chips, counters — pair with `uppercase tracking-label` |
  | `text-caption` | `--text-caption` | 13 / 1.4 | secondary text, table cells |
  | `text-body` | `--text-body` | 14 / 1.5 | body copy, ledes |
  | `text-ui` | `--text-ui` | 15 / 1.5 | list rows, primary values |
  | `text-heading` | `--text-heading` | 18 / 1.3 | card / section sub-headings |
  | `text-title` | `--text-title` | 22 / 1.15 / −0.01em | section `h2` — mixed-case, never uppercase |
  | `text-headline` | `--text-headline` | 30 / 1.1 / −0.02em | compact hero titles |
  | `text-display` | `--text-display` | clamp(32–56) / 1.03 / −0.01em | page-hero `h1` |

  `tracking-label` (`--tracking-label`, 0.08em) is the single tracking for uppercase labels. Never write `text-[Npx]` or `font-size: 11px` again — if a role is missing, add it to the `@theme` block. `scripts/check-design-compliance.mjs` R6 still enforces the 11px floor.
- `cn()` (`lib/utils.ts`) extends tailwind-merge with these role names; without that, `text-label` is filed under text-_color_ and a later `text-[color:…]` deletes it. Also note tailwind-merge drops `leading-*` when a font-size utility follows it in a later `cn()` argument — put line-height in the role token, not beside it.
- Use `tabular-nums` (or `.aqt-tnum`) for metrics where stable alignment matters.
  Examples: `frontend/src/components/StatisticsCard.tsx`, `frontend/src/app/(site)/users/components/header/UserHeader.tsx`.

**The `:root`-vs-`<html>` font trap.** The `.variable` classes from `next/font/local` MUST mount on `<html>`, not `<body>`: `globals.css` aliases them from `:root` (`--aqt-data`, `--aqt-display`), and a custom property is substituted where it is _declared_ — an alias on `:root` cannot read a variable defined one level down on `<body>`. It silently resolves to nothing (and poisons the whole declaration, so the literal fallback next to it doesn't apply either), so every `--aqt-display` surface falls back to plain Inter with no error. If you ever re-alias a `next/font` variable in a scoped `:root`, mount its class at or above that scope.

## Core building blocks

### Card as the standard container

Cards are the default pattern for content blocks:

- consistent radius/border/shadow
- consistent structure: header -> content -> footer

Implementation: `frontend/src/components/ui/card.tsx`.

Important: `Card` sets `data-ui="card"`. This is used for theming (notably Liquid Glass). Do not remove or rename this attribute.

### Shared primitives — use these, do not re-roll them

Every one of these replaced three to six hand-rolled copies. Reach for them
before writing markup:

| Need                        | Use                                                                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Filter chip                 | `components/ui/filter-chip.tsx` — `<FilterChip active count>` inside `<FilterChipGroup label>`                                                                           |
| Search input                | `components/ui/search-field.tsx` — `label` is required (a placeholder is not a label)                                                                                    |
| Pagination                  | `components/ui/data-pagination.tsx` — windowed, `aria-current`, real chevrons                                                                                            |
| Empty / error / not-found   | `components/ui/page-state-card.tsx`                                                                                                                                      |
| Data table                  | `components/data-table/AdminDataTable.tsx` — header scope, scroll region, skeletons, keyboard rows                                                                        |
| Placement medal             | `components/ui/place-badge.tsx` — `--aqt-medal-*` tokens                                                                                                                 |
| Role / division marker      | `components/PlayerRoleIcon.tsx`, `components/DivisionIcon.tsx` — icon+label only in a Role split; icon-only (name in `title`/`aria-label`) elsewhere on display surfaces |
| MVP pill                    | `components/match/MvpMatchPill.tsx`                                                                                                                                      |
| Status dot                  | `components/ui/status-dot.tsx` — `<StatusDot tone pulse>`; always `aria-hidden`, fill is `currentColor`, so a hue with no `Tone` is set with `className`/`style`, not a new tone      |
| Lifecycle status pill       | `components/tournaments/StatusPill.tsx` — `<TournamentStatusPill status>` for tournaments, encounters and streams; `live` carries the pulsing dot on its own, the label is always the caller's copy |
| Loading spinner             | `components/ui/spinner.tsx` — `<Spinner className label>`; decorative by default, `label` only where nothing else says "loading"                                           |
| Hero avatar / stack         | `components/hero/HeroImage.tsx` (`HeroStrip` for the collapsing stack)                                                                                                   |
| Platform totals             | `components/stats/PlatformStatsGrid.tsx`                                                                                                                                 |
| Filter/sort/page in the URL | `hooks/useQueryParams.ts`                                                                                                                                                |
| Author-written Markdown     | `components/Markdown.tsx` — renders to React elements, so raw HTML is inert and no sanitizer is involved; `MARKDOWN_REMARK_PLUGINS` is the one plugin set (GFM)                     |
| Markdown editing            | `components/admin/MarkdownEditor.tsx` — `@uiw/react-md-editor`, loaded client-side on demand, its preview pane wired to `Markdown` so it cannot disagree with the published page    |

### Tabs, Button, and other primitives

- Tabs: one look, three jobs — pick by what the control does, never restyle it per call site:

  | Job | Use |
  | --- | --- |
  | Switch between panels of different content (state-driven) | `components/ui/tabs.tsx` — Radix `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent`, `role=tab/tabpanel`, arrow keys. `TabsTrigger` takes `badge` (a count) and `dot` (`{ tone, label }`). Sync to `?tab=` with `useQueryParams` when it should survive a reload. |
  | Switch between routes (each tab is an address) | `components/kit/LinkTabs.tsx` — real links with `aria-current="page"`, `level={2}` for a sub-tab row. |
  | Switch the view/mode of the same data (list/table, simple/extended) | `components/ui/toggle-group.tsx` pill (`SegmentedLinks` when each mode is a URL). A mode switch that also owns panels is `<TabsList variant="pill">`. |

  Both tab forms draw from the same classes (`tabsListVariants`/`tabsTriggerVariants` in `ui/tabs.tsx`): an underline row on a hairline, horizontal scroll when narrow, the active tab kept in view. A `className` on `TabsList`/`TabsTrigger` is for layout only (`w-auto`, `flex-1`, a mobile `min-h-11`), never colour, radius or background. A `role="tablist"` written by hand is a bug.
- Buttons: `frontend/src/components/ui/button.tsx` (CVA) with focus/disabled states. `static={false}` opts a control into a reduced-motion-safe `scale(0.96)` press; the default is no press motion.

Principle: any new primitive must preserve:

- visible focus states
- reasonable touch targets (typically 36px+ height, 44px+ for primary actions on mobile)
- predictable hover/active behavior

## Admin kit

`/admin` is one product with one shape. Every screen there is an instance of
exactly one of seven templates, assembled from `components/admin/kit/*` plus
`components/ui/*` — pages do not write layout or colour of their own, because
the kit is where the visual language above is applied once.

If you are adding an admin screen: pick the template first, then reach only
for the components below. A screen that needs a shape no template has is a
sign the IA is wrong, not that the kit is missing something — say so before
inventing a surface.

### The seven templates

| #   | Template      | Structure                                                                                                                                   | Where it is used                                                                                                                                                   |
| --- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| T1  | Dashboard     | Greeting + one next action -> KPI strip -> two columns: "work" / "attention"                                                                | `/admin`                                                                                                                                                           |
| T2  | Browser       | Header -> filter bar (search + chips) -> table with an always-visible kebab -> Inspector (`?id=`) with "Open page" when the row has a route | Tournaments, People, Teams, Matches, Achievements, Members, `content/*`, `access/*` lists, Audit, hub Registration entries, hub Matches views                      |
| T3  | Hub           | Entity header (name, status, metrics, 1–2 actions) -> routed tabs -> optional routed sub-tabs -> body                                       | Tournament hub, `people/[id]`, `teams/[id]`, `achievements/[id]`                                                                                                   |
| T4  | Master-detail | Sortable list left (`+ Add`) -> editor right; destructive actions in a menu, one parameterised confirm                                      | `kit/MasterDetail`: Bracket stages, Pre-game phase scopes, Access roles. The Divisions draft editor is the full-screen variant — a ladder column instead of a list |
| T5  | Settings      | Vertical section nav left -> the section's form -> sticky save bar while dirty                                                              | `/admin/settings/*`, tournament `settings/*`, `workspaces/[id]/*`, collector settings                                                                              |
| T6  | Wizard        | Step rail -> step body -> footer (Back · Save draft · Continue)                                                                             | New tournament, Draft setup, Divisions import, Challonge sync                                                                                                      |
| T7  | Control room  | Status hero (phase, timer, connection) -> current action + lifecycle buttons -> right column (presence, feasibility)                        | Draft live (`tournaments/[id]/teams/draft` once the draft is running)                                                                                              |

### Rules that hold on every admin screen

- **Row detail has one answer per case.** Up to ~6 editable fields -> `EntityFormDialog`. Read-only investigation -> `Inspector`. An entity that is editable _and_ shareable -> its own route. The default for T2 is the Inspector.
- **One filter surface.** `FilterBar` above the table, nothing in the header and no `<Select>` in the toolbar. A column may still declare `meta.filter` — that is the endpoint/param contract the table applies, not a second control.
- **One tab look.** A routed tab row is `LinkTabs` (`level={2}` for sub-tabs) — not Radix `Tabs`, whose `role=tab` is wrong for a link and whose roving tabindex fights a nested row. Tabs that are not addresses (locales inside a form dialog) are `ui/tabs.tsx`. Both render the same underline; a view switch is a `ToggleGroup`, never a hand-rolled pill `<nav>`.
- **One row-actions convention.** `createKebabColumn`. An action the reader may not perform is _absent_, never disabled — and the menu is always visible, never revealed on hover.
- **At most three dialogs per screen**: create/edit (`EntityFormDialog`), one `ConfirmDialog` whose `intent` is swapped per operation, and at most one domain-specific dialog. Six copies of the same confirmation differing only in strings is the anti-pattern this replaced.
- **All three page states, always.** `PageStateCard` for `empty`, `error` and `filtered-empty`; a query that can fail MUST destructure `isError`.
- **State lives in the URL.** Tab, view, filters and the open Inspector row go through `hooks/useQueryParams.ts`, so a link pasted into Discord opens the same screen. Depth stays at three: sidebar -> screen -> (sub-tab | inspector); anything deeper becomes a route or a wizard.

### What each kit component owns

| Component                 | The job it owns                                                                                                                                                                          |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kit/LinkTabs.tsx`       | Routed tabs and sub-tabs: `next/link` items, `aria-current="page"`, arrow-key movement, horizontal scroll when narrow; styles shared with `ui/tabs.tsx`                                        |
| `kit/FilterBar.tsx`  | The one filter surface: search, removable chips, a "+ Filter" popover, pinned chips and saved presets                                                                                    |
| `kit/useFilters.ts`  | Filter state, which is the URL: `set`/`setMany`/`clear`, plus `toTableFilters()` and a `filterKey` that resets paging                                                                    |
| `kit/Inspector.tsx`  | The row detail: a right-hand panel at `lg`+, a full sheet below it; `Esc`, up/down between rows, optional "Open page"                                                                    |
| `kit/kebab-column.tsx`    | The actions column, and the permission gating inside it                                                                                                                                  |
| `kit/ConfirmDialog.tsx`   | Every confirmation: tone, cascade list, type-to-confirm, one mount per screen                                                                                                            |
| `kit/SectionNav.tsx` | T5 section navigation: a `<nav>` at `md`+, a `Select` below it                                                                                                                           |
| `kit/SaveBar.tsx`         | Save/discard for a dirty form, plus the unsaved-changes guard (turn the anchor half off with `guardNavigation={false}` when the screen's own routed sub-navigation is part of that form) |
| `kit/useUnsavedGuard.ts`  | The two halves of "do not lose my edits": `beforeunload` and in-app anchor interception. Shared by `SaveBar` and `EntityFormDialog` so there is only one behaviour                       |
| `kit/WizardShell.tsx`     | T6 frame: step rail with `aria-current="step"`, body, footer, optional aside                                                                                                             |
| `kit/EntityHubHeader.tsx` | The T3 header: title, status pill, middot-joined metrics, actions, back link, and `level` for an entity nested inside a hub that already owns the `<h1>`                                 |
| `kit/PhaseStrip.tsx`      | Lifecycle position as an indicator only — it carries no actions                                                                                                                          |
| `kit/MasterDetail.tsx`    | The T4 split, including the narrow-viewport switch to list-or-detail with a Back button                                                                                                  |
| `kit/NextActionHero.tsx`  | The single "do this next" call to action on T1 and a hub Overview                                                                                                                        |

Supporting these, outside `kit/`: `components/data-table/AdminDataTable.tsx` is the
table engine (server or client mode, paging, sorting, column picker, mobile
cards, `toolbar` slot for the filter bar); `components/ui/tone.ts` is the
shared tone map (`TONE_CLASS` / `TONE_TEXT`), re-exported from
`components/admin/tone.ts` with `EYEBROW_CLASS`. Boolean flags in tables
use `StatusIcon`; lifecycle state uses `kit/StatusPill` (a pill-shaped
`Badge` with `tone=`); categories stay on shadcn `Badge`.
`components/admin/AdminDetailTable.tsx` is styling only, for a dense table
nested inside an editor — not a browser.

## Layout and responsive behavior

### Global container

The app container is defined in `frontend/src/app/layout.tsx`:

- max width: `max-w-screen-3xl`
- horizontal padding: `px-4 md:px-6 xl:px-10`

Principle: AQT is "wide analytics". Tables and charts should not feel cramped.

### Grids

The home page (`frontend/src/app/(site)/(home)/page.tsx`) uses simple, stable grids:

- stats: `lg:grid-cols-4`
- charts: `lg:grid-cols-2`
- tables/cards: `xl:grid-cols-4` + `col-span-*` where needed

Principle: grids must remain stable during loading and error states.

### Breakpoints

Custom breakpoints (including `xs`) are the `--breakpoint-*` values in the `@theme` block of `frontend/src/app/globals.css`.

Principle: verify 375px / 768px / 1024px / 1440px. Avoid horizontal scrolling.

## Navigation and context retention

### Sticky header

Header is sticky:

- `frontend/src/components/Header.tsx` uses `sticky top-0 z-50`

Principle: navigation and search stay accessible without hiding content.

### Sticky profile tabs

User profile tab list is sticky:

- `frontend/src/app/(site)/users/components/tabs/UserTabsClient.tsx` uses `sticky top-[var(--aqt-header-h)] z-40` around the shared `TabsList`

Principle: tab switching should not jump the layout. The active tab syncs to URL query params (`?tab=`), so links are shareable.

## States: loading, errors, empty data

### Skeleton-first

Prefer skeletons that preserve layout over centered spinners.

- Dashboard skeletons (home, `/statistics`, `/workspace/[slug]`): `frontend/src/components/skeletons/dashboard-skeletons.tsx`.
- User profile skeletons: `frontend/src/app/users/[slug]/page.tsx`.

Goal: reduce perceived latency and prevent content jumping.

### Errors, empty and not-found

There is exactly one surface for these: `frontend/src/components/ui/page-state-card.tsx`.

```tsx
<PageStateCard state="error" onAction={refetch} />
<PageStateCard state="filtered-empty" onAction={clearFilters} />
<PageStateCard state="empty" />
```

Rules:

- A query that can fail MUST destructure `isError` and render the `error` state.
  Rendering the empty state on failure tells the user "there is nothing here"
  when the truth is "we could not load it" — never do this.
- Distinguish `empty` (nothing exists) from `filtered-empty` (filters exclude
  everything). The latter always offers a way out.
- Copy defaults come from the `common.pageState.*` messages; override only when
  a page can say something more specific.

## Liquid Glass

Only two class names survive: `liquid-glass-panel` and `liquid-glass-surface`
(`frontend/src/app/globals.css`). They are thin surface aliases — a border, a
radius and a card background. There is no blur, no context provider and no
per-user aura.

The previous system (a React context writing `--lg-a/--lg-b/--lg-c`, plus an
"aura reporter" that sampled avatar colors) was removed: no CSS rule ever read
those variables, so every inline `style={{ "--lg-a": ... }}` was inert markup.
Do not reintroduce them.

## Content: numbers, density, readability

### Numbers

- Format numbers and dates through next-intl (`useFormatter()`, or
  `getFormatter()` on the server). Never construct `Intl.NumberFormat("en-US")`
  or call `toLocaleDateString("en-US")`: the app's default locale is `ru`, and a
  pinned formatter puts an English date next to a Russian one in the same table
  row. `formatDateRange` in `lib/utils.ts` takes `locale` as a **required**
  argument for exactly this reason.
- Use `tabular-nums` for metrics.

### Low-sample gate

- Percentiles and vs-average comparisons hide below 10 games (`LOW_SAMPLE_GAMES`, e.g. `frontend/src/app/(site)/users/components/overview/OverviewTopHeroesTable.tsx`): render an em dash with the rule in `title`, plus a `LOW SAMPLE` badge. "Top 2%" off three games is noise, not signal — never print a percentile without checking the sample size first.

### Truncation

- Long names/handles should use `truncate` and keep the full value in `title`.
  Example: `frontend/src/app/(site)/users/components/header/UserHeader.tsx`.

### Density

- Default density is "analytics comfortable": readable, not marketing-spacious.
- Tables can be denser, but do not sacrifice touch targets.

## Accessibility baseline (required)

We treat accessibility as a default constraint:

- visible focus rings on interactive elements
- `aria-label` for icon-only controls
- meaningful `alt` text for images (avatars/logos)
- adequate touch targets for primary actions

References:

- Focus patterns in `frontend/src/components/ui/tabs.tsx` and `frontend/src/components/ui/button.tsx`.
- `sr-only` usage in `frontend/src/components/Header.tsx`.

## Performance and UX smoothness

- Suspense + skeletons instead of blocking loading states.
- Use `cache()` for repeated server-side requests within a render.
  Example: `frontend/src/app/users/[slug]/page.tsx` (getUserAndProfile).
- Use `next/image` for images.
- Keep client components only where interaction is required.

## How to build a new page

Suggested process:

1. Define 1-2 key questions the page answers.
2. Split the page into independent blocks (usually Cards).
3. For each block: loading (skeleton), error (message Card), empty (explicit state).
4. Verify responsive layout: 375px/768px/1024px/1440px.
5. Verify keyboard navigation: tab order and visible focus.

## Anti-patterns to avoid

- Emoji or bare glyphs (`←`, `→`, `↑`, `✓`, `×`, `‹`) used as icons: screen
  readers read them literally. Use `lucide-react` with `aria-hidden`.
- `<div onClick>` / `<span role="button">` for navigation or actions. A `<tr>`
  is not a link; put a real `<a href>` in the row. Note that a `<tr>` is also
  not a valid containing block for an absolutely positioned overlay link — the
  overlay escapes its scroll container and scrolls the whole document sideways.
- Hover effects that shift layout (scale/size changes instead of color/opacity).
- Mixing inconsistent container widths/paddings within one page.
- Rendering content without skeletons, causing layout jumps.
- Clickable surfaces without cursor/hover/focus affordances.

## PR checklist

- No emoji icons; use a consistent icon set.
- Everything interactive has hover + visible focus.
- Loading uses skeletons; layout stays stable.
- Errors do not break the grid; messaging is clear.
- No horizontal scroll at 375px: measure `document.documentElement.scrollWidth`
  against `innerWidth`, do not eyeball it. A wide table needs its own
  `overflow-x: auto` region (labelled, `tabIndex={0}`) — clipping it with
  `overflow: hidden` hides columns instead of making them reachable.
- Touch targets are at least 24x24.
- Every interactive element has an accessible name. Verify with the browser's
  accessibility tree, not by reading the JSX.
- Contrast stays readable on dark theme (and on Liquid Glass surfaces).
