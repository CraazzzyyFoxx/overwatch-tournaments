# Draft live-room hierarchy + regression restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore visual hierarchy and lost data-density/emphasis in the public live-draft room while keeping the editorial-tactical aesthetic, and fix two regressions (ranks bypassing DivisionGrid; broken sticky command bar).

**Architecture:** Frontend-only. Introduce two pure helper modules (visual/state mapping + extended pool model), thread the tournament `DivisionGrid` from `DraftBoard` down to every rank-rendering component, then restyle each panel into three attention tiers (focal state card → working area → quiet reference). Pure logic is TDD'd; presentational components are verified via typecheck + manual browser checks (the repo's vitest runs in `node` env, so components are not render-tested — matches existing draft test conventions).

**Tech Stack:** Next.js 16 (App Router, RSC + client), React 19, TypeScript, Tailwind v4 + `--aqt-*` design tokens, next-intl v4, vitest v4 (node env), bun package manager, lucide-react icons.

## Global Constraints

- **Design tokens only:** colours come from `--aqt-*` (globals.css). State accent mapping: `live`→`--aqt-teal`, `paused`→`--aqt-amber`, `blocked`/`urgent`→`--aqt-live` (rose), `done`/`safe`→`--aqt-support`. Role tints (`--aqt-tank`/`--aqt-damage`/`--aqt-support`) are secondary strokes, never fills. Single dominant accent at a time ("one teal leads").
- **DivisionGrid source = tournament grid:** `tournament.division_grid_version ?? DEFAULT_DIVISION_GRID`. No component may render a raw SR number where a division icon belongs. Do NOT use `useDivisionGrid()` inside the room anymore.
- **Hero avatars:** render via `AvatarStack` (`@/components/ui/avatar`) + `getHeroIconUrl` (`@/utils/player`). Do NOT use `HeroStatsPopover` (needs per-hero stats the pool lacks).
- **shadcn/existing primitives** over hand-rolled (`@/components/ui/*`).
- **i18n:** all user-facing strings go through `useTranslations("draftRedesign")`. Add every new key to BOTH `frontend/src/i18n/messages/en.json` and `frontend/src/i18n/messages/ru.json` under the `draftRedesign` object. Any `t("key", {x})` MUST receive its `{x}` value or next-intl throws (RU plurals require ICU `{n, plural, ...}`).
- **No backend/API/type changes.** All fields already exist on `DraftPlayer`/`DraftPick`/`DraftSession`/`Tournament`.
- **Out of scope:** admin lifecycle controls in the public room; per-team multi-colour palette; admin-picking-for-captain from the public room.
- **Test runner:** `rtk vitest run <path>` (node env). Typecheck gate: `rtk tsc` (i.e. `bunx tsc --noEmit`). Lint: `rtk lint`. `next build` masks TS errors — always use `rtk tsc`.
- **Reduced motion:** every new animation (ring sweep, live-dot pulse) must be disabled under `prefers-reduced-motion` (`motion-reduce:` utilities or a media query).

---

## File Structure

**Create:**
- `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.ts` — pure state→accent mapping + urgency helpers.
- `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.test.ts`
- `frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftClockRing.tsx` — SVG countdown ring.

**Modify (logic):**
- `_lib/draft-workspace-model.ts` (+ `.test.ts`) — extended search, hero normalization, round grouping, off-role division helper.

**Modify (shell/plumbing):**
- `frontend/src/app/draft/[id]/DraftRoom.module.css` — sticky fix.
- `_components/DraftBoard.tsx` — resolve `divisionGrid`, thread it down.
- `_components/CaptainDraftWorkspace.tsx` — pass `divisionGrid`, sticky asides, wire Enter-confirm.
- `_components/SpectatorDraftWorkspace.tsx` — focus + tiering + `divisionGrid`.

**Modify (panels):**
- `_components/CurrentPick.tsx`, `DraftClock.tsx`, `DraftPageHero.tsx`, `PlayerPool.tsx`, `PlayerInspector.tsx`, `TeamRosters.tsx`, `DraftOrder.tsx`, `DraftEventFeed.tsx`, `CaptainShortlist.tsx`, `DraftConnectionStatus.tsx`, `PickCommandBar.tsx`.

**Modify (i18n):** `frontend/src/i18n/messages/{en,ru}.json`.

---

## Phase 0 — Foundations

### Task 1: Fix the broken sticky command bar

**Files:**
- Modify: `frontend/src/app/draft/[id]/DraftRoom.module.css:5-6`

**Interfaces:**
- Produces: nothing consumed by other tasks; standalone shell fix.

- [ ] **Step 1: Change the overflow property**

In `.room`, replace `overflow-x: hidden;` with `overflow-x: clip;`. `clip` still prevents horizontal scroll from the glow/grid but does NOT establish a scroll container, so descendant `position: sticky` regains its scroll range.

```css
.room {
  position: relative;
  isolation: isolate;
  min-height: 100svh;
  overflow-x: clip;
  color: var(--aqt-fg);
  background:
    radial-gradient(circle at 78% -12%, color-mix(in srgb, var(--aqt-teal) 9%, transparent), transparent 34rem),
    var(--aqt-bg);
}
```

- [ ] **Step 2: Typecheck (no TS impact, sanity only)**

Run: `cd frontend && rtk tsc`
Expected: no new errors.

- [ ] **Step 3: Manual verify**

