// @vitest-environment happy-dom
//
// One claim: a team dragged by its handle is INSERTED where it is dropped, in
// its own group or another one, and every group's seeds stay numbered 1..N.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import adminService from "@/services/admin.service";

import type { Team } from "@/types/team.types";
import type { Stage, StageItem, StageItemInput } from "@/types/tournament.types";

import { StageItemsSection } from "./StageItemsSection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/services/admin.service", () => ({
  default: {
    createStageItem: vi.fn(),
    updateStageItem: vi.fn(),
    createStageItemInput: vi.fn(),
    updateStageItemInput: vi.fn(),
    deleteStageItemInput: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: unknown }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

function input(id: number, overrides: Partial<StageItemInput> = {}): StageItemInput {
  return {
    id,
    stage_item_id: 100,
    slot: 1,
    input_type: "final",
    team_id: 7,
    source_stage_item_id: null,
    source_position: null,
    ...overrides
  };
}

function item(id: number, inputs: StageItemInput[]): StageItem {
  return {
    id,
    stage_id: 10,
    name: `Group ${id}`,
    type: "group",
    order: 0,
    advance_count: null,
    inputs
  };
}

function groupStage(items: StageItem[]): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Groups",
    description: null,
    stage_type: "round_robin",
    max_rounds: 3,
    advance_count: 2,
    advance_upper_count: null,
    order: 0,
    is_active: true,
    is_published: true,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items
  };
}

const teams = [
  { id: 7, name: "Wrong Team" },
  { id: 8, name: "Team 8" },
  { id: 9, name: "Team 9" },
  { id: 10, name: "Team 10" }
] as Team[];

let container: HTMLDivElement;
let root: Root;

async function settle() {
  for (let index = 0; index < 4; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(stage: Stage) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <StageItemsSection
          stage={stage}
          stages={[stage]}
          teams={teams}
          isTeamsLoading={false}
          progress={undefined}
          encountersHref="/admin/encounters"
          onChanged={() => {}}
          onRequestDeleteItem={() => {}}
          onRequestRemoveInput={() => {}}
        />
      </QueryClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.mocked(adminService.updateStageItemInput).mockReset();
});

describe("moving seeded teams", () => {
  it("offers a drag handle on seeded slots only", async () => {
    await mount(
      groupStage([
        item(100, [
          input(501, { team_id: 7 }),
          input(502, { slot: 2, team_id: null, input_type: "empty" })
        ])
      ])
    );

    expect(
      container.querySelector('button[aria-label="Drag Wrong Team to another slot"]')
    ).not.toBeNull();
    expect(container.querySelectorAll('button[aria-label^="Drag "]')).toHaveLength(1);
  });

  describe("dragging with the pointer", () => {
    // happy-dom lays nothing out, so every slot row of THIS test's container gets
    // a 40px band of its own (row i spans y = 50i .. 50i + 40, counted across all
    // groups in DOM order) and everything inside a row shares it. dnd-kit measures
    // the dragged row and the drop targets through this.
    let restoreRect: () => void;
    beforeEach(() => {
      const original = HTMLElement.prototype.getBoundingClientRect;
      HTMLElement.prototype.getBoundingClientRect = function rectOf(this: HTMLElement) {
        const row = this.closest("li");
        const index = row ? [...container.querySelectorAll("li")].indexOf(row) : -1;
        if (index < 0) return original.call(this);
        const top = index * 50;
        return { x: 0, y: top, top, left: 0, right: 500, bottom: top + 40, width: 500, height: 40, toJSON() {} } as DOMRect;
      };
      restoreRect = () => {
        HTMLElement.prototype.getBoundingClientRect = original;
      };
    });
    afterEach(() => restoreRect());

    function pointer(type: string, target: EventTarget, y: number) {
      target.dispatchEvent(
        new PointerEvent(type, { bubbles: true, cancelable: true, isPrimary: true, button: 0, pointerId: 1, clientX: 20, clientY: y })
      );
    }

    /** Picks Wrong Team's grip up at y=20 and walks it through `path`, dropping at the end. */
    async function drag(path: number[]) {
      const grip = container.querySelector('button[aria-label="Drag Wrong Team to another slot"]')!;
      await act(async () => pointer("pointerdown", grip, 20));
      for (const y of path) {
        await act(async () => pointer("pointermove", document, y));
      }
      await act(async () => pointer("pointerup", document, path.at(-1)!));
      await settle();
    }

    /** Each group's rows as rendered: seed number and team. */
    function groups() {
      return [...container.querySelectorAll("ul")].map((list) =>
        [...list.querySelectorAll("li")].map((row) => row.querySelector("span")?.textContent)
      );
    }

    it("inserts a team dragged down its group, shifting the teams it passes up", async () => {
      vi.mocked(adminService.updateStageItemInput).mockResolvedValue({} as never);
      await mount(
        groupStage([
          item(100, [
            input(501, { team_id: 7 }),
            input(502, { slot: 2, team_id: 8 }),
            input(503, { slot: 3, team_id: 9 })
          ])
        ])
      );

      // Onto the third row (y 100..140): a swap would trade places with Team 9.
      await drag([30, 45, 70, 95, 120]);

      expect(vi.mocked(adminService.updateStageItemInput).mock.calls).toEqual([
        [501, { stage_item_id: 100, slot: 3 }]
      ]);
      expect(groups()).toEqual([["#1 Team 8", "#2 Team 9", "#3 Wrong Team"]]);
    });

    it("moves a team into another group and closes the gap it leaves", async () => {
      vi.mocked(adminService.updateStageItemInput).mockResolvedValue({} as never);
      await mount(
        groupStage([
          item(100, [input(501, { team_id: 7 }), input(502, { slot: 2, team_id: 8 })]),
          item(200, [
            input(601, { stage_item_id: 200, team_id: 9 }),
            input(602, { stage_item_id: 200, slot: 2, team_id: 10 })
          ])
        ])
      );

      // Down past Team 8 into the second group, onto its last row.
      await drag([30, 45, 70, 120, 170]);

      expect(vi.mocked(adminService.updateStageItemInput).mock.calls).toEqual([
        [501, { stage_item_id: 200, slot: 3 }]
      ]);
      expect(groups()).toEqual([["#1 Team 8"], ["#1 Team 9", "#2 Team 10", "#3 Wrong Team"]]);
    });
  });
});
