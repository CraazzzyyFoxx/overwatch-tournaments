# Draft Console Redesign (round 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rework the public live-draft captain/spectator room into a wide "command console": compact `PageHero` (secondary), `[order+recent rail | dossier→shortlist→pool(3-col) | all-teams right column]`, timer/turn folded into the fixed command bar, presence (online captains + viewers) in the hero — matching the locked mockup.

**Architecture:** Frontend-only, builds on the round-1 components (already enriched). Restructure `CaptainDraftWorkspace`/`SpectatorDraftWorkspace` layout; rewrite `DraftPageHero` as a compact header on the shared `HeroFrame` shell; add a vertical `column` variant to `TeamRosters`; fold the countdown ring + turn state into `PickCommandBar`; move presence into the hero. No backend/API/type changes.

**Tech Stack:** Next.js 16 (App Router, client), React 19, TS, Tailwind v4 + `--aqt-*` tokens, next-intl v4, lucide-react, vitest (node env), bun.

## Global Constraints

- **Visual spec = the mockup.** Open it before every UI task: run the loopback server if needed (`cd <scratchpad> && python -m http.server 8799 --bind 127.0.0.1 &`) and view `http://127.0.0.1:8799/draft-console-mockup.html`, or open the file `C:\Users\andre\AppData\Local\Temp\claude\C--Users-andre-Programming-anak-tournaments\b3c2af3e-2303-4af8-a4b5-565534b7dce6\scratchpad\draft-console-mockup.html`. Match layout/spacing/hierarchy; the mockup's role/rank/hero glyphs are PLACEHOLDERS — in code use the REAL components below.
- **Real assets, not mockup placeholders:** roles → `PlayerRoleIcon` (`@/components/PlayerRoleIcon`) + `getRoleIconName`/`ROLE_ACCENT` (`@/lib/roles`); ranks → `PlayerDivisionIcon` (`@/components/PlayerDivisionIcon`, pass `tournamentGrid={divisionGrid}`); heroes → `AvatarStack` (`@/components/ui/avatar`) + `getHeroIconUrl` (`@/utils/player`).
- **Tokens only** (`--aqt-*`); "one teal leads" — team crests use a single muted hue each, teal stays the dominant accent. Reduced-motion gating on any pulse/ring.
- **Grid source = tournament grid** (`divisionGrid` prop already threaded from `DraftBoard`). No `useDivisionGrid()` in the room.
- **i18n:** every user string via `useTranslations("draftRedesign")`; new keys in BOTH `frontend/src/i18n/messages/{en,ru}.json` under `draftRedesign`, parallel; `t(key,{x})` always gets `{x}` (RU plurals = ICU).
- **Verify:** `bunx tsc --noEmit` green; `bunx eslint "src/app/**/draft/**/*.tsx" "src/app/**/draft/**/*.ts"` zero errors; `bunx vitest run draft` passes; JSON files parse. UI tasks additionally verified by a Playwright screenshot at 1920px (controller does this).
- No backend/API/type changes.

---

## File Structure

- Modify: `frontend/src/app/draft/[id]/page.tsx` — back button → ghost; widen container.
- Modify: `_components/DraftBoard.tsx` — widen container; thread presence to hero; drop standalone `DraftConnectionStatus` render.
- Rewrite: `_components/DraftPageHero.tsx` — compact header on `HeroFrame` + inline presence.
- Modify: `_components/PlayerPool.tsx` — 3-col grid, bigger hero avatars.
- Modify: `_components/CaptainShortlist.tsx` — add compact chips variant.
- Modify: `_components/PickCommandBar.tsx` — fold in ring + turn state.
- Rewrite layout: `_components/CaptainDraftWorkspace.tsx` — new 3-zone grid, dossier→shortlist→pool center, all-teams right column, remove CurrentPick band.
- Modify: `_components/TeamRosters.tsx` — vertical `column` variant + crest + captain online dot.
- Modify: `_components/SpectatorDraftWorkspace.tsx` — mirror (hero presence, all-teams, keep focal CurrentPick).
- Create: `_lib/draft-crest.ts` (+ `.test.ts`) — deterministic team crest (initial + muted hue).
- Modify: i18n `{en,ru}.json`.