Start dev (`cd frontend && bun run dev`), open a live draft as a captain with a long pool, scroll the pool. Expected: `PickCommandBar` stays pinned to the viewport bottom (was scrolling away). Verify on a narrow (mobile) viewport too.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/app/draft/[id]/DraftRoom.module.css
rtk git commit -m "fix(draft): restore sticky command bar (overflow-x clip on room)"
```

---

### Task 2: Visual state→accent model (pure, TDD)

**Files:**
- Create: `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.ts`
- Test: `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.test.ts`

**Interfaces:**
- Produces:
  - `type DraftAccent = "live" | "paused" | "blocked" | "urgent" | "done" | "idle"`
  - `resolveDraftAccent(board: DraftBoard, opts?: { urgentMs?: number; nowMs?: number }): DraftAccent`
  - `accentToken(accent: DraftAccent): string` → returns the CSS var literal, e.g. `"var(--aqt-teal)"`.
  - Consumed by Tasks 6, 7, 14.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { resolveDraftAccent, accentToken } from "./draft-visual";
import type { DraftBoard } from "@/types/draft.types";

function board(partial: Partial<DraftBoard["session"]>, currentExpires?: string | null): DraftBoard {
  return {
    session: { status: "live", blocked_reason: null, ...partial } as DraftBoard["session"],
    teams: [], picks: [], players: [],
    current_pick: currentExpires === undefined ? null : ({ clock_expires_at: currentExpires } as any),
    server_time: "", last_event_id: null,
  } as DraftBoard;
}

describe("resolveDraftAccent", () => {
  it("maps paused → paused", () => {
    expect(resolveDraftAccent(board({ status: "paused" }))).toBe("paused");
  });
  it("maps role_shortage block → blocked", () => {
    expect(resolveDraftAccent(board({ status: "live", blocked_reason: "role_shortage" }))).toBe("blocked");
  });
  it("maps completed → done", () => {
    expect(resolveDraftAccent(board({ status: "completed" }))).toBe("done");
  });
  it("maps live with plenty of time → live", () => {
    const now = 1_000_000;
    const expires = new Date(now + 30_000).toISOString();
    expect(resolveDraftAccent(board({ status: "live" }, expires), { nowMs: now })).toBe("live");
  });
  it("maps live under the urgent threshold → urgent", () => {
    const now = 1_000_000;
    const expires = new Date(now + 4_000).toISOString();
    expect(resolveDraftAccent(board({ status: "live" }, expires), { nowMs: now, urgentMs: 10_000 })).toBe("urgent");
  });
  it("maps setup/ready (no clock) → idle", () => {
    expect(resolveDraftAccent(board({ status: "ready" }))).toBe("idle");
  });
  it("accentToken returns a css var", () => {
    expect(accentToken("blocked")).toBe("var(--aqt-live)");
    expect(accentToken("live")).toBe("var(--aqt-teal)");
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd frontend && rtk vitest run "src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.test.ts"`
Expected: FAIL — module not found / exports undefined.

- [ ] **Step 3: Implement**

```ts
import type { DraftBoard } from "@/types/draft.types";
import { remainingMs } from "./draft-logic";

export type DraftAccent = "live" | "paused" | "blocked" | "urgent" | "done" | "idle";

const DEFAULT_URGENT_MS = 10_000;

export function resolveDraftAccent(
  board: DraftBoard,
  opts: { urgentMs?: number; nowMs?: number } = {}
): DraftAccent {
  const { session, current_pick } = board;
  if (session.blocked_reason === "role_shortage") return "blocked";
  if (session.status === "paused") return "paused";
  if (session.status === "completed") return "done";
  if (session.status !== "live" || !current_pick?.clock_expires_at) return "idle";
  const now = opts.nowMs ?? Date.now();
  const ms = remainingMs(current_pick.clock_expires_at, now);
  return ms > 0 && ms <= (opts.urgentMs ?? DEFAULT_URGENT_MS) ? "urgent" : "live";
}

export function accentToken(accent: DraftAccent): string {
  switch (accent) {
    case "live": return "var(--aqt-teal)";
    case "paused": return "var(--aqt-amber)";
    case "blocked":
    case "urgent": return "var(--aqt-live)";
    case "done": return "var(--aqt-support)";
    case "idle": return "var(--aqt-fg-faint)";
  }
}
```

> NOTE: `remainingMs(expiresAt, now)` already exists in `./draft-logic` (used by `DraftClock`). Verify its signature there before implementing; it takes `(expiresAt: string, now: number)`.

- [ ] **Step 4: Run test, verify it passes**

Run: `cd frontend && rtk vitest run "src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.test.ts"`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.ts" "frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-visual.test.ts"
rtk git commit -m "feat(draft): add state→accent visual model"
```

---

### Task 3: Extend pool model — search, hero normalization, round grouping, off-role division (pure, TDD)

**Files:**
- Modify: `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-workspace-model.ts`
- Test: `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-workspace-model.test.ts`

**Interfaces:**
- Produces:
  - Extended `filterDraftPlayers` — search now also matches `sub_role` and role labels (tank/dps/support), not just `battle_tag`. Signature unchanged.
  - `normalizeTopHeroes(entries: DraftPlayer["role_top_heroes"][string] | undefined): { slug: string; imagePath: string | null }[]`
  - `roleTopHeroes(player: DraftPlayer, role: DraftRole): { slug: string; imagePath: string | null }[]`
  - `interface DraftRoundGroup { round: number; picks: DraftPick[] }` + `groupPicksByRound(picks: DraftPick[]): DraftRoundGroup[]`
  - `rosterRoleForPlayer(player: DraftPlayer, picks: DraftPick[]): DraftRole` — the drafted (target) role if the player was picked, else `primary_role`.
  - `rosterRankForPlayer(player: DraftPlayer, role: DraftRole): number | null` — `role_ranks[role] ?? rank_value`.
  - Consumed by Tasks 8, 9, 10, 11, 12.

- [ ] **Step 1: Add failing tests (append to existing test file)**

```ts
import {
  filterDraftPlayers, normalizeTopHeroes, roleTopHeroes,
  groupPicksByRound, rosterRoleForPlayer, rosterRankForPlayer,
} from "./draft-workspace-model";
import type { DraftPick, DraftPlayer } from "@/types/draft.types";

