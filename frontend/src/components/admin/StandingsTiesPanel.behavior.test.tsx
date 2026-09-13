// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StandingsTiesPanel } from "@/components/admin/StandingsTiesPanel";
import type { Team } from "@/types/team.types";
import type { Stage, Standings } from "@/types/tournament.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const updateStage = vi.fn();
const recalculateStandings = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    updateStage: (...args: unknown[]) => updateStage(...args),
    recalculateStandings: (...args: unknown[]) => recalculateStandings(...args)
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  return document.body;
}

/** Let a mutation's two awaited service calls settle before asserting. */
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function team(id: number, name: string): Team {
  // The panel renders identity only; the rest of `Team` never reaches it.
  return { id, name, image_url: null } as unknown as Team;
}

function standing(overrides: Partial<Standings> & { team_id: number }): Standings {
  return {
    id: overrides.team_id * 100,
    tournament_id: 42,
    stage_id: 5,
    stage_item_id: 9,
    position: 1,
    overall_position: 1,
    matches: 4,
    win: 2,
    draw: 0,
    lose: 2,
    points: 6,
    buchholz: 9,
    full_buchholz: 15,
    tie_group: null,
    tb: null,
    score_differential: null,
    ranking_context: null,
    tb_metrics: null,
    source_rule_profile: null,
    tiebreak_order: ["points", "manual_override"],
    team: team(overrides.team_id, `Team ${overrides.team_id}`),
    tournament: null,
    stage: null,
    stage_item: { id: 9, stage_id: 5, name: "Group A", type: "round_robin", order: 1, advance_count: null, inputs: [] },
    matches_history: [],
    ...overrides
  };
}

/** Teams 7 and 8 sit in one unresolved cluster starting at position 3. */
function tiedRows(): Standings[] {
  return [
    standing({ team_id: 7, position: 3, tie_group: 3 }),
    standing({ team_id: 8, position: 4, tie_group: 3 })
  ];
}

function stage(manualPositions: Record<string, number>): Stage {
  return {
    id: 5,
    tournament_id: 42,
    name: "Group stage",
    description: null,
    stage_type: "round_robin",
    max_rounds: 5,
    advance_count: 2,
    split_lower_bracket: false,
    order: 1,
    is_active: true,
    is_published: true,
    is_completed: false,
    settings_json: {
      tiebreak_order: ["points", "manual_override"],
      manual_positions: manualPositions
    },
    challonge_id: null,
    challonge_slug: null,
    items: []
  };
}

function button(label: string): HTMLButtonElement {
  const found = Array.from(document.body.querySelectorAll("button")).find(
    (node) => node.textContent?.trim() === label || node.getAttribute("aria-label") === label
  );
  if (!found) throw new Error(`no button ${label}`);
  return found;
}

function panel(rows: Standings[], manualPositions: Record<string, number> = { "99": 1 }) {
  return (
    <StandingsTiesPanel
      rows={rows}
      stages={[stage(manualPositions)]}
      tournamentId={42}
      canUpdate
      onChanged={() => {}}
    />
  );
}

describe("StandingsTiesPanel", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    updateStage.mockReset().mockResolvedValue({});
    recalculateStandings.mockReset().mockResolvedValue({});
  });

  it("renders one card per tie cluster, listing the tied teams in order", async () => {
    const body = await mount(panel(tiedRows()));
    expect(body.textContent).toContain("Unresolved ties");
    expect(body.textContent).toContain("3–4");
    expect(body.textContent).toContain("Team 7");
    expect(body.textContent).toContain("Team 8");
  });

  it("stays out of the way when nothing is tied", async () => {
    // A tie is a soft signal: with no cluster the panel must not take space or
    // imply something needs attention.
    const body = await mount(panel([standing({ team_id: 7, position: 3 })]));
    expect(body.textContent).not.toContain("Unresolved ties");
  });

  it("saves the displayed order without a reorder", async () => {
    // The engine assigned this order; locking it is still a save.
    await mount(panel(tiedRows()));
    expect(button("Save order").disabled).toBe(false);

    await act(async () => {
      button("Save order").click();
    });
    await flush();

    expect(updateStage).toHaveBeenCalledWith(5, {
      settings_json: {
        tiebreak_order: ["points", "manual_override"],
        manual_positions: { "99": 1, "7": 3, "8": 4 }
      }
    });
    expect(recalculateStandings).toHaveBeenCalledWith(42);
  });

  it("saves absolute positions for the cluster's teams and keeps other overrides", async () => {
    // Positions are absolute, not offsets, and a save must not wipe an
    // override an organizer set on an unrelated team.
    await mount(panel(tiedRows()));

    await act(async () => {
      button("Move Team 8 up").click();
    });
    await act(async () => {
      button("Save order").click();
    });
    await flush();

    expect(updateStage).toHaveBeenCalledWith(5, {
      settings_json: {
        tiebreak_order: ["points", "manual_override"],
        manual_positions: { "99": 1, "8": 3, "7": 4 }
      }
    });
    // Rows are rebuilt while ranking, so the new order is invisible until this.
    expect(recalculateStandings).toHaveBeenCalledWith(42);
  });

  it("hides Save when the displayed order is already persisted", async () => {
    const body = await mount(panel(tiedRows(), { "99": 1, "7": 3, "8": 4 }));
    expect(body.textContent).toContain("Saved");
    expect(
      Array.from(document.body.querySelectorAll("button")).some(
        (node) => node.textContent?.trim() === "Save order"
      )
    ).toBe(false);
  });

  it("resets only its own cluster's overrides", async () => {
    await mount(panel(tiedRows(), { "99": 1, "7": 4, "8": 3 }));

    await act(async () => {
      button("Clear override").click();
    });
    await flush();

    expect(updateStage).toHaveBeenCalledWith(5, {
      settings_json: {
        tiebreak_order: ["points", "manual_override"],
        manual_positions: { "99": 1 }
      }
    });
    expect(recalculateStandings).toHaveBeenCalledWith(42);
  });
});