---

## Task 1: Room shell — ghost back button + full-bleed width

**Files:** Modify `frontend/src/app/draft/[id]/page.tsx`; Modify `_components/DraftBoard.tsx:127`.

- [ ] **Step 1: Back button → ghost.** In `page.tsx`, the back `Link` (`styles.backLink` + border classes) → neutral ghost: drop the border + border-hover; use muted text that goes teal on hover. Replace its className with:
```tsx
className="inline-flex min-h-11 items-center gap-2 rounded-lg px-2.5 text-sm font-medium text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-card-2)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
```
(Keep the `ArrowLeft` icon + `styles.backArrow` hover-translate.)

- [ ] **Step 2: Widen shells.** In `page.tsx` the toolbar+stage use `max-w-[1600px]`; change both to `max-w-[min(2000px,96vw)]`. In `DraftBoard.tsx:127` change the workspace wrapper `max-w-[1400px]` → `max-w-[min(2000px,96vw)]`.

- [ ] **Step 3: Verify + commit.** `cd frontend && bunx tsc --noEmit` green. Manual: back button reads as a plain ghost control; room uses near-full width. Commit: `feat(draft): ghost back button + full-bleed console width`.

---

## Task 2: `draft-crest` helper (pure, TDD)

**Files:** Create `_lib/draft-crest.ts` + `_lib/draft-crest.test.ts`.

**Interfaces produces:** `teamCrest(team: { id: number; name: string }): { initial: string; hue: number }` — `initial` = first alphanumeric of name upper-cased (fallback `#`), `hue` = deterministic 0–359 from the id (stable per team). Consumed by Task 8 (`TeamRosters` crest).

- [ ] **Step 1: Failing test**
```ts
import { describe, expect, it } from "vitest";
import { teamCrest } from "./draft-crest";

describe("teamCrest", () => {
  it("takes the first letter, uppercased", () => {
    expect(teamCrest({ id: 1, name: "void syndicate" }).initial).toBe("V");
  });
  it("falls back to # for empty/symbol names", () => {
    expect(teamCrest({ id: 2, name: "  " }).initial).toBe("#");
  });
  it("hue is deterministic per id and within 0..359", () => {
    const a = teamCrest({ id: 7, name: "Nova" }).hue;
    expect(a).toBe(teamCrest({ id: 7, name: "Other" }).hue);
    expect(a).toBeGreaterThanOrEqual(0);
    expect(a).toBeLessThan(360);
  });
});
```
- [ ] **Step 2:** `cd frontend && bunx vitest run "src/app/(site)/tournaments/[id]/draft/_lib/draft-crest.test.ts"` → FAIL.
- [ ] **Step 3: Implement**
```ts
export function teamCrest(team: { id: number; name: string }): { initial: string; hue: number } {
  const match = team.name.match(/[A-Za-z0-9]/);
  const initial = match ? match[0].toUpperCase() : "#";
  // stable hue from id; golden-angle spread keeps adjacent ids visually distinct
  const hue = Math.round((team.id * 137.508) % 360);
  return { initial, hue };
}
```
- [ ] **Step 4:** rerun → PASS. **Step 5:** commit `feat(draft): deterministic team crest helper`.

---

## Task 3: PlayerPool — 3-column grid + bigger hero avatars

**Files:** Modify `_components/PlayerPool.tsx`.

- [ ] **Step 1: 3-column responsive grid.** The results grid `className="mt-4 grid gap-x-5 sm:grid-cols-2"` → 3-column at wide, 2 at medium, 1 at narrow:
```tsx
className="mt-4 grid gap-x-6 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3"
```
- [ ] **Step 2: Bigger hero avatars.** The pool row `AvatarStack size={18}` + `Avatar className="h-[18px] w-[18px]"` → `size={30}` and `h-[30px] w-[30px]`. Keep `max={4}`.
- [ ] **Step 3: Verify + commit.** `bunx tsc --noEmit` green. Controller Playwright-checks the 3-col pool doesn't cramp cards. Commit: `feat(draft): 3-column pool + larger hero avatars`.