const mkPlayer = (p: Partial<DraftPlayer>): DraftPlayer => ({
  id: 1, session_id: 1, user_id: null, battle_tag: "Ana#1", primary_role: "support",
  sub_role: null, is_flex: false, division_number: null, rank_value: 3000,
  status: "available", is_captain: false, drafted_by_team_id: null,
  secondary_roles_json: null, role_ranks: {}, role_top_heroes: {}, additional_info: {},
  version: 1, ...p,
});

describe("extended filterDraftPlayers search", () => {
  it("matches on sub_role", () => {
    const players = [mkPlayer({ id: 1, battle_tag: "Zed", sub_role: "hitscan" }), mkPlayer({ id: 2, battle_tag: "Boo", sub_role: "flex" })];
    const out = filterDraftPlayers(players, { role: "all", sort: "rank", query: "hitscan" });
    expect(out.map((p) => p.id)).toEqual([1]);
  });
  it("matches on role label", () => {
    const players = [mkPlayer({ id: 1, primary_role: "tank" }), mkPlayer({ id: 2, primary_role: "support" })];
    const out = filterDraftPlayers(players, { role: "all", sort: "rank", query: "tank" });
    expect(out.map((p) => p.id)).toEqual([1]);
  });
});

describe("normalizeTopHeroes", () => {
  it("normalizes string + object entries", () => {
    expect(normalizeTopHeroes(["ana", { slug: "kiriko", image_path: "/k.png" }])).toEqual([
      { slug: "ana", imagePath: null },
      { slug: "kiriko", imagePath: "/k.png" },
    ]);
  });
  it("handles undefined", () => {
    expect(normalizeTopHeroes(undefined)).toEqual([]);
  });
});

describe("groupPicksByRound", () => {
  it("groups and sorts by round then pick_in_round", () => {
    const picks = [
      { id: 3, round_no: 2, pick_in_round: 1, overall_no: 3 },
      { id: 1, round_no: 1, pick_in_round: 1, overall_no: 1 },
      { id: 2, round_no: 1, pick_in_round: 2, overall_no: 2 },
    ] as DraftPick[];
    const groups = groupPicksByRound(picks);
    expect(groups.map((g) => g.round)).toEqual([1, 2]);
    expect(groups[0].picks.map((p) => p.id)).toEqual([1, 2]);
  });
});

describe("roster role/rank", () => {
  it("uses drafted target role over primary", () => {
    const player = mkPlayer({ id: 5, primary_role: "support", role_ranks: { dps: 3500, support: 3000 } });
    const picks = [{ id: 9, picked_player_id: 5, target_role: "dps" }] as DraftPick[];
    expect(rosterRoleForPlayer(player, picks)).toBe("dps");
    expect(rosterRankForPlayer(player, "dps")).toBe(3500);
  });
  it("falls back to primary role + rank_value", () => {
    const player = mkPlayer({ id: 6, primary_role: "tank", rank_value: 2800, role_ranks: {} });
    expect(rosterRoleForPlayer(player, [])).toBe("tank");
    expect(rosterRankForPlayer(player, "tank")).toBe(2800);
  });
});
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd frontend && rtk vitest run "src/app/(site)/tournaments/[id]/draft/_lib/draft-workspace-model.test.ts"`
Expected: FAIL — new exports undefined; sub_role/label search returns empty.

- [ ] **Step 3: Implement**

Extend `filterDraftPlayers`'s predicate and add the new exports. Role labels are matched language-agnostically against the role keys `tank/dps/support` (lowercased). Append:

```ts
const ROLE_LABELS: Record<DraftRole, string[]> = {
  tank: ["tank"],
  dps: ["dps", "damage"],
  support: ["support", "sup", "heal"],
};

// inside filterDraftPlayers predicate, replace the name-only query check:
const haystack = [
  player.battle_tag ?? `#${player.id}`,
  player.sub_role ?? "",
  ...[player.primary_role, ...((player.secondary_roles_json ?? []) as DraftRole[])]
    .flatMap((r) => ROLE_LABELS[r] ?? [r]),
].join(" ").toLocaleLowerCase();
return (filters.role === "all" || roles.has(filters.role)) && (!query || haystack.includes(query));

export function normalizeTopHeroes(
  entries: DraftPlayer["role_top_heroes"][string] | undefined
): { slug: string; imagePath: string | null }[] {
  if (!entries) return [];
  return entries.map((e) =>
    typeof e === "string" ? { slug: e, imagePath: null } : { slug: e.slug, imagePath: e.image_path ?? null }
  );
}

export function roleTopHeroes(player: DraftPlayer, role: DraftRole) {
  return normalizeTopHeroes(player.role_top_heroes?.[role]);
}

export interface DraftRoundGroup {
  round: number;
  picks: DraftPick[];
}

export function groupPicksByRound(picks: DraftPick[]): DraftRoundGroup[] {
  const byRound = new Map<number, DraftPick[]>();
  for (const pick of picks) {
    const list = byRound.get(pick.round_no) ?? [];
    list.push(pick);
    byRound.set(pick.round_no, list);
  }
  return [...byRound.entries()]
    .sort(([a], [b]) => a - b)
    .map(([round, list]) => ({
      round,
      picks: [...list].sort((l, r) => l.pick_in_round - r.pick_in_round || l.overall_no - r.overall_no),
    }));
}

export function rosterRoleForPlayer(player: DraftPlayer, picks: DraftPick[]): DraftRole {
  const pick = picks.find((p) => p.picked_player_id === player.id && p.target_role != null);
  return (pick?.target_role as DraftRole | undefined) ?? player.primary_role;
}

export function rosterRankForPlayer(player: DraftPlayer, role: DraftRole): number | null {
  return player.role_ranks?.[role] ?? player.rank_value ?? null;
}
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd frontend && rtk vitest run "src/app/(site)/tournaments/[id]/draft/_lib/draft-workspace-model.test.ts"`
Expected: PASS (existing + new tests).

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-workspace-model.ts" "frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-workspace-model.test.ts"
rtk git commit -m "feat(draft): extend pool model (search, heroes, rounds, off-role rank)"
```

