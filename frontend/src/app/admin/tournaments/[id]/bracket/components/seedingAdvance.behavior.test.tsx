// @vitest-environment happy-dom
//
// One claim: how many teams advance can be set per GROUP, not only per stage,
// and both controls live in Seeding.
//
// `Stage.advance_count` is one number for every group in the stage. A tournament
// that takes 3 from a strong group and 2 from the rest had no way to say so, and
// the projection silently multiplied the stage number by the group count. The
// per-group override needs a way in, and clearing the field has to mean "inherit
// the stage again" — an explicit `null`, not an omitted key, which the API reads
// as "leave it alone".
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Stage, StageItem } from "@/types/tournament.types";

import { buildStageUpdatePayload, stageFormFromStage, type StageForm } from "../stageForm";
import { SeedingSection } from "./StageSettingsSections";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const updateStageItem = vi.fn();
const autoWireStage = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    updateStageItem: (...args: unknown[]) => updateStageItem(...args),
    autoWireStage: (...args: unknown[]) => autoWireStage(...args),
    createStageItem: vi.fn(),
    createStageItemInput: vi.fn(),
    updateStageItemInput: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

function item(id: number, overrides: Partial<StageItem> = {}): StageItem {
  return {
    id,
    stage_id: 10,
    name: `Group ${id}`,
    type: "group",
    order: 0,
    advance_count: null,
    advance_upper_count: null,
    inputs: [],
    ...overrides
  };
}

function groupStage(items: StageItem[], overrides: Partial<Stage> = {}): Stage {
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
    items,
    ...overrides
  };
}

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

/** Every draft patch the section handed back, so a test can build the save payload. */
const patches: Partial<StageForm>[] = [];

/** The draft as "Save changes" would see it. */
function draft(stage: Stage): StageForm {
  return patches.reduce<StageForm>(
    (acc, patch) => ({ ...acc, ...patch }),
    stageFormFromStage(stage)
  );
}

async function mount(stage: Stage, extras: { stages?: Stage[] } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Harness() {
    const [form, setForm] = useState<StageForm>(() => stageFormFromStage(stage));
    return (
      <SeedingSection
        stage={stage}
        form={form}
        stages={extras.stages}
        onChange={(patch) => {
          patches.push(patch);
          setForm((current) => ({ ...current, ...patch }));
        }}
        onChanged={() => {}}
      />
    );
  }
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>
    );
  });
  await settle();
}

/** The ids are `useId()`-prefixed, so the suffix is the only stable handle. */
function advanceInput(stageItemId: number) {
  const input = container.querySelector<HTMLInputElement>(`input[id$="-advance-${stageItemId}"]`);
  if (!input) throw new Error(`No advance field for item ${stageItemId}`);
  return input;
}

function upperInput(stageItemId: number) {
  const input = container.querySelector<HTMLInputElement>(`input[id$="-upper-${stageItemId}"]`);
  if (!input) throw new Error(`No upper-bracket field for item ${stageItemId}`);
  return input;
}

function stageUpperInput() {
  const input = container.querySelector<HTMLInputElement>('input[id$="-advance-upper"]');
  if (!input) throw new Error("No stage-wide upper-bracket field");
  return input;
}

async function typeAndBlur(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  // React delegates `onBlur` off the bubbling `focusout` event, not `blur`.
  await act(async () => {
    input.dispatchEvent(new Event("focusout", { bubbles: true }));
  });
  await settle();
}

