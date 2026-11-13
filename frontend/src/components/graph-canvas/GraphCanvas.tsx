"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type ReactNode
} from "react";
import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  ControlButton,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStore,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
  type XYPosition
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Maximize2, Minimize2, Network } from "lucide-react";
import { useTranslations } from "next-intl";

import { Dialog, DialogContent, DialogTitle } from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";

import { GraphEdge } from "./GraphEdge";
import { GRAPH_PALETTE_MIME, GraphPalette, GraphPaletteMenu, type GraphPaletteGroup } from "./GraphPalette";
import { HANDLE_COLOR } from "./tokens";

/**
 * xyflow chrome repainted in the app's shadcn tokens. The app is dark-only, so `colorMode="dark"` flips xyflow's own
 * chrome to dark and these overrides repaint it: xyflow's dark palette is a neutral grey that clashes with the
 * blue-tinted surfaces around it.
 */
const XY_THEME = {
  "--xy-background-color": "transparent",
  "--xy-background-pattern-color": "hsl(var(--muted-foreground) / 0.22)",
  "--xy-edge-stroke": "hsl(var(--muted-foreground) / 0.55)",
  "--xy-handle-background-color": HANDLE_COLOR,
  "--xy-handle-border-color": "hsl(var(--card))",
  "--xy-controls-box-shadow": "none",
  "--xy-controls-button-background-color": "hsl(var(--card))",
  "--xy-controls-button-background-color-hover": "hsl(var(--accent))",
  "--xy-controls-button-color": "hsl(var(--muted-foreground))",
  "--xy-controls-button-color-hover": "hsl(var(--foreground))",
  "--xy-controls-button-border-color": "hsl(var(--border))",
  "--xy-minimap-background-color": "hsl(var(--card))"
} as CSSProperties;

// `default` is the type of every edge without one: all of them are drawn the same way.
const edgeTypes = { default: GraphEdge };

/** A node's minimap swatch: its card's `accent` when its data names one. */
const swatch = (node: Node) => (typeof node.data.accent === "string" ? node.data.accent : HANDLE_COLOR);

/** The next props' elements, each keeping the xyflow-owned fields of the element it replaces (matched by id). */
function carryOver<T extends { id: string }>(current: T[], next: T[], keys: (keyof T)[]): T[] {
  const byId = new Map(current.map((element) => [element.id, element]));
  return next.map((element) => {
    const previous = byId.get(element.id);
    return previous ? { ...element, ...Object.fromEntries(keys.map((key) => [key, previous[key]])) } : element;
  });
}

export type GraphCanvasProps<N extends Node> = {
  nodes: N[];
  edges: Edge[];
  /** A module-level constant: xyflow remounts every node when this object changes identity. */
  nodeTypes: NodeTypes;
  readOnly: boolean;
  /** The canvas' height utility, e.g. `h-[70vh]`. */
  heightClass: string;
  /** Position and removal changes. Nodes are draggable only with it: elsewhere positions are a layout's, not the admin's. */
  onNodesChange?: OnNodesChange<N>;
  onEdgesChange?: OnEdgesChange;
  onConnect?: (connection: Connection) => void;
  /** An edge's end dragged onto another handle. */
  onReconnect?: (edgeId: string, connection: Connection) => void;
  onNodeClick?: (id: string) => void;
  /** Lays every node out again; offered as a canvas control while editable. */
  onArrange?: () => void;
  /** The add-node palette (editable only): `at` is the flow-space drop point, absent for a click. */
  palette?: { groups: GraphPaletteGroup[]; onAdd: (key: string, at?: XYPosition) => void };
  /** `CanvasPanel`s floating over the canvas. */
  children?: ReactNode;
};

/** A box pinned over the canvas (xyflow's `Panel`), for the editor's own overlays. */
export const CanvasPanel = Panel;

type Focus = { key: string; at: number };
const FocusContext = createContext<(key: string) => void>(() => undefined);

