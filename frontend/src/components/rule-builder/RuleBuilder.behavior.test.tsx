// @vitest-environment happy-dom
//
// An edit publishes the rebuilt tree to the parent, whose `onChange` sets state. That call must come from the edit's
// event, not from inside React's render of the builder: React rejects one component updating another mid-render.
import type { ReactNode } from "react";
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";

import { RuleBuilder } from "./RuleBuilder";
import type { RuleBuilderEditLabels } from "./RuleNodes";
import type { TreeNode } from "./rule-tree";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// xyflow's drawing is not under test; the palette column is the canvas' own, outside it.
vi.mock("@xyflow/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@xyflow/react")>()),
  ReactFlow: () => null,
  ReactFlowProvider: ({ children }: { children: ReactNode }) => children,
  useReactFlow: () => ({ screenToFlowPosition: (point: { x: number; y: number }) => point })
}));

const name = (...parts: string[]) => parts.join(" ");
const labels: RuleBuilderEditLabels = {
  outlineTitle: "Outline",
  outlineGroup: name,
  groupName: name,
  operatorLabel: name,
  addLeaf: "Add condition",
  addLeafLabel: name,
  addGroup: "Add group",
  addGroupLabel: name,
  deleteGroupLabel: name,
  deleteLeafLabel: name,
  leafTypeLabel: name,
  leafFieldLabel: name
};

function Host() {
  const [tree, setTree] = useState<TreeNode>({ AND: [{ type: "map_index" }] });
  return (
    <>
      <output>{JSON.stringify(tree)}</output>
      <RuleBuilder
        value={tree}
        onChange={setTree}
        leafOptions={[]}
        defaultLeafType="map_index"
        palette={[{ label: "Logic", items: [{ type: "logical", logicalOp: "OR", label: "OR" }] }]}
        renderLeafFields={() => null}
        labelForLeaf={(type) => type ?? ""}
        summarizeLeaf={() => ""}
        labels={labels}
        heightClass="h-10"
      />
    </>
  );
}

let root: Root;
let container: HTMLDivElement;

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("RuleBuilder", () => {
  it("hands each edit to the parent from the event, never while rendering", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    act(() =>
      root.render(
        <NextIntlClientProvider locale="en" messages={en}>
          <Host />
        </NextIntlClientProvider>
      )
    );
    const add = () => container.querySelector<HTMLButtonElement>('[aria-label="Add OR"]')!;

    act(() => add().click());
    act(() => add().click());

    expect(JSON.parse(container.querySelector("output")!.textContent!)).toEqual({
      AND: [{ type: "map_index" }, { OR: [] }, { OR: [] }]
    });
    expect(errors).not.toHaveBeenCalled();
  });
});