---

### Task 4: Thread the tournament DivisionGrid through the room

**Files:**
- Modify: `_components/DraftBoard.tsx` (resolve grid, pass to both workspaces)
- Modify: `_components/CaptainDraftWorkspace.tsx` (accept `divisionGrid`, pass to `PlayerPool`, `PlayerInspector`, `TeamRosters`, `DraftOrder`)
- Modify: `_components/SpectatorDraftWorkspace.tsx` (accept `divisionGrid`, pass to `TeamRosters`, `DraftOrder`)

**Interfaces:**
- Produces: a `divisionGrid: DivisionGrid` prop on `CaptainDraftWorkspace`, `SpectatorDraftWorkspace`, and (Tasks 8/10/11/12) `PlayerPool`, `PlayerInspector`, `TeamRosters`, `DraftOrder`.
- Consumes: `DivisionGrid` type from `@/types/workspace.types`; `getDefaultDivisionGrid` from `@/lib/division-grid`.

- [ ] **Step 1: Resolve the grid in DraftBoard**

In `DraftBoard.tsx`, add imports and a memo, then pass `divisionGrid` to both workspace components:

```tsx
import { getDefaultDivisionGrid } from "@/lib/division-grid";
import type { DivisionGrid } from "@/types/workspace.types";

// inside DraftBoard, near other useMemo calls:
const divisionGrid: DivisionGrid = useMemo(
  () =>
    tournament.division_grid_version?.tiers
      ? { tiers: tournament.division_grid_version.tiers }
      : getDefaultDivisionGrid(),
  [tournament.division_grid_version]
);
```

Pass `divisionGrid={divisionGrid}` to `<CaptainDraftWorkspace .../>` and `<SpectatorDraftWorkspace .../>`.

> NOTE: verify `getDefaultDivisionGrid` is exported from `@/lib/division-grid` (it is — used by `useCurrentWorkspace`). `DivisionGrid` shape is `{ tiers: ... }`.

- [ ] **Step 2: Accept + forward in CaptainDraftWorkspace**

Add `divisionGrid: DivisionGrid` to `CaptainDraftWorkspaceProps`. Forward it into the `pool`, `team`, and `order` elements and the desktop `PlayerInspector` instances (props added in Tasks 8/10/11/12 — for now add the prop to the interface and to each child JSX call so the wiring compiles once those tasks land). Import `DivisionGrid` from `@/types/workspace.types`.

- [ ] **Step 3: Accept + forward in SpectatorDraftWorkspace**

Add `divisionGrid: DivisionGrid` to its props; forward to `<TeamRosters>` and `<DraftOrder>`.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && rtk tsc`
Expected: errors ONLY about `divisionGrid` not yet accepted by `PlayerPool`/`PlayerInspector`/`TeamRosters`/`DraftOrder` (those props are added in later tasks). If you are executing strictly task-by-task, temporarily hold the child `divisionGrid=` props until each child task adds the prop, OR land Tasks 8/10/11/12 in the same batch. Prefer: land Task 4 wiring together with Task 11 (`TeamRosters`) first so `rtk tsc` is green at each commit.

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftBoard.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/CaptainDraftWorkspace.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/SpectatorDraftWorkspace.tsx"
rtk git commit -m "feat(draft): thread tournament division grid through the room"
```

---

## Phase 1 — Focus tier (Ярус 1)

### Task 5: DraftClockRing component

**Files:**
- Create: `frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftClockRing.tsx`

**Interfaces:**
- Produces: `DraftClockRing({ expiresAt, paused, totalSeconds, accent }: { expiresAt: string | null; paused: boolean; totalSeconds: number; accent: DraftAccent })` — an SVG ring + centered seconds. Reuses `remainingMs`/`isUrgent` from `_lib/draft-logic`, colour from `accentToken`.
- Consumed by Task 6 (`CurrentPick`).

- [ ] **Step 1: Implement the ring**

```tsx
"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { isUrgent, remainingMs } from "../_lib/draft-logic";
import { accentToken, type DraftAccent } from "../_lib/draft-visual";

interface DraftClockRingProps {
  expiresAt: string | null;
  paused: boolean;
  totalSeconds: number;
  accent: DraftAccent;
}

const SIZE = 88;
const STROKE = 6;
const R = (SIZE - STROKE) / 2;
const C = 2 * Math.PI * R;

export function DraftClockRing({ expiresAt, paused, totalSeconds, accent }: DraftClockRingProps) {
  const t = useTranslations();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (paused || !expiresAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [paused, expiresAt]);

  const ms = expiresAt && now != null ? Math.max(0, remainingMs(expiresAt, now)) : null;
  const seconds = ms == null ? null : Math.ceil(ms / 1000);
  const frac = ms == null || totalSeconds <= 0 ? 0 : Math.min(1, ms / (totalSeconds * 1000));
  const urgent = ms != null && isUrgent(ms);
  const color = paused ? "var(--aqt-amber)" : accentToken(accent);

  return (
    <div className="relative grid place-items-center" style={{ width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE} className="-rotate-90" aria-hidden>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="var(--aqt-border)" strokeWidth={STROKE} />
        <circle
          cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke={color} strokeWidth={STROKE}
          strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - frac)}
          className="transition-[stroke-dashoffset] duration-200 motion-reduce:transition-none"
        />
      </svg>
      <span
        className={`absolute font-onest text-xl font-semibold tabular-nums ${urgent ? "animate-pulse motion-reduce:animate-none" : ""}`}
        style={{ color }}
      >
        {paused ? t("draft.clock.pauseCompact") : seconds == null ? "--" : `${seconds}`}
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && rtk tsc`
Expected: PASS (component is self-contained; `t("draft.clock.pauseCompact")` key already exists — used by `DraftClock`).

