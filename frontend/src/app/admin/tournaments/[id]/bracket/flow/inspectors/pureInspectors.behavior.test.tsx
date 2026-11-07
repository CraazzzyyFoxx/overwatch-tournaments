// @vitest-environment happy-dom
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { leagueFlow, roleFlow, starterRead } from "@/lib/flow/fixtures";
import type { DraftNode } from "@/lib/flow/flowDraft";
import type { FlowRead } from "@/types/flow.types";

import { PureInspector } from "./PureInspectors";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const onChange = vi.fn();
let root: Root;
let container: HTMLDivElement;
const settle = async (ticks = 1) => {
  for (let i = 0; i < ticks; i++) await act(async () => undefined);
};
const node = (over: Partial<DraftNode>): DraftNode => ({ key: "new-1", id: null, kind: "filter", name: "N", config: {}, stageId: null, stage: null, x: 0, y: 0, status: null, ...over });

async function render(n: DraftNode, read: FlowRead = starterRead()) {
  onChange.mockClear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <PureInspector node={n} read={read} readOnly={false} onChange={onChange} />
      </NextIntlClientProvider>
    );
  });
  await settle();
}
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

// Radix selects open on `pointerdown`; their options are portalled `[role="option"]`.
async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}
function select(label: string): HTMLElement {
  const found = [...container.querySelectorAll("label")].find((element) => (element.textContent ?? "").trim() === label);
  const trigger = found?.htmlFor ? document.getElementById(found.htmlFor) : null;
  if (!(trigger instanceof HTMLElement)) throw new Error(`no select labelled "${label}"`);
  return trigger;
}
async function choose(option: string) {
  const items = [...document.querySelectorAll<HTMLElement>('[role="option"]')].filter((element) => (element.textContent ?? "").trim() === option);
  if (items.length === 0) throw new Error(`no option named "${option}" is offered`);
  await click(items[0]);
}
function only(name: string): HTMLElement {
  const matches = [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) => (element.textContent ?? "").trim() === name || element.getAttribute("aria-label") === name
  );
  if (matches.length === 0) throw new Error(`no control named "${name}"`);
  return matches[0];
}
const pick = async (label: string, option: string) => {
  await click(select(label));
  await choose(option);
};
const hasField = (label: string) => [...container.querySelectorAll("label")].some((l) => (l.textContent ?? "").trim() === label);

describe("pure node inspectors", () => {
  it("a filter switched to range writes its bounds", async () => {
    await render(node({ kind: "filter", config: { mode: "top", n: 4 } }));
    await pick("Mode", "Range");
    expect(onChange).toHaveBeenLastCalledWith({ config: { mode: "range", from: 1, to: 1 } });
  });

  it("a split adds a bucket and keeps the size of the earlier ones", async () => {
    await render(node({ kind: "split", config: { buckets: [{ name: "A", size: 4 }], serpentine: false } }));
    await click(only("Add bucket"));
    expect(onChange).toHaveBeenLastCalledWith({ config: { buckets: [{ name: "A", size: 4 }, { name: "Bucket 2", size: null }], serpentine: false } });
  });

  it("an aggregate asks for N only for last/best modes", async () => {
    await render(node({ kind: "aggregate", config: { unit: "players", score: { preset: "stage_points" }, mode: "sum_all", n: null } }));
    expect(hasField("Count")).toBe(false);
    await pick("Mode", "Best N");
    expect(onChange).toHaveBeenLastCalledWith({ config: { unit: "players", score: { preset: "stage_points" }, mode: "sum_best_n", n: 1 } });
  });

  it("a leaderboard pin writes participant and position", async () => {
    await render(node({ key: "21", id: 21, kind: "leaderboard", config: { pins: [] } }), leagueFlow());
    await click(only("Add pin"));
    expect(onChange).toHaveBeenLastCalledWith({ config: { pins: [{ participant_id: 1, position: 1 }] } });
  });

  describe("ranking by role", () => {
    const aggregate = (config: Record<string, unknown>) => node({ kind: "aggregate", config: { score: { preset: "stage_points" }, mode: "sum_all", n: null, ...config } });
    const roleSwitch = () => container.querySelector<HTMLElement>('[role="switch"]');

    it("an aggregate of players offers the switch and writes by_role", async () => {
      await render(aggregate({ unit: "players" }));
      expect(roleSwitch()).not.toBeNull();
      expect(container.textContent).toContain("Ranking by role");
      await click(roleSwitch()!);
      expect(onChange).toHaveBeenLastCalledWith({ config: expect.objectContaining({ unit: "players", by_role: true }) });
    });

    it("an aggregate of teams has no switch", async () => {
      await render(aggregate({ unit: "teams" }));
      expect(roleSwitch()).toBeNull();
    });

    it("switching the unit to teams drops by_role", async () => {
      await render(aggregate({ unit: "players", by_role: true }));
      await pick("Unit", "Teams");
      const written = onChange.mock.lastCall![0].config;
      expect(written).toMatchObject({ unit: "teams" });
      expect(written).not.toHaveProperty("by_role");
    });

    it("a pin under a by-role aggregate names a member and a role", async () => {
      await render(node({ key: "21", id: 21, kind: "leaderboard", config: { pins: [] } }), roleFlow());
      expect(container.textContent).not.toContain("Place in role");
      await click(only("Add pin"));
      expect(onChange).toHaveBeenLastCalledWith({ config: { pins: [{ participant_id: 1, role: "tank", position: 1 }] } });
    });

    it("offers a (member, role) pair per ranking row and keeps the role when the pin moves", async () => {
      await render(node({ key: "21", id: 21, kind: "leaderboard", config: { pins: [{ participant_id: 1, role: "tank", position: 2 }] } }), roleFlow());
      expect(container.textContent).toContain("Place in role");
      await pick("Participant", "Ann · Damage");
      expect(onChange).toHaveBeenLastCalledWith({ config: { pins: [{ participant_id: 1, role: "damage", position: 2 }] } });
      await pick("Participant", "Cid · No role");
      expect(onChange).toHaveBeenLastCalledWith({ config: { pins: [{ participant_id: 3, role: null, position: 2 }] } });
    });
  });
});
