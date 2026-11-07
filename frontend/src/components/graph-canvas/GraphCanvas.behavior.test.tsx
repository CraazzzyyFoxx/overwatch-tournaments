// @vitest-environment happy-dom
//
// The canvas owns xyflow's state: a controlled xyflow applies only the changes the app applies, so `select` and
// `dimensions` must be applied here (else nothing is selectable or deletable and nodes stay unmeasured), while only
// position and removal go back to the parent. xyflow's drawing is stubbed; its `onNodesChange` contract is the real one.
import type { Edge, EdgeChange, Node, NodeChange } from "@xyflow/react";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GraphCanvas } from "./GraphCanvas";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type Handed = {
  nodes: Node[];
  edges: Edge[];
  nodesDraggable: boolean;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
};
let handed: Handed;

vi.mock("@xyflow/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@xyflow/react")>()),
  ReactFlow: (props: Handed) => {
    handed = props;
    return null;
  },
  ReactFlowProvider: ({ children }: { children: ReactNode }) => children,
  useReactFlow: () => ({ screenToFlowPosition: (point: { x: number; y: number }) => point })
}));

const makeNodes = (x = 0): Node[] => [
  { id: "a", type: "card", position: { x, y: 0 }, data: {} },
  { id: "b", type: "card", position: { x: 300, y: 0 }, data: {} }
];
const makeEdges = (): Edge[] => [{ id: "e", source: "a", target: "b" }];

let root: Root;
let container: HTMLDivElement;
function render(props: {
  nodes: Node[];
  edges: Edge[];
  readOnly?: boolean;
  onNodesChange?: Handed["onNodesChange"];
  onEdgesChange?: Handed["onEdgesChange"];
}) {
  container ??= document.body.appendChild(document.createElement("div"));
  root ??= createRoot(container);
  act(() => root.render(<GraphCanvas nodeTypes={{}} readOnly={false} heightClass="h-10" {...props} />));
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  root = undefined as never;
  container = undefined as never;
});

describe("GraphCanvas", () => {
  it("applies select, dimensions and position changes, handing only the position back", () => {
    const onNodesChange = vi.fn();
    render({ nodes: makeNodes(), edges: makeEdges(), onNodesChange });

    act(() =>
      handed.onNodesChange([
        { type: "select", id: "a", selected: true },
        { type: "dimensions", id: "a", dimensions: { width: 176, height: 60 } },
        { type: "position", id: "a", position: { x: 10, y: 5 }, dragging: true }
      ])
    );

    expect(handed.nodes[0]).toMatchObject({ selected: true, measured: { width: 176, height: 60 }, position: { x: 10, y: 5 } });
    expect(onNodesChange).toHaveBeenCalledTimes(1);
    expect(onNodesChange).toHaveBeenCalledWith([expect.objectContaining({ type: "position", id: "a" })]);
  });

  it("keeps selection and measured sizes when the parent re-renders with fresh node objects", () => {
    render({ nodes: makeNodes(), edges: makeEdges(), onNodesChange: vi.fn() });
    act(() => {
      handed.onNodesChange([
        { type: "select", id: "a", selected: true },
        { type: "dimensions", id: "a", dimensions: { width: 176, height: 60 } }
      ]);
      handed.onEdgesChange([{ type: "select", id: "e", selected: true }]);
    });

    render({ nodes: makeNodes(40), edges: makeEdges(), onNodesChange: vi.fn() });

    expect(handed.nodes[0]).toMatchObject({ selected: true, measured: { width: 176, height: 60 }, position: { x: 40, y: 0 } });
    expect(handed.edges[0]?.selected).toBe(true);
  });

  it("selects an edge locally and hands its removal back", () => {
    const onEdgesChange = vi.fn();
    render({ nodes: makeNodes(), edges: makeEdges(), onEdgesChange });

    act(() => handed.onEdgesChange([{ type: "select", id: "e", selected: true }]));
    expect(handed.edges[0]?.selected).toBe(true);
    expect(onEdgesChange).not.toHaveBeenCalled();

    act(() => handed.onEdgesChange([{ type: "remove", id: "e" }]));
    expect(handed.edges).toEqual([]);
    expect(onEdgesChange).toHaveBeenCalledWith([{ type: "remove", id: "e" }]);
  });

  it("measures a read-only canvas without handing anything back", () => {
    const onNodesChange = vi.fn();
    render({ nodes: makeNodes(), edges: makeEdges(), readOnly: true, onNodesChange });

    act(() => handed.onNodesChange([{ type: "dimensions", id: "b", dimensions: { width: 100, height: 40 } }]));

    expect(handed.nodes[1]?.measured).toEqual({ width: 100, height: 40 });
    expect(onNodesChange).not.toHaveBeenCalled();
  });

  it("lets nodes be dragged only where the parent keeps their positions", () => {
    render({ nodes: makeNodes(), edges: makeEdges() });
    expect(handed.nodesDraggable).toBe(false);

    render({ nodes: makeNodes(), edges: makeEdges(), onNodesChange: vi.fn() });
    expect(handed.nodesDraggable).toBe(true);
  });
});