- [ ] **Step 3: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftClockRing.tsx"
rtk git commit -m "feat(draft): add countdown ring clock"
```

---

### Task 6: CurrentPick → state-led focal card with ring

**Files:**
- Modify: `_components/CurrentPick.tsx`

**Interfaces:**
- Consumes: `resolveDraftAccent`/`accentToken` (Task 2), `DraftClockRing` (Task 5).
- Produces: focal card is the single home of the live clock.

- [ ] **Step 1: Rebuild CurrentPick as the focal card**

Replace the flat section with an elevated card whose accent ring/border follows `resolveDraftAccent(board)`. Keep the existing `HeroCoord` "yourTurn/currentPick" eyebrow. Put `DraftClockRing` on the right (replacing the inline `DraftClock` text). When `isMyPick`, show a prominent "выбери игрока ниже" call using i18n `t("focalPickPrompt")`. Keep the paused/blocked reason but render it at card-level with the accent colour (not a tiny sidebar note). Key structure:

```tsx
const accent = resolveDraftAccent(board);
const accentColor = accentToken(accent);
// card wrapper:
<section
  className="rounded-2xl border bg-[color:var(--aqt-card)] p-5 shadow-lg"
  style={{ borderColor: `color-mix(in srgb, ${accentColor} 45%, var(--aqt-border))` }}
  aria-labelledby="current-pick-heading"
>
  <span aria-hidden className="mb-4 block h-0.5 w-12 rounded" style={{ background: accentColor }} />
  {/* left: eyebrow + team name + pick meta; right: <DraftClockRing
        expiresAt={current?.clock_expires_at ?? null}
        paused={board.session.status === "paused"}
        totalSeconds={board.session.pick_time_seconds}
        accent={accent} /> */}
  {/* when isMyPick && accent !== "blocked": <p style={{color: accentColor}}>{t("focalPickPrompt")}</p> */}
  {/* blocked/paused reason line, accent-coloured, text-sm */}
</section>
```

Use `board.session.pick_time_seconds` for the ring total (exists on `DraftSession`).

- [ ] **Step 2: Add i18n keys**

Add to `draftRedesign` in both `en.json`/`ru.json`: `focalPickPrompt` (en: "Select a player below to pick", ru: "Выберите игрока ниже, чтобы сделать пик"). (`yourTurn`, `currentPick`, `pickMeta`, `noActivePick`, `pickIdle`, `roleShortagePaused`, `organizerPaused` already exist.)

- [ ] **Step 3: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: force each state (live/your-turn/paused/blocked/completed) and confirm the accent colour + ring + prompt change and the card visually dominates the workspace.

- [ ] **Step 4: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/CurrentPick.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): state-led focal current-pick card with ring"
```

---

### Task 7: DraftPageHero — drop duplicate clock, add progress pips + live pill

**Files:**
- Modify: `_components/DraftPageHero.tsx`

**Interfaces:**
- Consumes: nothing new beyond board data.
- Produces: hero no longer renders a clock (dedup — clock now lives only in `CurrentPick`).

- [ ] **Step 1: Replace the timeLeft stat with pips**

Remove the `HeroStat label={t("timeLeft")}` block (and the `DraftClock` import if now unused). Replace the third stat slot with a pick-map: a horizontal strip of small dots, one per pick, coloured by status (`completed`/`autopicked`→`--aqt-support`, `on_clock`→accent teal with pulse, else faint), each with a `title` = team/player. Keep `progress` (`completed/total`) and `onClock` stats.

```tsx
// pips
<div className="flex flex-wrap gap-1" aria-label={t("progress")}>
  {board.picks.map((pick) => {
    const done = ["completed", "autopicked", "skipped"].includes(pick.status);
    const onClock = pick.status === "on_clock";
    return (
      <span key={pick.id}
        title={`#${pick.overall_no}`}
        className={`h-1.5 w-1.5 rounded-full ${
          done ? "bg-[color:var(--aqt-support)]"
          : onClock ? "bg-[color:var(--aqt-teal)] animate-pulse motion-reduce:animate-none"
          : "bg-[color:var(--aqt-fg-faint)]"
        }`} />
    );
  })}
</div>
```

Make the status pill "live" (pulsing dot) when `session.status === "live"`.

- [ ] **Step 2: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS (ensure no unused `DraftClock`/`timeLeft` references).
Manual: hero shows pips + progress + on-clock team, NO clock; clock appears only in the focal card.

- [ ] **Step 3: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftPageHero.tsx"
rtk git commit -m "feat(draft): hero progress pips + live pill, drop duplicate clock"
```

---

## Phase 2 — Working area: pool + dossier (Ярус 2)

### Task 8: PlayerPool — selection highlight, division chip, hero avatars, role/sub_role/flex, profile link

**Files:**
- Modify: `_components/PlayerPool.tsx`

**Interfaces:**
- Consumes: `divisionGrid` (Task 4), `roleTopHeroes`/`normalizeTopHeroes` (Task 3), `resolveDivisionFromRank`/`getDivisionLabel` (`@/lib/division-grid`), `PlayerDivisionIcon`, `AvatarStack`, `getHeroIconUrl`.
- Produces: `divisionGrid: DivisionGrid` prop on `PlayerPool`.

- [ ] **Step 1: Add the prop + imports**

Add `divisionGrid: DivisionGrid` to `PlayerPoolProps`. Import `PlayerDivisionIcon`, `resolveDivisionFromRank`, `getDivisionLabel`, `AvatarStack`, `getHeroIconUrl`, `roleTopHeroes`, `DivisionGrid`.

- [ ] **Step 2: Restyle the player row**

Per player card: (a) selected row → filled tint `bg-[color:var(--aqt-teal)]/10` + role-tinted left border instead of the bare 2px line; (b) replace the raw `rank_value` span with a right-aligned division chip:

