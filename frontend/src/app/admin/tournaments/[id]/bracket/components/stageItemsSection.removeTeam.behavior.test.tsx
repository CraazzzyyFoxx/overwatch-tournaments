// @vitest-environment happy-dom
//
// One claim: an assigned team slot can be removed, not only swapped.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Team } from "@/types/team.types";
import type { Stage, StageItem } from "@/types/tournament.types";

import { StageItemsSection } from "./StageItemsSection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const deleteStageItemInput = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    createStageItem: vi.fn(),
    updateStageItem: vi.fn(),
    createStageItemInput: vi.fn(),
    updateStageItemInput: vi.fn(),
    deleteStageItemInput: (...args: unknown[]) => deleteStageItemInput(...args)
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

function item(id: number, overrides: Partial<StageItem> = {}): StageItem {
  return {
    id,
    stage_id: 10,
    name: `Group ${id}`,
    type: "group",
    order: 0,
    advance_count: null,
    inputs: [
      {
        id: 501,
        stage_item_id: id,
        slot: 1,
        input_type: "final",
        team_id: 7,
        source_stage_item_id: null,
        source_position: null
      }
    ],
    ...overrides
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
        />
      </QueryClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  deleteStageItemInput.mockReset();
  deleteStageItemInput.mockResolvedValue(undefined);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

describe("remove assigned team", () => {
  it("deletes the slot instead of requiring a swap", async () => {
    await mount(groupStage([item(100)]));

    const remove = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Remove team from slot 1 of Group 100"]'
    );
    if (!remove) throw new Error("No remove button on the assigned slot");

    await act(async () => {
      remove.click();
    });
    await settle();

    expect(deleteStageItemInput).toHaveBeenCalledTimes(1);
    expect(deleteStageItemInput).toHaveBeenCalledWith(501);
  });
});