---

## Task 4: CaptainShortlist — compact chips variant

**Files:** Modify `_components/CaptainShortlist.tsx`.

**Interfaces produces:** a `variant?: "panel" | "chips"` prop (default keeps current panel). `"chips"` renders a single horizontal wrap of removable chips with a `★ Shortlist` mono label — for placement under the dossier. Consumed by Task 7.

- [ ] **Step 1: Add the variant.** When `variant === "chips"`: render a `flex flex-wrap items-center gap-2` row: a `★ {t("shortlist")}` mono label, then each player as a chip `button` (name, click = `onSelect`) with an `×` remove control (`onRemove`); empty → a muted "empty" hint. Reuse tokens (`--aqt-border-2`, `--aqt-card`, hover `--aqt-teal`). Keep the existing panel markup for the default variant. Match the mockup's `.shortlist-bar`/`.sl-chip`.
- [ ] **Step 2: Verify + commit.** `bunx tsc --noEmit` green. Commit: `feat(draft): shortlist chips variant`.

---

## Task 5: PickCommandBar — fold in the countdown ring + turn state

**Files:** Modify `_components/PickCommandBar.tsx`; Modify caller `CaptainDraftWorkspace.tsx` (props).

**Interfaces produces:** `PickCommandBar` gains props `board: DraftBoard`, `isMyPick: boolean`, `myTeamId: number | null` (in addition to existing). It renders, left-to-right: `DraftClockRing` (from `./DraftClockRing`) + a turn block (`YOUR TURN`/on-clock team + `pick N/total`) + the existing selection detail + the confirm button. When it's not the viewer's pick, show the on-clock team + disabled confirm.

- [ ] **Step 1: Add ring + turn block.** Import `DraftClockRing` and `resolveDraftAccent`/`accentToken` (`../_lib/draft-visual`). Compute `accent = resolveDraftAccent(board)`, `current = board.current_pick`, on-clock team name. Prepend to the bar (before the existing selection block):
```tsx
<DraftClockRing expiresAt={current?.clock_expires_at ?? null} paused={board.session.status === "paused"} totalSeconds={board.session.pick_time_seconds} accent={accent} />
<div className="shrink-0 border-r border-[color:var(--aqt-border-2)] pr-4">
  <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[color:var(--aqt-teal)]">{isMyPick ? t("yourTurn") : t("onClockLabel")}</p>
  <p className="text-sm font-semibold">{onClockTeamName} <span className="font-normal text-[color:var(--aqt-fg-muted)]">· {t("pickMeta", { pick: current?.overall_no ?? 0, total: board.picks.length })}</span></p>
</div>
```
Keep the Enter-to-confirm effect + safety dialog + selection + review button unchanged. The bar renders for captains regardless of whose turn (selection/confirm gated by `canConfirm` as today).
- [ ] **Step 2: i18n.** Add `onClockLabel` (en "On the clock" / ru "Ходит сейчас") to both dicts. (`yourTurn`, `pickMeta` already exist.)
- [ ] **Step 3: Verify + commit.** `bunx tsc --noEmit` green (caller updated in Task 7 — if building standalone, temporarily pass the new props from CaptainDraftWorkspace in this task). Commit: `feat(draft): command bar with countdown ring + turn state`.

---

## Task 6: CaptainDraftWorkspace — new console layout

**Files:** Modify `_components/CaptainDraftWorkspace.tsx`.

**Consumes:** PlayerPool 3-col (T3), shortlist chips (T4), PickCommandBar ring/turn (T5), TeamRosters column variant (T7).