```tsx
const division = player.division_number ?? resolveDivisionFromRank(divisionGrid, player.rank_value);
// chip:
{division != null ? (
  <span className="inline-flex items-center gap-1" title={[getDivisionLabel(divisionGrid, division), player.rank_value ? `${player.rank_value} SR` : null].filter(Boolean).join(" · ")}>
    <PlayerDivisionIcon division={division} width={26} height={26} className="h-6 w-6 object-contain" />
  </span>
) : <span className="text-[color:var(--aqt-fg-faint)]">—</span>}
```

(c) primary role icon larger + secondary roles as smaller badges; (d) `sub_role` + `is_flex` mini-badges; (e) hero avatars for the primary role via `AvatarStack` of `roleTopHeroes(player, player.primary_role)` mapped through `getHeroIconUrl(slug, imagePath)`; (f) wrap the battle_tag in a link to `/users/{player.user_id ?? battle_tag}` (match how other pages build the profile href — check an existing roster link; if only `user_id` is available and null, render plain text).

> NOTE on profile href: confirm the canonical user route (`/users/{slug}`) and what slug the app uses (id vs battle_tag). Reuse the same helper other components use for user links; do not invent a route.

- [ ] **Step 3: Add i18n keys** for any new labels (`flex`, `subRolePrefix` if needed). Reuse existing `roles.*`.

- [ ] **Step 4: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: pool rows show division icons (not SR numbers), hero avatars, role badges, sub_role/flex; selected row has a clear filled highlight; names link to profiles.

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/PlayerPool.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): enrich pool rows (division, heroes, roles, selection)"
```

---

### Task 9: PlayerPool filters — hero filter + per-role counts + wired extended search

**Files:**
- Modify: `_components/PlayerPool.tsx`
- Modify: `_components/CaptainDraftWorkspace.tsx` (pass hero-filter state if lifted; otherwise keep local)

**Interfaces:**
- Consumes: extended `filterDraftPlayers` (already active from Task 3), `role_top_heroes`.
- Produces: pool filtered by selected hero slugs (local `useState<Set<string>>`), role filter buttons annotated with available counts.

- [ ] **Step 1: Per-role counts on the role Select**

Compute counts from `totalPlayers` set per role and append to each `SelectItem` label, e.g. `t("roles.tank")` + ` (${count})`. Counts derive from the unfiltered available players (pass a `roleCounts: Record<DraftRole, number>` computed in `CaptainDraftWorkspace` or from `players` prop).

- [ ] **Step 2: Hero filter popover**

Add a `Popover` (`@/components/ui/popover`) trigger "Heroes (n)". Inside: a searchable multi-select list of hero slugs present across the available pool's `role_top_heroes`, each with its `getHeroIconUrl` avatar; toggling adds/removes from a local `Set<string>`. Apply as an extra client-side filter after `filterDraftPlayers`: keep a player if the set is empty OR any of the player's normalized hero slugs is in the set. Add a "clear" action.

- [ ] **Step 3: i18n keys** `heroFilter`, `heroFilterClear`, `heroFilterCount` (ICU: `{count, plural, ...}` for RU).

- [ ] **Step 4: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: role buttons show counts; hero filter narrows the pool; search matches sub_role/role words; clear resets.

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/PlayerPool.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/CaptainDraftWorkspace.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): pool hero filter + per-role counts"
```

---

### Task 10: PlayerInspector → rich selected-player dossier

**Files:**
- Modify: `_components/PlayerInspector.tsx`

**Interfaces:**
- Consumes: `divisionGrid` (Task 4), `roleTopHeroes` (Task 3), division helpers, `AvatarStack`, `getHeroIconUrl`, `PlayerDivisionIcon`.
- Produces: `divisionGrid: DivisionGrid` prop on `PlayerInspector`.

- [ ] **Step 1: Add prop + build the dossier**

Add `divisionGrid: DivisionGrid`. Keep the empty-state and the close button. Rebuild the body as a dossier:
- Header: name (profile link), `#id`, captain marker (`Crown` when `is_captain`), header division icon + label (from `rank_value`/`division_number`).
- Badges row: `sub_role`, `is_flex` (when true), secondary roles.
- **Per-role list:** for each of `playerRoles(player)`, a row with: role icon (role tint), `role_ranks[role]` as `{SR} + PlayerDivisionIcon` (via `resolveDivisionFromRank(divisionGrid, rank)`), and `AvatarStack` of `roleTopHeroes(player, role)`. Keep the existing safe/blocked role selection (the row IS the role toggle — preserve `onRoleChange`, `aria-pressed`, disabled-when-blocked, `Ban`/`ShieldCheck`).
- Note block: `additional_info.notes` when present (guard type: it's `Record<string, unknown>`, read `notes` as string if `typeof === "string"`).
- Keep the blocked-reason explanation list from the current implementation.

- [ ] **Step 2: i18n keys** `captain`, `note`, `secondaryRoles`, `flex` (reuse existing where present).

- [ ] **Step 3: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: selecting a player shows the full dossier — per-role SR + division + heroes, sub_role/flex, note, captain marker; role selection still gates on safety.

- [ ] **Step 4: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/PlayerInspector.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): rich selected-player dossier inspector"
```

---

## Phase 3 — Rosters, order, presence

### Task 11: TeamRosters — tournament grid, off-role division, average, slot-fill, empty slots, on-clock highlight

**Files:**
- Modify: `_components/TeamRosters.tsx`

**Interfaces:**
- Consumes: `divisionGrid` (Task 4), `rosterRoleForPlayer`/`rosterRankForPlayer` (Task 3), division helpers.
- Produces: `divisionGrid: DivisionGrid` prop on `TeamRosters` (replaces internal `useDivisionGrid()`).

- [ ] **Step 1: Swap grid source + off-role rank**

Add `divisionGrid: DivisionGrid`, `picks: DraftPick[]` (needed for drafted role) props; remove `useDivisionGrid()`. Per roster row compute `role = rosterRoleForPlayer(player, picks)`, `rank = rosterRankForPlayer(player, role)`, `division = player.division_number ?? resolveDivisionFromRank(divisionGrid, rank)`, and show the role icon for `role` (not `primary_role`).

- [ ] **Step 2: Team stats + slot fill + empty slots + on-clock**

Add per team: a header stat with average-rank → division icon (avg of roster `rank_value`s), role-fill counts `{filled}/{target}` per role (target from `session.team_size` split or `settings_json`; if not available, target = number of rounds per role — use `Math.ceil(team_size/3)` as a safe default and note it), and pad the roster to `team_size` with numbered "Open slot" rows. Highlight the team whose id === `board.current_pick.draft_team_id` (pass `onClockTeamId?: number | null` prop) with a teal ring + "on the clock" label.

> `ponytail:` role-target defaults to `ceil(team_size/3)` per role when `settings_json` has no explicit role targets — upgrade to real targets if the session exposes them.

- [ ] **Step 3: Update call sites** — `CaptainDraftWorkspace` and `SpectatorDraftWorkspace` pass `divisionGrid`, `picks`, `onClockTeamId={board.current_pick?.draft_team_id ?? null}`.

- [ ] **Step 4: i18n keys** `teamAverage`, `openSlot`, `onTheClock`, `roleFill`.

- [ ] **Step 5: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: off-role picks show the drafted-role rank; team average + slot fill + empty slots render; on-clock team is highlighted.

- [ ] **Step 6: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/TeamRosters.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/CaptainDraftWorkspace.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/SpectatorDraftWorkspace.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): richer team rosters (grid, off-role, avg, slots, on-clock)"
```

