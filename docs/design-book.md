# OWT Design Book — "Editorial Tactical"

> The single source of truth for the OWT frontend design system.
> Interactive version: [`/docs/design-book.html`](../frontend/public/docs/design-book.html).
> Status: **v2 — tokens reconciled** against `frontend/src/app/globals.css` (the real `--aqt-*`, not the prototype `--bg`/`--brand`). Every rule below carries one of three tiers, the same three the interactive version uses: **Verified** — measured against `globals.css` / `tailwind.config.ts`, safe to build on; **Specified** — stated by this book and not implemented upstream, whether a target rule or a token/component API the code expresses only as CSS-class shape and inline literals; **Fixed** — a divergence that was found and has already been repaired upstream, recorded so the fix is not undone by someone reading older code.

The direction is **Editorial Tactical**: an airy editorial layout (hairline rules, open blocks instead of boxes, large mixed-case headings) plus a tactical/broadcast voice (a barely visible coordinate grid, mono labels, a large grotesque on numbers). Dark-only.

Three theses:

1. **Air over boxes** — group with whitespace and hairline rules; a bordered card is only for dense data.
2. **Numbers are telemetry** — statistics in grotesque + mono, tabular figures, like a broadcast overlay.
3. **Meaning over decoration** — colour and the role spectrum encode data, they never decorate. One teal leads.

---

## 1. Tokens

The source of truth is `:root` in `frontend/src/app/globals.css`. Below are the real `--aqt-*` (Verified), not a separate scheme still waiting to be aliased.

```css
:root {
  /* ground & elevation — 4 steps, nesting is overlays, not a new grey */
  --aqt-bg:hsl(220 21% 5%); --aqt-bg-2:hsl(220 22% 7%); --aqt-card:hsl(220 22% 8%); --aqt-card-2:hsl(222 24% 11%);
  --aqt-border:hsl(219 19% 15%); --aqt-border-2:hsl(217 17% 21%); --aqt-border-3:hsl(216 16% 26%); /* exactly THREE borders, -3 = active/focus/scrollbar */

  /* text — 4 steps */
  --aqt-fg:hsl(214 33% 96%); --aqt-fg-muted:hsl(212 13% 65%); --aqt-fg-dim:hsl(213 9% 58%); --aqt-fg-faint:hsl(214 10% 52%);

  /* accent */
  --aqt-teal:hsl(172 70% 49%);                        /* one teal, no hue drift */
  --aqt-warm:hsl(36 88% 65%);                         /* = --aqt-amber, featured moments ONLY */

  /* roles */
  --aqt-tank:hsl(209 82% 65%); --aqt-damage:hsl(337 81% 66%); --aqt-support:hsl(150 57% 52%);
  --aqt-spectrum:linear-gradient(90deg,var(--aqt-tank),var(--aqt-damage),var(--aqt-support));

  /* results & quality — SEPARATE tokens, neither roles nor statuses */
  --aqt-win:hsl(150 57% 52%); --aqt-loss:hsl(349 84% 63%); --aqt-draw:hsl(36 88% 65%);
  --aqt-good:var(--aqt-win); --aqt-mid:var(--aqt-draw); --aqt-bad:var(--aqt-loss);

  /* statuses */
  --aqt-status-live:hsl(349 84% 63%); --aqt-status-upcoming:hsl(36 88% 65%); --aqt-status-finished:hsl(213 9% 47%); --aqt-status-draft:hsl(215 83% 66%);

  /* podium */
  --aqt-gold:hsl(42 63% 60%); --aqt-silver:hsl(212 21% 73%); --aqt-bronze:hsl(26 49% 54%);

  /* shape */
  --aqt-radius-card:12px; --aqt-radius-sm:8px; --aqt-radius-xs:4px; --aqt-radius:14px; /* hero */
}
```

Every `--aqt-*` is declared **once** as an HSL triplet (`--aqt-h-*`) and expanded twice — as a ready-made colour and as a bare triplet for the shadcn layer (`--primary: var(--aqt-h-teal)`). That way, overriding a shadcn name inside a scope cannot turn into `hsl(hsl(...))` — see §0 in `frontend/DESIGN.md`.

