"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { flowNodeTypes } from "@/components/flow/FlowNodeCard";
import { CanvasPanel, GraphCanvas } from "@/components/graph-canvas/GraphCanvas";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SaveBar } from "@/components/kit/SaveBar";
import { Button } from "@/components/ui/button";
import { floatingPanelClass } from "@/components/ui/popover";
import { FLOW_NODE_PARAM } from "@/hooks/useFlowNodeParam";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { toCanvas } from "@/lib/flow/flowCanvas";
import { arrangeDraft } from "@/lib/flow/autoLayout";
import {
  addNode,
  assignStageOrders,
  canDelete,
  connect,
  deletedLifecycleNodes,
  reconnect,
  removeEdge,
  removeNode,
  toChanges,
  updateNode
} from "@/lib/flow/flowDraft";
import { LIFECYCLE_KINDS, PURE_KINDS } from "@/lib/flow/kinds";
import { applyPreset, hasOnlyStarterNodes } from "@/lib/flow/presets";
import { usePresetLabels } from "@/lib/flow/usePresetLabels";
import { cn } from "@/lib/utils";
import type { FlowNodeKind, FlowStageCreate } from "@/types/flow.types";

import { tabError, tabFallback, useHubTournamentQuery } from "../../hubQueries";
import { FlowIssues } from "./FlowIssues";
import { NodeInspector } from "./inspectors/NodeInspector";
import { PresetDialog } from "./PresetDialog";
import { useFlowEditor } from "./useFlowEditor";

/** A palette click lands this far right of the right-most node's card (`min-w-44`, 176 px, plus a gap). */
const CLICK_OFFSET = 176 + 40;