---

### Task 12: DraftOrder — round grouping, role-pill, division icon, quiet header

**Files:**
- Modify: `_components/DraftOrder.tsx`

**Interfaces:**
- Consumes: `groupPicksByRound` (Task 3), `divisionGrid` (Task 4), division helpers.
- Produces: `divisionGrid: DivisionGrid` prop on `DraftOrder`.

- [ ] **Step 1: Group + enrich**

Add `divisionGrid: DivisionGrid`. Replace the flat `<ol>` with round groups from `groupPicksByRound(picks)`; each group gets a small round header (`t("round", {n})`). Per pick row: keep overall_no + team/player + status glyph; add a `target_role` role-pill (role icon + label, role tint) and, for picked players, a small division icon via `resolveDivisionFromRank(divisionGrid, player.rank_value)`. Keep `compact` scroll behaviour.

- [ ] **Step 2: Quiet header** — this panel is Ярус 3: shrink the heading (`text-sm` muted, drop the `HeroCoord` "sequence" eyebrow).

- [ ] **Step 3: i18n keys** `round` (ICU/param `{n}`).

- [ ] **Step 4: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: picks grouped by round with role-pills + division icons; header visually recedes.

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftOrder.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): draft order round grouping + role-pill + division"
```

---

### Task 13: DraftConnectionStatus — per-captain presence bubbles

**Files:**
- Modify: `_components/DraftConnectionStatus.tsx`

**Interfaces:**
- Consumes: `board.teams` (captain_auth_user_id), `presence.users`.
- Produces: unchanged prop shape.

- [ ] **Step 1: Render per-captain bubbles**

Below the aggregate line, map `teams` → a bubble per captain: team initials, name, online/offline dot (online if `presence.users[captain_auth_user_id]` exists), and a "you" marker when `captain_auth_user_id === currentUserId` (add `currentUserId?: number | null` prop; pass `user?.id` from `DraftBoard` via the workspace, or read where connection status is rendered in `DraftBoard`). Keep the aggregate "captains online X/total" + viewer count as a summary.

- [ ] **Step 2: i18n keys** `you`, `captainOnline`, `captainOffline`.

- [ ] **Step 3: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: each captain shows an online/offline bubble; your own is marked.

- [ ] **Step 4: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftConnectionStatus.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftBoard.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): per-captain presence bubbles"
```

---

## Phase 4 — Command bar, tiering, spectator parity

### Task 14: PickCommandBar — ready detail (SR/division), elevation, readiness colour, Enter-to-confirm

**Files:**
- Modify: `_components/PickCommandBar.tsx`
- Modify: `_components/CaptainDraftWorkspace.tsx` (Enter handler + pass division/rank of selection)

**Interfaces:**
- Consumes: `divisionGrid`, selected player + role, `resolveDivisionFromRank`.
- Produces: keyboard Enter opens the review dialog when a valid pick is selected.

- [ ] **Step 1: Enrich the ready state**

Add selection SR + division to the bar: alongside `battle_tag · role`, show `role_ranks[role] ?? rank_value` + a small `PlayerDivisionIcon`. Colour the bar/button by readiness: ready→teal, blocked/disconnected→amber/rose. Pass `divisionGrid` + selected player from `CaptainDraftWorkspace`.

- [ ] **Step 2: Enter-to-confirm**

In `CaptainDraftWorkspace`, add a `useEffect` global `keydown` listener: on `Enter`, if `confirmAllowed` and the event target is not an input/textarea/select/contenteditable, open the review dialog (lift `reviewOpen` state up, or expose an `onQuickConfirm` that the bar wires to opening its dialog). Keep the safety dialog — Enter only opens it faster. Add an "Enter" hint chip on the review button.

```tsx
useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    const el = e.target as HTMLElement | null;
    if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
    if (el?.isContentEditable) return;
    if (e.key === "Enter" && confirmAllowed) { e.preventDefault(); openReview(); }
  };
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
}, [confirmAllowed, openReview]);
```

- [ ] **Step 3: i18n keys** `enterHint`.

- [ ] **Step 4: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: bar shows SR + division; ready/blocked colours differ; Enter opens the review dialog only when a valid pick is selected and focus isn't in a field.

