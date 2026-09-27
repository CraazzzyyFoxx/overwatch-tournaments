// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { StandingsArrangeBoard } from "@/components/admin/StandingsArrangeBoard";
import type { Team } from "@/types/team.types";
import type { Standings } from "@/types/tournament.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const setStandingPins = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: { setStandingPins: (...args: unknown[]) => setStandingPins(...args) }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

// The drop is what this pins, not dnd-kit's pointer maths: the list reports a
// reorder the way the kit does — the new array and the dragged item.
let drop: ((next: Standings[], moved: Standings) => void) | undefined;
vi.mock("@/components/kit/SortableRows", () => ({
  SortableRows: ({
    items,
    onReorder,
    children
  }: {
    items: readonly Standings[];
    onReorder: (next: Standings[], moved: Standings) => void;
    children: (item: Standings, index: number) => ReactNode;
  }) => {
    drop = onReorder;
    return <div>{items.map((item, index) => children(item, index))}</div>;
  },
  useSortableRow: () => ({ ref: () => {}, style: {}, handleProps: {}, isDragging: false }),
  SortableGrip: ({ label }: { label: string }) => <button type="button" aria-label={label} />
}));

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>{node}</QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function standing(team_id: number, position: number, is_pinned = false): Standings {
  return {
    id: team_id * 100,
    tournament_id: 42,
    team_id,
    stage_id: 5,
    stage_item_id: 9,
    position,
    overall_position: position,
    matches: 4,
    win: 2,
    draw: 0,
    lose: 2,
    points: 6,
    buchholz: 9,
    full_buchholz: 15,
    tie_group: null,
    is_pinned,
    tb: null,
    score_differential: null,
    ranking_context: null,
    tb_metrics: null,
    source_rule_profile: null,
    tiebreak_order: ["points"],
    // The board renders identity only; the rest of `Team` never reaches it.
    team: { id: team_id, name: `Team ${team_id}`, image_url: null } as unknown as Team,
    tournament: null,
    stage: null,
    stage_item: { id: 9, stage_id: 5, name: "Group A", type: "round_robin", order: 1, advance_count: null, inputs: [] },
    matches_history: []
  };
}

function button(label: string, root: ParentNode = document.body): HTMLButtonElement {
  const found = Array.from(root.querySelectorAll("button")).find(
    (node) => node.textContent?.trim() === label || node.getAttribute("aria-label") === label
  );
  if (!found) throw new Error(`no button ${label}`);
  return found;
}

function board(rows: Standings[], canUpdate = true) {
  return <StandingsArrangeBoard rows={rows} stages={[]} canUpdate={canUpdate} onChanged={() => {}} />;
}

describe("StandingsArrangeBoard", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    drop = undefined;
    setStandingPins.mockReset().mockResolvedValue(undefined);
  });

  it("pins the dropped team and re-pins the already pinned ones at their new places", async () => {
    // Given in scrambled order: the board shows the table by place.
    const rows = [standing(4, 4), standing(3, 3, true), standing(1, 1), standing(2, 2)];
    await mount(board(rows));
    expect(document.body.textContent).toContain("Group A");

    const [one, two, three, four] = [1, 2, 3, 4].map((id) => rows.find((row) => row.team_id === id)!);
    await act(async () => drop!([four, one, two, three], four));
    await flush();

    // Teams 1 and 2 moved too, but they stay unpinned: they keep following results.
    expect(setStandingPins).toHaveBeenCalledTimes(1);
    expect(setStandingPins).toHaveBeenCalledWith(5, {
      stage_item_id: 9,
      pins: [
        { team_id: 4, position: 1 },
        { team_id: 3, position: 4 }
      ]
    });
  });

  it("pins the dragged team, not its neighbour, on an adjacent swap", async () => {
    const rows = [standing(1, 1), standing(2, 2)];
    await mount(board(rows));

    await act(async () => drop!([rows[1], rows[0]], rows[0]));
    await flush();

    expect(setStandingPins).toHaveBeenCalledWith(5, {
      stage_item_id: 9,
      pins: [{ team_id: 1, position: 2 }]
    });
  });

  it("unpins one team and keeps the others where they are", async () => {
    await mount(board([standing(1, 1, true), standing(2, 2), standing(3, 3, true)]));

    await act(async () => button("Unpin Team 1").click());
    await flush();

    expect(setStandingPins).toHaveBeenCalledWith(5, {
      stage_item_id: 9,
      pins: [{ team_id: 3, position: 3 }]
    });
  });

  it("clears every pin of the table only after confirming", async () => {
    await mount(board([standing(1, 1, true), standing(2, 2)]));

    await act(async () => button("Clear pins").click());
    expect(setStandingPins).not.toHaveBeenCalled();

    const dialog = document.body.querySelector('[role="alertdialog"]');
    if (!dialog) throw new Error("no confirmation");
    await act(async () => button("Clear pins", dialog).click());
    await flush();

    expect(setStandingPins).toHaveBeenCalledWith(5, { stage_item_id: 9, pins: [] });
  });

  it("offers no clear when nothing in the table is pinned", async () => {
    await mount(board([standing(1, 1), standing(2, 2)]));
    expect(button("Clear pins").disabled).toBe(true);
  });

  it("is read-only without the update permission", async () => {
    await mount(board([standing(1, 1, true), standing(2, 2)], false));

    const labels = Array.from(document.body.querySelectorAll("button")).map(
      (node) => node.getAttribute("aria-label") ?? node.textContent?.trim()
    );
    expect(labels).toEqual([]);
    // The pin itself stays visible.
    expect(document.body.textContent).toContain("Pinned place");
  });
});
