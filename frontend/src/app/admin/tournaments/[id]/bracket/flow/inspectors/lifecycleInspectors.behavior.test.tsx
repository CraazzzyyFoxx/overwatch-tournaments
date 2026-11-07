// @vitest-environment happy-dom
//
// The node inspector holds only what shapes the graph, as draft edits saved with the flow; the node's own screen is one
// link away.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { starterRead } from "@/lib/flow/fixtures";
import type { DraftNode } from "@/lib/flow/flowDraft";

import { NodeInspector } from "./NodeInspector";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const tournament = { id: 7, workspace_id: 3, stages: [{ id: 40, name: "Groups", stage_type: "round_robin" }] } as never;
const node = (over: Partial<DraftNode>): DraftNode => ({
  key: "1",
  id: 1,
  kind: "registration",
  name: "Day 1",
  config: { intake: "solo" },
  stageId: null,
  stage: null,
  x: 0,
  y: 0,
  status: "open",
  ...over
});

let root: Root;
let container: HTMLDivElement;
async function render(n: DraftNode, onChange = vi.fn()) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <NodeInspector tournamentId={7} tournament={tournament} read={starterRead()} node={n} readOnly={false} onChange={onChange} onDelete={vi.fn()} onClose={vi.fn()} />
      </NextIntlClientProvider>
    );
  });
  return onChange;
}
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("node inspector", () => {
  it("edits a registration's check-in as a draft change and links its full settings", async () => {
    const onChange = await render(node({}));
    const checkIn = container.querySelector<HTMLButtonElement>('[role="switch"]')!;
    await act(async () => checkIn.click());
    expect(onChange).toHaveBeenCalledWith({ config: { intake: "solo", check_in: true } });
    expect(container.querySelector('a[href="/admin/tournaments/7/settings/registration?node=1"]')).not.toBeNull();
  });

  it("lets a new formation pick its mode, and links a saved one to the screen of its mode", async () => {
    await render(node({ key: "new-1", id: null, kind: "formation", status: null, config: { mode: "draft" } }));
    expect(container.querySelector('button[role="combobox"]')?.hasAttribute("disabled")).toBe(false);
    expect(container.textContent).toContain(en.draftAdmin.format);
    act(() => root.unmount());
    container.remove();

    await render(node({ key: "2", id: 2, kind: "formation", status: "completed", config: { mode: "balancer" } }));
    expect(container.querySelector('button[role="combobox"]')?.hasAttribute("disabled")).toBe(true);
    expect(container.querySelector('a[href="/balancer?tournament=7&node=2"]')).not.toBeNull();
  });

  it("shows a saved stage's format and sends the rest to the stage editor", async () => {
    await render(node({ key: "3", id: 3, kind: "stage", name: "Groups", stageId: 40, status: "draft", config: {} }));
    expect(container.textContent).toContain(en.adminBracket.labels.types.round_robin);
    expect(container.querySelector('a[href="/admin/tournaments/7/bracket?stage=40"]')).not.toBeNull();
  });
});