### Colour semantics rules

| Context | Tokens | Examples |
|---|---|---|
| Result | `--aqt-win / --aqt-loss / --aqt-draw` | the `3–1` score, W-D-L, form chips, map pips |
| Quality | `--aqt-good / --aqt-mid / --aqt-bad` | winrate %, ▲/▼ deltas, impact bars, DIFF |
| Role | `--aqt-tank / --aqt-damage / --aqt-support` | role icons, role bars, avatar tints |
| Status | `--aqt-status-live / --aqt-status-upcoming / --aqt-status-finished / --aqt-status-draft` | tournament badges |

- Winrate colour thresholds: **≥60% → good, 50–59% → mid, <50% → bad**.
- Today `--aqt-win`≡`--aqt-support`, `--aqt-loss`≡`--aqt-status-live`, `--aqt-draw`≡`--aqt-warm` by hue (150/349/36) — that is deliberate, but the tokens are decoupled: any group can be recoloured without touching the others.
- **The role spectrum (the tank→damage→support gradient) is semantics, not decoration**: only as a role-distribution bar (team composition) and as the signature hairline of the profile header.
- `--aqt-warm` (= `--aqt-amber`) as an accent — featured content only (the main tournament, titles).

## 2. Typography

| Role | Typeface | Reason |
|---|---|---|
| UI, headings, data/labels | **Inter** (400/500/600/700) | mixed-case, **never** condensed caps; the "tactical voice" (eyebrows, table heads, scores) is Inter uppercase with `tracking-label` + `tabular-nums` (`.aqt-tnum`, `--aqt-data`) |
| Display + large numbers | **Onest** (500/600/700/800) | a Cyrillic-native geometric grotesque: "Grand Final" and its Cyrillic equivalent have identical plastics. Space Grotesk was rejected — it has no Cyrillic |
| Code, identifiers | system monospace (Tailwind `font-mono`) | API keys, usernames, log output only — never UI labels. JetBrains Mono was retired: at 11px uppercase it read as an IDE, not a product |

```tsx
// app/layout.tsx — the fonts are self-hosted (next/font/local), NOT next/font/google:
// next/font/google fetches from fonts.gstatic.com at build time, and a production build
// once broke on a hash rotation. The .variable classes sit on <html>, not on <body> —
// globals.css aliases them from :root (--aqt-data/--aqt-display), and a custom property
// resolves where it is declared: an alias on :root cannot see a variable
// set one level below (<body>).
import localFont from "next/font/local";

const inter = localFont({ src: "./fonts/inter-variable.woff2", variable: "--font-inter" });
const onest = localFont({ src: "./fonts/onest-variable.woff2", variable: "--font-onest" });

// <html className={cn(inter.variable, onest.variable)}>
```

**Scale = type roles**, defined once in `globals.css` (`@theme static`) and used as `text-<role>` / `var(--text-<role>)`; each carries its line-height, weight stays explicit. `label 12/1.25` · `caption 13/1.4` · `body 14/1.5` · `ui 15/1.5` · `heading 18/1.3` · `title 22/1.15/−.01em` (section h2, mixed-case) · `headline 30/1.1/−.02em` · `display clamp(32–56)/1.03/−.01em` (hero h1). Uppercase labels take `tracking-label` (0.08em). No `text-[Npx]` anywhere; **the readability floor is 12px** for anything meant to be read (R6 in `check-design-compliance.mjs` still bans <11).

## 3. Roles, divisions, avatars

### Role markers — which form goes where

| Surface | Form |
|---|---|
| **Role split** (the only place) | icon + mono label |
| Tables and rows (rosters, hero tables, leaderboards) | **icon only**, role name in `title`/`aria-label` |
| Meta lines (the "Tank main" header, tournament subtitle) | text only |

The icons are the project's standard `TankIcon/DamageIcon/SupportIcon` (`PlayerRoleIcon`), viewBox `0 0 40 40`. Do not reinvent them.

