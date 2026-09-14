// @vitest-environment happy-dom
//
// One claim: a seeded slot can be dragged onto another slot, and what that
// costs depends on the target — a filled target is a single atomic swap the
// API already does, an empty one is a move that has to empty the source first.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Team } from "@/types/team.types";
import type { Stage, StageItem, StageItemInput } from "@/types/tournament.types";

import { seedSwapRequests, StageItemsSection } from "./StageItemsSection";

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
    split_lower_bracket: false,
    order: 0,
    is_active: true,
    is_published: true,
    is_completed: false,
    settings_json: null,
    challonge_id: null,
    challonge_slug: null,
    items
  };
}

const team = { id: 7, name: "Wrong Team" } as Team;

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
          teams={[team]}
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
});

describe("swapping seeded slots", () => {
  it("swaps two filled slots with the API's own one-call exchange", () => {
    const source = input(501, { team_id: 7 });
    const target = input(502, { id: 502, slot: 2, team_id: 9 });

    // One PATCH: the server puts the displaced team (9) back into slot 501.
    expect(seedSwapRequests(source, target)).toEqual([
      { inputId: 502, data: { team_id: 7, input_type: "final" } }
    ]);
  });

  it("empties the source before filling an empty target", () => {
    const source = input(501, { team_id: 7 });
    const target = input(502, { id: 502, slot: 2, team_id: null, input_type: "empty" });

    // Order matters: filling first would leave the team seated twice.
    expect(seedSwapRequests(source, target)).toEqual([
      { inputId: 501, data: { input_type: "empty" } },
      { inputId: 502, data: { team_id: 7, input_type: "final" } }
    ]);
  });

  it("offers a drag handle on seeded slots only", async () => {
    await mount(
      groupStage([
        item(100, [
          input(501, { team_id: 7 }),
          input(502, { id: 502, slot: 2, team_id: null, input_type: "empty" })
        ])
      ])
    );

    expect(
      container.querySelector('button[aria-label="Drag Wrong Team to another slot"]')
    ).not.toBeNull();
    expect(
      container.querySelectorAll('button[aria-label^="Drag "]')
    ).toHaveLength(1);
  });
});