beforeEach(() => {
  updateStageItem.mockReset();
  updateStageItem.mockResolvedValue({});
  patches.length = 0;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

describe("per-group advance count", () => {
  it("sits in Seeding, next to the stage-wide number it overrides", async () => {
    await mount(groupStage([item(100)]));

    // Both controls in one section is the point: an organizer setting the bar
    // for a stage and for one group should not have to change screens.
    expect(container.textContent).toContain("Teams advancing to playoff (per group)");
    expect(container.textContent).toContain("Advance count per group");
  });

  it("offers the stage's number as the placeholder every group inherits", async () => {
    await mount(groupStage([item(100), item(101, { advance_count: 3, order: 1 })]));

    expect(advanceInput(100).placeholder).toBe("Inherit (2)");
    expect(advanceInput(100).value).toBe("");
    // A group that overrides shows its own number, not the stage's.
    expect(advanceInput(101).value).toBe("3");
  });

  it("saves the typed override for that group alone", async () => {
    await mount(groupStage([item(100), item(101, { order: 1 })]));

    await typeAndBlur(advanceInput(100), "3");

    expect(updateStageItem).toHaveBeenCalledTimes(1);
    expect(updateStageItem).toHaveBeenCalledWith(100, { advance_count: 3 });
  });

  it("clears the override back to the stage with an explicit null", async () => {
    await mount(groupStage([item(100, { advance_count: 3 })]));

    await typeAndBlur(advanceInput(100), "");

    expect(updateStageItem).toHaveBeenCalledWith(100, { advance_count: null });
  });

  it("leaves a bracket lane alone: it has nothing to advance", async () => {
    await mount(
      groupStage([item(100, { type: "bracket_upper" })], { stage_type: "single_elimination" })
    );

    expect(container.querySelector('input[id$="-advance-100"]')).toBeNull();
  });
});

describe("per-group upper bracket share", () => {
  it("saves the stage-wide share with the rest of the form", async () => {
    const stage = groupStage([item(100)]);
    await mount(stage);

    await typeAndBlur(stageUpperInput(), "2");

    expect(buildStageUpdatePayload(stage, draft(stage))).toMatchObject({
      advance_upper_count: 2
    });
  });

  it("reads an unset share as All, and keeps 0 as a real answer", async () => {
    const stage = groupStage([item(100)]);
    await mount(stage);
    expect(stageUpperInput().placeholder).toBe("All");
    expect(stageUpperInput().value).toBe("");

    await typeAndBlur(stageUpperInput(), "0");
    expect(buildStageUpdatePayload(stage, draft(stage))).toMatchObject({
      advance_upper_count: 0
    });
  });

  it("saves a group's own share on blur, like the advance count beside it", async () => {
    await mount(groupStage([item(100)], { advance_upper_count: 2 }));

    expect(upperInput(100).placeholder).toBe("Inherit (2)");
    await typeAndBlur(upperInput(100), "3");

    expect(updateStageItem).toHaveBeenCalledTimes(1);
    expect(updateStageItem).toHaveBeenCalledWith(100, { advance_upper_count: 3 });
  });

  it("no longer offers the all-or-half Group seeding switch", async () => {
    // Half-and-half was the only split the stage could express; the share is a
    // number per group now, so the switch has nothing left to say.
    await mount(
      groupStage([], { id: 20, stage_type: "double_elimination", order: 2 })
    );

    expect(container.textContent).not.toContain("Group seeding");
  });

  it("shows what the next playoff will be seeded with", async () => {
    const groups = groupStage([item(100), item(101, { order: 1 })], {
      advance_count: 6,
      advance_upper_count: 2
    });
    const playoff = groupStage([], {
      id: 20,
      name: "Playoff",
      stage_type: "double_elimination",
      order: 2
    });

    await mount(groups, { stages: [groups, playoff] });

    expect(container.textContent).toContain("→ 4 upper, 8 lower");
  });

  it("counts the seeds with the numbers being typed, before they are saved", async () => {
    const groups = groupStage([item(100), item(101, { order: 1 })], {
      advance_count: 6,
      advance_upper_count: 2
    });
    const playoff = groupStage([], {
      id: 20,
      name: "Playoff",
      stage_type: "double_elimination",
      order: 2
    });
    await mount(groups, { stages: [groups, playoff] });

    await typeAndBlur(stageUpperInput(), "1");

    // The saved stage still says 2 up; the line has to answer the field.
    expect(container.textContent).toContain("→ 2 upper, 10 lower");
  });

  it("stays quiet about a playoff fed by another division's groups", async () => {
    // Two divisions in phase 1: the playoff in phase 2 resolves to neither (the
    // server refuses to wire an ambiguous phase), so this stage may not claim
    // its seed counts.
    const groups = groupStage([item(100)], {
      id: 1,
      name: "Groups Low",
      order: 1,
      advance_count: 6,
      advance_upper_count: 2
    });
    const sibling = groupStage([item(200)], { id: 2, name: "Groups High", order: 1 });
    const playoff = groupStage([], {
      id: 20,
      name: "Playoff",
      stage_type: "double_elimination",
      order: 2
    });

    await mount(groups, { stages: [groups, sibling, playoff] });

    expect(container.textContent).not.toContain("upper,");
  });

  it("says nothing about a single-elimination playoff, which has no lower bracket", async () => {
    const groups = groupStage([item(100)], {
      advance_count: 6,
      advance_upper_count: 2
    });
    const playoff = groupStage([], {
      id: 20,
      name: "Playoff",
      stage_type: "single_elimination",
      order: 2
    });

    await mount(groups, { stages: [groups, playoff] });

    expect(container.textContent).not.toContain("upper,");
  });
});

describe("parallel division wiring", () => {
  it("lists earlier group stages as wire sources for a playoff", async () => {
    const low = groupStage([], { id: 1, name: "Groups Low", order: 1 });
    const high = groupStage([], { id: 2, name: "Groups High", order: 1 });
    const playoff = groupStage([], {
      id: 20,
      name: "Playoff Low",
      stage_type: "double_elimination",
      order: 2
    });
    await mount(playoff, { stages: [low, high, playoff] });

    expect(container.textContent).toContain("Wire seeds from");
    expect(container.querySelector('[id$="-feed"]')).not.toBeNull();
  });

  it("hands the server the chosen source and no seeding maths of its own", async () => {
    // A lone source is preselected, so Wire is actionable on first render even
    // though the stage list arrives after mount.
    const groups = groupStage([], { id: 1, name: "Groups", order: 1, advance_count: 4 });
    const playoff = groupStage([], {
      id: 20,
      name: "Playoff",
      stage_type: "double_elimination",
      order: 2,
      advance_upper_count: 2
    });
    await mount(playoff, { stages: [groups, playoff] });

    const wire = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Wire"
    );
    if (!wire) throw new Error("No wire button beside the source picker");

    await act(async () => {
      wire.click();
    });
    await settle();

    expect(autoWireStage).toHaveBeenCalledWith(20, 1);
  });
});