### Divisions

Icon only (`DivisionIcon`/`PlayerDivisionIcon` + `lib/divisions/grid.ts`), the division name goes in `alt`/`title`. We never spell the division out in text on display surfaces; a list of names is acceptable only in the rank-selection form (that is input, not display).

### Hero avatars (`HeroImage` / `HeroStrip`)

| Context | Size |
|---|---|
| Standard stack (match rows, rosters, teammates) | **30px** |
| Compact detail rows (match expansions, dossier runs) | 24px |
| Inline in tables (top heroes) | 26px |
| Single avatar (sidebar rows) | 32px |

The stack collapses into `+N`; the overlap is −9px; player avatars (as opposed to hero avatars) carry a `data-players` marker so that the hero popover leaves them alone.

## 4. Accessibility — the mandatory floor

- **Never colour-only**: W/L squares carry letters, trend dots carry a ring at the podium and a hollow shape in the bottom bucket, result chips carry the letters W/L/D.
- **Every hover popover** (hero stats, MVP breakdown) also opens on **focus** and on **tap**: the trigger gets `tabindex="0"` + `aria-label`, a tap outside closes it, scrolling hides it.
- `:focus-visible` — a 2px teal outline on everything interactive; `prefers-reduced-motion` mutes all animation; tabs use `role=tab/tabpanel`; modals get a focus trap + focus restoration + Esc.
- Contrast: `--aqt-fg-faint` (52% L) is the minimum for text on `--aqt-bg` (the text ramp has 4 steps at 96/65/58/52%, all distinguishable and ordered).

## 5. Data honesty

- **No SR/MMR** — they do not exist in the system; do not invent them, neither in statistics nor in achievements.
- **Encounter ⊃ Matches**: an encounter is a series against an opponent (the `3–1` score), and inside it are the map matches; statistics (heroes/KDA/MVP) live per match, while the encounter shows aggregates (median MVP, avg KDA, hero stack). Do not label an encounter with the name of a single map.
- **Mix tournaments**: a player has no permanent team — a team is meaningful only in the context of a tournament. No "pre-filled" teams in the profile.
- **Per workspace**: profile numbers live in the context of a single community; we do not show aggregated community lists as a caption to the numbers.
- **Low-sample gate**: percentiles and vs-avg are hidden below **n < 10 games** — an em dash + a `title` with the rule + a `LOW SAMPLE` badge. "Top 2%" off 3 games is noise.
- **No "seasons"** — tournaments only; frame everything by tournaments/periods.
- One term per metric: **Closeness** (not Proximity), with a glossary `title` on first use.

## 6. Key patterns

- **Scouting report** — a verdict sentence in the profile header instead of bare numbers; the data is generated by rules with thresholds, and on a small sample it is not shown at all.
- The **percentile language** "Top X%" plus a **horizontal percentile bar** under the value (fuller = better). A vertical tick was rejected: an encoding that needs a caption is a failed encoding.
- **Lobby leaderboard**: every per-stat KPI tile is a button that opens a modal with every player in the lobby ranked by that statistic — stat chips, medals for the top 3, your own row highlighted (`rank + top X%`), a bar vs the leader; inverse stats (Deaths) are ranked ascending and marked "lower is better".
- **Master-detail** for tournament lists (Event dossier + a compact list) — instead of tables with accordions.
- **Digest blocks**: every Overview block that previews another tab carries a "View all →" that switches to it.
- **Empty states** of two kinds: page-level (an invitation to act) and filter-zero inside lists (the reason + an inline "Reset filters"). A filtered list never goes empty silently.
- **Dates**: relative `2d ago` plus the absolute date in `title`. A bare `2D` is forbidden — it collides with the letter for Draw.
- **Deep links**: the screen, tab, filters, search and the selected tournament all live in the URL (`searchParams` in Next). A state dropped into Discord as a link opens up exactly the same.
- **Share card**: the player card renders to a 1200×630 PNG (OG) on canvas — the grid, the spectrum bar, Onest figures, form chips, the profile URL; clipboard plus a download fallback.
- **MVP ordinal**: one form everywhere — `1st` in gold, the rest in `--aqt-fg-faint`, with a per-map breakdown on hover/tap.
- Modals in the real code are the shadcn `Dialog`; components live in `components/ui/` (no hand-rolled overlays; portals outside `.cRoot` cannot see the tokens).