- [ ] **Step 1: Remove the CurrentPick focal band.** Delete the `<CurrentPick .../>` render + the "checkingSafeOptions" note relocation is fine to keep as a slim line above the grid. The turn/timer now lives in `PickCommandBar`.
- [ ] **Step 2: New desktop grid.** Replace the current `md:grid-cols-[...] xl:grid-cols-[260px_1fr_320px]` block with:
  - `grid gap-4 xl:grid-cols-[248px_minmax(0,1fr)_378px]`.
  - **Left rail** (`<aside>` sticky as today): `DraftOrder` (order) then `DraftEventFeed` (recent picks) — quiet headers (already).
  - **Center** (`<main class="min-w-0 flex flex-col gap-4">`): `PlayerInspector` (dossier, band) → `CaptainShortlist variant="chips"` → `PlayerPool`.
  - **Right column** (`<aside>` sticky, own scroll): `TeamRosters variant="column"` (ALL teams — drop `focusTeamOnly`), passing `picks`, `teamSize`, `onClockTeamId`, `myTeamId`, `divisionGrid`.
- [ ] **Step 3: Mobile.** Keep the mobile tab switcher; the "team" tab shows all teams (`TeamRosters` default grid, NOT focusTeamOnly); "pool" tab shows dossier + shortlist chips + pool.
- [ ] **Step 4: Command bar props.** Pass `board`, `isMyPick={gating.isMyPick}`, `myTeamId={gating.myTeamId}` to `PickCommandBar` (T5).
- [ ] **Step 5: Verify + commit.** `bunx tsc --noEmit` green. Controller Playwright-checks captain layout vs mockup. Commit: `feat(draft): captain console layout (dossier→pool center, all-teams right)`.

---

## Task 7: TeamRosters — vertical `column` variant + crest + captain dot

**Files:** Modify `_components/TeamRosters.tsx`.

**Consumes:** `teamCrest` (T2).
**Produces:** `variant?: "grid" | "column"` prop (default `"grid"`). `"column"` = a vertical scroll list of compact team cards (mockup `.teams-col`/`.tcard`): crest monogram (`teamCrest` → `hsl(hue 55% 22%)` bg / `hsl(hue 70% 72%)` text), name, captain online dot, avg-division + `#position`, role-fill row, roster rows (drafted-role icon + name + division), open slots; my team + on-clock ringed teal.

- [ ] **Step 1: Add captain online state.** Add optional props `onlineCaptainIds?: Set<number>` (auth ids) so a card can show a captain online/offline dot (green `--aqt-support` / faint). Pass from the workspace via presence (Task 8 wires spectator; captain workspace passes it too — thread `onlineCaptainIds` from `DraftBoard`→workspaces).
- [ ] **Step 2: Column variant.** When `variant === "column"`: wrap cards in `flex flex-col gap-3 overflow-y-auto` (parent aside provides sticky + max-height). Each card compact (mockup `.tcard`): crest + name + online dot + avg/position header, role-fill line, roster rows, open slots. Keep the existing grid variant intact for mobile/default.
- [ ] **Step 3: i18n** — reuse existing (`onTheClock`, `teamAverage`, `openSlot`, `roles.*`); add `captainOnline`/`captainOffline` if not already present (they were added round 1 — reuse).
- [ ] **Step 4: Verify + commit.** `bunx tsc --noEmit` green. Commit: `feat(draft): team rosters vertical column variant + crest + captain dot`.

---

## Task 8: Compact console hero + presence

**Files:** Rewrite `_components/DraftPageHero.tsx`; Modify `_components/DraftBoard.tsx`.

**Consumes:** presence data.
**Produces:** `DraftPageHero` gains props `presence: DraftPresenceState`, `connectionState: RealtimeConnectionState`, `currentUserId: number | null` (plus existing `tournament`, `board`, `mode`).

- [ ] **Step 1: Rewrite DraftPageHero as a compact header.** Use `HeroFrame` (from `@/components/site/PageHero`) as the shell. Inner = two tight rows (mockup):
  - **Top row:** breadcrumb (`HeroCoord`: `Tournaments / #{tournament.number} · {formatDateRange(start,end,locale)}`) + PRESENCE pushed right — online-captain avatar stack (from `presence.users` ∩ `teams[].captain_auth_user_id`, offline dimmed, "N/total online"), viewer count `presence.anonymous_viewer_count`, and `connectionState` dot.
  - **Main row:** compact title (`tournament.name`, ~clamp(21px,2.1vw,28px)) + meta pills (status, format, teams, roster) on the left; 4 compact stats on the right (`Teams`, `Pool` = available count, `Progress` = completed/total, `On clock` = team name). No lede, no pips, no clock ring (those live elsewhere).
  Keep padding tight (~14px 28px). Match mockup `.hero`/`.hero-top`/`.hero-main`/`.presence`.