/** The Flow tab: canvas (with its palette) and its issues, and the save bar. A viewer without `tournament.update` gets the canvas read-only. */
export function FlowEditor({ tournamentId }: Readonly<{ tournamentId: number }>) {
  const t = useTranslations("adminTournament.flow");
  const tKind = useTranslations("common.flow.kind");
  const tPalette = useTranslations("adminTournament.flow.palette");
  const labels = usePresetLabels();
  const { canAccessPermission } = usePermissions();
  const { searchParams, setParams } = useQueryParams({ shallow: true, resetOnChange: [] });
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const editor = useFlowEditor(tournamentId);
  const tournament = useHubTournamentQuery(tournamentId).data;
  const workspaceId = tournament?.workspace_id ?? null;
  const canUpdate = canAccessPermission("tournament.update", workspaceId);
  const { read, draft, keyed, dirty, changes, apply } = editor;

  if (editor.isError) return tabError(() => editor.refetch());
  if (!read || !draft || !keyed) return tabFallback;

  const readOnly = !canUpdate;
  const selected = draft.nodes.find((n) => n.key === searchParams?.get(FLOW_NODE_PARAM));
  // Canvas, and the narrow inspector beside it while a node is selected.
  const columns = selected ? "lg:grid-cols-[minmax(0,1fr)_20rem]" : "";
  const select = (key: string | null) => setParams({ [FLOW_NODE_PARAM]: key });
  const issueCounts = new Map([...keyed.nodeIssues].map(([key, list]) => [key, list.length]));
  const { nodes, edges } = toCanvas(draft, keyed.ports, issueCounts, new Set(keyed.edgeIssues.keys()), readOnly);
  const savedOrders = new Map((tournament?.stages ?? []).map((stage) => [stage.id, stage.order] as const));
  const doomed = deletedLifecycleNodes(draft);
  // The opening arrangement goes out with Save, but it is not the admin's change to count.
  const arranged = new Set(editor.opened ? toChanges(editor.opened).nodes.map((n) => JSON.stringify(n)) : []);
  const summary = changes
    ? (
        [
          ["nodesAdded", changes.nodes.filter((n) => n.id === undefined).length],
          ["nodesChanged", changes.nodes.filter((n) => n.id !== undefined && !arranged.has(JSON.stringify(n))).length],
          ["nodesRemoved", changes.delete_node_ids.length],
          ["linksAdded", changes.edges.length],
          ["linksRemoved", changes.delete_edge_ids.length]
        ] as const
      )
        .filter(([, count]) => count > 0)
        .map(([key, count]) => t(`changes.${key}`, { count }))
        .join(" · ")
    : "";

  const add = (kind: FlowNodeKind, at?: { x: number; y: number }) =>
    apply((d) => {
      const name = tKind(kind);
      const rightmost = d.nodes.reduce<(typeof d.nodes)[number] | null>((r, n) => (!r || n.x > r.x ? n : r), null);
      const { x, y } = at ?? { x: (rightmost?.x ?? 0) + CLICK_OFFSET, y: rightmost?.y ?? 0 };
      const seed = (read.config_defaults?.[kind as keyof typeof read.config_defaults] ?? {}) as Record<string, unknown>;
      return assignStageOrders(
        addNode(d, {
          kind,
          name,
          config: structuredClone(seed),
          stage: kind === "stage" ? ({ name, stage_type: "round_robin" } as FlowStageCreate) : null,
          x,
          y
        }),
        savedOrders
      );
    });
  const palette = readOnly
    ? undefined
    : {
        groups: [
          { label: tPalette("lifecycle"), items: LIFECYCLE_KINDS.map((kind) => ({ key: kind, label: tKind(kind) })) },
          { label: tPalette("transitions"), items: PURE_KINDS.map((kind) => ({ key: kind, label: tKind(kind) })) }
        ],
        onAdd: (kind: string, at?: { x: number; y: number }) => add(kind as FlowNodeKind, at)
      };

  return (
    <div className="space-y-4">
      <div className={`grid gap-4 ${columns}`}>
        <section aria-label={t("canvasLabel")}>
          <GraphCanvas
            nodes={nodes}
            edges={edges}
            nodeTypes={flowNodeTypes}
            readOnly={readOnly}
            heightClass="h-[70vh]"
            onNodeClick={select}
            palette={palette}
            onConnect={({ source, sourceHandle, target, targetHandle }) => {
              if (sourceHandle && targetHandle)
                apply((d) => assignStageOrders(connect(d, { source, sourceHandle, target, targetHandle }), savedOrders));
            }}
            onReconnect={(edgeId, { source, sourceHandle, target, targetHandle }) => {
              if (sourceHandle && targetHandle)
                apply((d) => assignStageOrders(reconnect(d, edgeId, { source, sourceHandle, target, targetHandle }), savedOrders));
            }}
            onNodesChange={(changes) =>
              apply((d) =>
                changes.reduce((acc, change) => {
                  if (change.type === "position" && change.position)
                    return updateNode(acc, change.id, { x: change.position.x, y: change.position.y });
                  const gone = change.type === "remove" ? acc.nodes.find((n) => n.key === change.id) : undefined;
                  return gone && canDelete(gone) ? removeNode(acc, gone.key) : acc;
                }, d)
              )
            }
            onEdgesChange={(changes) =>
              apply((d) => changes.reduce((acc, change) => (change.type === "remove" ? removeEdge(acc, change.id) : acc), d))
            }
            onArrange={readOnly ? undefined : () => apply(arrangeDraft)}
          >
            {canUpdate && hasOnlyStarterNodes(read) && !dirty ? (
              <CanvasPanel position="top-center">
                <div className={cn(floatingPanelClass, "flex items-center gap-3 px-3 py-2")}>
                  <p className="hidden text-caption text-muted-foreground sm:block">{t("presets.hint")}</p>
                  <Button type="button" variant="outline" size="sm" onClick={() => setPresetsOpen(true)}>
                    {t("presets.open")}
                  </Button>
                </div>
              </CanvasPanel>
            ) : null}
            <FlowIssues keyed={keyed} draft={draft} onSelect={select} />
          </GraphCanvas>
        </section>
        {selected && tournament ? (
          <NodeInspector
            key={selected.key}
            tournamentId={tournamentId}
            tournament={tournament}
            read={read}
            node={selected}
            readOnly={readOnly}
            onChange={(patch) => apply((d) => updateNode(d, selected.key, patch))}
            onDelete={() => {
              apply((d) => removeNode(d, selected.key));
              select(null);
            }}
            onClose={() => select(null)}
          />
        ) : null}
      </div>

      <SaveBar
        dirty={dirty}
        summary={summary}
        error={editor.error}
        saving={editor.saving}
        primaryLabel={t("save")}
        onDiscard={editor.discard}
        onSave={() => (doomed.length > 0 ? setConfirmingDelete(true) : editor.save())}
      />

      <PresetDialog
        open={presetsOpen}
        onOpenChange={setPresetsOpen}
        onApply={(preset, params) => {
          apply((d) => applyPreset(d, preset, params, labels));
          setPresetsOpen(false);
        }}
      />

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        intent={{
          title: t("confirmDelete.title"),
          description: t("confirmDelete.description"),
          confirmLabel: t("confirmDelete.confirm"),
          tone: "danger",
          cascade: doomed.map((n) => t(`confirmDelete.${n.kind as "registration"}`, { name: n.name }))
        }}
        pending={editor.saving}
        onConfirm={() => {
          setConfirmingDelete(false);
          editor.save();
        }}
      />
    </div>
  );
}