## 7. Layout

- Content width: `max-width:1400px` (1180 is too narrow) — **Specified**, not implemented in code. The site's real container is `1720px` (`screen-3xl`, `frontend/tailwind.config.ts`, applied in `(site)/layout.tsx`) with `px-4/md:px-6/xl:px-10` gutters — **Verified**. 1400px remains the target for narrowing the readable column later, not a description of the current layout.
- The profile Overview is two flex columns (`main flex:1` + `sidebar 380px`), and the cards pack tightly without grid gaps; on mobile the columns need `align-items:stretch`.
- Numeric table columns: `th.num { text-align:right }` must beat `table.tbl th` on specificity.
- Wide content (tables, brackets) scrolls horizontally inside its own container (`.tblw`); the page body never scrolls sideways.

## 8. Decision changelog (prototype v22 → v48)

| Version | Decision |
|---|---|
| v22–25 | Profile tabs, scouting report, percentile language, mobile fixes (`min-width:0` on grid children), a11y pass |
| v27–35 | Tournaments subpage: real API fields, no invented MVPs or dates; accordions dropped after 5 iterations |
| v40–42 | **Master-detail** "Event dossier"; roster table: role as an icon, division as an icon, Avg MVP |
| v43 | Type scale +1px for everything ≤14.5px (the "too small" complaint) |
| v44 | Match heroes = a 1–3+N stack (OW players use several heroes); the LOG indicator; a modal with all opponents |
| v45 | `th.num` alignment fix; nested padding normalised |
| **v46** | **Onest** instead of Space Grotesk (Cyrillic); the `--win/--loss/--draw` + `--good/--mid/--bad` tokens; letters in map results; rings/hollows on trend dots; an Achievements grid with working filters; faceted Matches filters + a clickable "By stage"; fonts inlined into the artifact as data URIs |
| **v47** | The role-marker rule (icon + text only in Role split); avatars 24→30px; horizontal percentile bars; Closeness; `2d ago`; "View all →"; muted provider chips |
| **v48** | Lobby leaderboard built from KPI tiles; touch/keyboard popovers; low-sample gate + filter-zero empty state; deep links in the hash; Share → PNG |

## 9. Fixed — found and already repaired upstream

- **The `:root`-vs-`<body>` font trap.** Until a recent pass the stack did not render: `globals.css` aliased the `next/font` variables from `:root`, while `layout.tsx` hung the `.variable` classes on `<body>`. A custom property resolves where it is declared, so the variable simply did not exist on `:root` — and a failed `var()` poisons the whole value, so even a literal fallback next to it did not kick in. All 73 references to `--aqt-mono`/`--aqt-display` in `globals.css` silently rendered in Inter. Fixed by moving the classes onto `<html>` (`app/layout.tsx:109-116`).
- **Uppercase on display blocks.** `globals.css` once forced `text-transform:uppercase` on the 52px display blocks — a direct violation of §2's "never condensed caps". Both blocks are mixed-case now; `uppercase` survives in the code only on mono labels (the correct use).

## 10. Specified — still ahead of the code (Phase 0+)

- Spacing-scale tokens; consolidating the ~10 metric-tile primitives into a single component.
- `title` → `aria-label`/`alt` on divisions (in the real build `DivisionIcon` already has an alt).
- Formalise "verdict" and "Top X%" as design-system components with generation rules and localisation (the Russian templates are authored, not translated).
- Skeleton states in the system's own aesthetic (mono coordinates + a hairline frame).
- Narrow the readable column to 1400px (it is 1720px full-width today) — if editorial review decides it is still needed.