- [ ] **Step 2: DraftBoard wiring.** Resolve `onlineCaptainIds` + pass `presence`, `connectionState`, `currentUserId` to `DraftPageHero`; REMOVE the standalone `<DraftConnectionStatus>` render (presence now in the hero). Thread `onlineCaptainIds` to both workspaces (for TeamRosters captain dots). Keep `DraftConnectionStatus.tsx` file (may be reused) or delete if now unreferenced (grep first).
- [ ] **Step 3: i18n** — add `onlineCount` (ICU: en `{n} of {total} online` / ru with plural), reuse `anonymousViewers`, `connection.*`. Reuse `format`/`rosterSize`/`teams`/`progress`/`onClock`.
- [ ] **Step 4: Verify + commit.** `bunx tsc --noEmit` green; JSON parses. Controller Playwright-checks compact hero + presence. Commit: `feat(draft): compact console hero with inline presence`.

---

## Task 9: SpectatorDraftWorkspace parity

**Files:** Modify `_components/SpectatorDraftWorkspace.tsx`.

- [ ] **Step 1:** Spectator keeps a focal turn/clock (no command bar): keep `<CurrentPick>` (round-1 focal card with ring) at the top. Below: grid `[all-teams | order+feed]` or all-teams as the main region + order/feed rail — mirror the captain hierarchy (all teams prominent). Pass `divisionGrid`, `picks`, `teamSize`, `onClockTeamId`, `onlineCaptainIds` to `TeamRosters` (use `variant="grid"` for spectator's wider area, or `column` — pick to match captain; grid reads better full-width). Presence is in the shared hero (Task 8), so no separate presence here.
- [ ] **Step 2: Verify + commit.** `bunx tsc --noEmit` green. Controller Playwright-checks spectator view. Commit: `feat(draft): spectator parity with console redesign`.

---

## Task 10: Full-room verification

**Files:** none (verify + fixups).

- [ ] **Step 1:** `cd frontend && bunx tsc --noEmit` green; `bunx eslint "src/app/**/draft/**/*.tsx" "src/app/**/draft/**/*.ts"` zero; `bunx vitest run draft` all pass; `node -e "require('./src/i18n/messages/ru.json')"` + en parse.
- [ ] **Step 2:** i18n parity — every new key in both locales, ICU valid, no `t(key,{x})` missing `{x}`.
- [ ] **Step 3:** Controller renders the real room (or a mock-data preview) via Playwright at 1920px for BOTH captain and spectator; compare to the mockup; fix visual gaps.
- [ ] **Step 4:** Commit any fixups: `chore(draft): console redesign verification fixups`.

---

## Self-Review (author checklist — completed)

**Spec coverage:** compact hero → T8; full-bleed width → T1; 3-col pool + big avatars → T3; all-teams right column → T6/T7; dossier→shortlist→pool center → T6 (+T4 chips); timer/turn in command bar → T5; presence (captains+viewers) → T8; ghost back button → T1; crest → T2/T7; spectator → T9; craft (real icons/emblems/portraits) → Global Constraints + T3/T7. **Gap noted & folded:** removing `CurrentPick` for captains (T6) while keeping it for spectators (T9) — explicit in both tasks.

**Placeholder scan:** UI tasks reference the mockup for pixel detail + give the key structural classNames/JSX; the one pure helper (T2) has full TDD code. No TBD/TODO.

**Type consistency:** `variant` prop names — `TeamRosters` `"grid"|"column"`, `CaptainShortlist` `"panel"|"chips"`. `DraftPageHero` new props (`presence`, `connectionState`, `currentUserId`) and `PickCommandBar` new props (`board`, `isMyPick`, `myTeamId`) are consistent between producer task and caller (T6/T8). `teamCrest` signature consistent T2↔T7. `onlineCaptainIds: Set<number>` consistent T7↔T8.