/** Brings one node into view, for a control in a `CanvasPanel` that names it (an issue row). */
export const useFocusNode = () => useContext(FocusContext);

/**
 * Fits the canvas to the node just asked for, and again while the canvas resizes in the next moment: selecting that node
 * opens the inspector beside the canvas, which would leave the node off-centre or cut off.
 */
function FocusFollower({ focus }: Readonly<{ focus: Focus | null }>) {
  const { fitView } = useReactFlow();
  const width = useStore((state) => state.width);
  const reducedMotion = usePrefersReducedMotion();
  useEffect(() => {
    if (focus && Date.now() - focus.at < 1000)
      void fitView({ nodes: [{ id: focus.key }], maxZoom: 1, duration: reducedMotion ? 0 : 300 });
  }, [focus, width, fitView, reducedMotion]);
  return null;
}

function CanvasControls({
  onArrange,
  fullscreen,
  onFullscreen
}: Readonly<{ onArrange?: () => void; fullscreen: boolean; onFullscreen: () => void }>) {
  const t = useTranslations("common.graphCanvas");
  const fullscreenLabel = fullscreen ? t("exitFullscreen") : t("fullscreen");
  // xyflow fills control icons; a Lucide glyph is a stroke.
  return (
    <Controls showInteractive={false}>
      {onArrange ? (
        <ControlButton onClick={onArrange} title={t("arrange")} aria-label={t("arrange")}>
          <Network aria-hidden className="fill-none!" />
        </ControlButton>
      ) : null}
      <ControlButton
        onClick={onFullscreen}
        title={fullscreenLabel}
        aria-label={fullscreenLabel}
        aria-pressed={fullscreen}
        data-fullscreen-toggle
      >
        {fullscreen ? <Minimize2 aria-hidden className="fill-none!" /> : <Maximize2 aria-hidden className="fill-none!" />}
      </ControlButton>
    </Controls>
  );
}

/**
 * Fullscreen is a full-viewport modal, not a `fixed` frame: a transformed ancestor (a dialog centring itself) would
 * confine a `fixed` frame to its own box. The modal also brings Esc, the scroll lock, and a focus trap that stacks over
 * a surrounding dialog's, so Esc leaves fullscreen without closing that dialog. The canvas remounts on either side, so
 * focus goes to the remounted toggle rather than to the one the modal was opened from.
 */
function FullscreenDialog({
  onExit,
  focusToggle,
  children
}: Readonly<{ onExit: () => void; focusToggle: () => void; children: ReactNode }>) {
  const t = useTranslations("common.graphCanvas");
  const toToggle = (e: Event) => {
    e.preventDefault();
    focusToggle();
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onExit();
      }}
    >
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        onOpenAutoFocus={toToggle}
        onCloseAutoFocus={toToggle}
        className="inset-0 block h-dvh max-h-none w-full max-w-none translate-x-0 translate-y-0 overflow-hidden rounded-none border-0 bg-background p-0"
      >
        <DialogTitle className="sr-only">{t("fullscreen")}</DialogTitle>
        {children}
      </DialogContent>
    </Dialog>
  );
}