- [ ] **Step 5: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/PickCommandBar.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/CaptainDraftWorkspace.tsx" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
rtk git commit -m "feat(draft): richer command bar + Enter-to-confirm"
```

---

### Task 15: Panel chrome tiering + sticky side panels

**Files:**
- Modify: `_components/DraftEventFeed.tsx`, `_components/CaptainShortlist.tsx` (quiet Ярус-3 headers)
- Modify: `_components/CaptainDraftWorkspace.tsx` (sticky asides)

**Interfaces:** none new.

- [ ] **Step 1: Quiet reference-panel headers**

In `DraftEventFeed` and `CaptainShortlist` (and confirm `DraftOrder` from Task 12): shrink headings to `text-sm font-medium text-[color:var(--aqt-fg-muted)]`, drop `HeroCoord` eyebrows. These recede as Ярус 3.

- [ ] **Step 2: Sticky asides**

In `CaptainDraftWorkspace`, make the left (`order`) and right (`inspector/shortlist/team`) `<aside>` elements `className="... sticky top-4 self-start max-h-[calc(100svh-2rem)] overflow-y-auto"` so they stay in view while the pool scrolls. Ensure this composes with the Task 1 shell fix (the asides scroll internally; the command bar still sticks to the viewport).

- [ ] **Step 3: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: secondary panels look quieter than pool/rosters; asides stay visible on scroll; command bar still sticky.

- [ ] **Step 4: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftEventFeed.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/CaptainShortlist.tsx" "frontend/src/app/(site)/tournaments/[id]/draft/_components/CaptainDraftWorkspace.tsx"
rtk git commit -m "feat(draft): tier panel chrome + sticky side panels"
```

---

### Task 16: SpectatorDraftWorkspace parity

**Files:**
- Modify: `_components/SpectatorDraftWorkspace.tsx`

**Interfaces:** consumes `divisionGrid` (Task 4).

- [ ] **Step 1: Bring the focus + tiering to spectators**

`CurrentPick` already renders the focal card (shared). Ensure the spectator layout leads with it, keeps the tiered quiet headers for `DraftOrder`/`DraftEventFeed`, and passes `divisionGrid`/`picks`/`onClockTeamId` to `TeamRosters` and `divisionGrid` to `DraftOrder`. Demote the read-only banner to a quiet Ярус-3 note.

- [ ] **Step 2: Typecheck + manual verify**

Run: `cd frontend && rtk tsc` → PASS.
Manual: open the room as a non-captain — same focal card + division icons + tiering as the captain view (minus the pool/command bar).

- [ ] **Step 3: Commit**

```bash
rtk git add "frontend/src/app/(site)/tournaments/[id]/draft/_components/SpectatorDraftWorkspace.tsx"
rtk git commit -m "feat(draft): spectator workspace parity (focus + tiering)"
```

---

### Task 17: Full-room verification pass

**Files:** none (verification + any fixups).

- [ ] **Step 1: Static gates**

Run: `cd frontend && rtk tsc` → PASS.
Run: `cd frontend && rtk lint` → no new errors.
Run: `cd frontend && rtk vitest run "src/app/(site)/tournaments/[id]/draft"` → all draft `_lib` tests PASS.

- [ ] **Step 2: i18n completeness**

Confirm every new key exists in BOTH `en.json` and `ru.json`, RU plural keys use ICU, and no `t("…", {x})` is missing its param (grep the touched components for `t(` and cross-check).

- [ ] **Step 3: Manual matrix**

Verify as captain and as spectator: focal card states (live/your-turn/paused/blocked/urgent/completed); ranks are DivisionGrid icons in pool, inspector, order, rosters (incl. off-role); sticky command bar on long pools (desktop + mobile); hero avatars; Enter-to-confirm gated correctly; `prefers-reduced-motion` disables ring/pulse.

- [ ] **Step 4: Commit any fixups**

```bash
rtk git add -A
rtk git commit -m "chore(draft): room hierarchy verification fixups"
```

---

## Self-Review (author checklist — completed)

**Spec coverage:** T0 fixes → Tasks 1 (sticky), 8/10/11/12 (ranks→DivisionGrid), 11 (off-role). T1 emphasis → Tasks 5,6,7,11(on-clock),15(tiering/sticky asides),8(selection). T2 density → Tasks 8,10 (heroes/per-role/sub_role/flex/links), 6/CurrentPick messaging, "your turn in N" — **gap noted:** the "your turn in N picks" waiting countdown is not its own task; fold into Task 6 CurrentPick (when `!isMyPick` and a `myTeamId` exists, show picks-until-your-turn). Added here as a Task 6 sub-requirement. T3 → Tasks 9 (filters), 12 (order), 13 (presence). Dossier → Task 10. Grid=tournament → Task 4. Enter-confirm → Task 14. Spectator parity → Task 16.

**Placeholder scan:** UI tasks intentionally show key snippets + precise instructions rather than reproducing entire 150-line components verbatim (repo convention: node-env vitest tests pure logic only; components verified via `rtk tsc` + manual matrix). Pure-logic tasks (2,3) carry complete TDD code. Two `NOTE`s call out things to verify against the codebase (profile-href helper, `getDefaultDivisionGrid` export) rather than guessing a route.

**Type consistency:** `divisionGrid: DivisionGrid` prop name used uniformly (Tasks 4,8,10,11,12,14). Helper names match Task 3 exports (`normalizeTopHeroes`, `roleTopHeroes`, `groupPicksByRound`, `rosterRoleForPlayer`, `rosterRankForPlayer`). Accent API (`resolveDraftAccent`, `accentToken`, `DraftAccent`) consistent across Tasks 2,5,6.

**Task 6 addendum (folded gap):** also render a "your turn in N picks" line in `CurrentPick` when it's not the viewer's pick but their team is upcoming — compute from `board.picks` ordered by `overall_no` vs the viewer's `myTeamId` (pass `myTeamId` into `CurrentPick`). i18n key `yourTurnInPicks` (ICU `{n, plural, ...}`).