function Canvas<N extends Node>({
  nodes,
  edges,
  nodeTypes,
  readOnly,
  heightClass,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onReconnect,
  onNodeClick,
  onArrange,
  palette,
  children
}: Readonly<GraphCanvasProps<N>>) {
  const { screenToFlowPosition } = useReactFlow();
  const [focus, setFocus] = useState<Focus | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);

  // xyflow's own state (selection, measured sizes, drag flags) lives here: a controlled canvas applies only the
  // changes the app applies, so dropping `select`/`dimensions` would leave nothing selectable and every node unmeasured.
  // The props stay the source of truth for what exists and where, and only position and removal go back to the parent.
  const [rfNodes, setRfNodes] = useState(nodes);
  const [rfEdges, setRfEdges] = useState(edges);
  const [synced, setSynced] = useState({ nodes, edges });
  if (synced.nodes !== nodes || synced.edges !== edges) {
    setSynced({ nodes, edges });
    setRfNodes((current) => carryOver(current, nodes, ["measured", "selected", "dragging"]));
    setRfEdges((current) => carryOver(current, edges, ["selected"]));
  }

  const handleNodesChange: OnNodesChange<N> = (changes) => {
    setRfNodes((current) => applyNodeChanges(changes, current));
    const edits = changes.filter((change) => change.type === "position" || change.type === "remove");
    if (!readOnly && edits.length > 0) onNodesChange?.(edits);
  };
  const handleEdgesChange: OnEdgesChange = (changes) => {
    setRfEdges((current) => applyEdgeChanges(changes, current));
    const edits = changes.filter((change) => change.type === "remove");
    if (!readOnly && edits.length > 0) onEdgesChange?.(edits);
  };

  const adding = readOnly ? undefined : palette;
  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const key = e.dataTransfer.getData(GRAPH_PALETTE_MIME);
    if (key) adding?.onAdd(key, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  const frame = (
    <div
      ref={frameRef}
      className={cn("flex w-full overflow-hidden bg-background", fullscreen ? "h-full" : `${heightClass} rounded-lg border`)}
    >
      {adding ? <GraphPalette groups={adding.groups} onAdd={(key) => adding.onAdd(key)} /> : null}
      <div className="relative min-w-0 flex-1">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={readOnly ? undefined : onConnect}
          onReconnect={readOnly || !onReconnect ? undefined : (edge, connection) => onReconnect(edge.id, connection)}
          edgesReconnectable={!readOnly && onReconnect !== undefined}
          deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
          onNodeClick={onNodeClick ? (_event, node) => onNodeClick(node.id) : undefined}
          onDragOver={adding ? onDragOver : undefined}
          onDrop={adding ? onDrop : undefined}
          nodesConnectable={!readOnly && onConnect !== undefined}
          nodesDraggable={!readOnly && onNodesChange !== undefined}
          elementsSelectable={!readOnly}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.3}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
          style={XY_THEME}
        >
          <Background gap={20} size={1} />
          <CanvasControls
            onArrange={readOnly ? undefined : onArrange}
            fullscreen={fullscreen}
            onFullscreen={() => setFullscreen((on) => !on)}
          />
          {readOnly ? null : <MiniMap nodeColor={swatch} maskColor="rgba(0,0,0,0.2)" />}
          {adding ? (
            <Panel position="top-left" className="lg:hidden">
              <GraphPaletteMenu groups={adding.groups} onAdd={(key) => adding.onAdd(key)} />
            </Panel>
          ) : null}
          <FocusFollower focus={focus} />
          <FocusContext value={(key) => setFocus({ key, at: Date.now() })}>{children}</FocusContext>
        </ReactFlow>
      </div>
    </div>
  );
  if (!fullscreen) return frame;
  // The empty frame holds the page's layout while the canvas is up in the modal, so leaving fullscreen does not jump.
  return (
    <>
      <div aria-hidden className={cn(heightClass, "w-full rounded-lg border")} />
      <FullscreenDialog
        onExit={() => setFullscreen(false)}
        focusToggle={() => frameRef.current?.querySelector<HTMLButtonElement>("[data-fullscreen-toggle]")?.focus()}
      >
        {frame}
      </FullscreenDialog>
    </>
  );
}

/**
 * The one xyflow canvas: theme, controls (zoom, fit, arrange, fullscreen), minimap, palette, drop and xyflow's state
 * sync. Editable with handlers, read-only without; the nodes are the caller's (`GraphNodeCard`), every edge a
 * `GraphEdge`. Import it through `next/dynamic` in client-only screens, with `GraphCanvasSkeleton` as the placeholder.
 */
export function GraphCanvas<N extends Node>(props: Readonly<GraphCanvasProps<N>>) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
