"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { FlowCanvas } from "@/components/flow/FlowCanvas";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { FLOW_NODE_PARAM } from "@/hooks/useFlowNodeParam";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { toCanvas } from "@/lib/flow/flowCanvas";
import { addNode, assignStageOrders, connect, deletedLifecycleNodes, removeEdge, removeNode, updateNode, canDelete } from "@/lib/flow/flowDraft";
import { applyPreset, hasOnlyStarterNodes, type PresetLabels } from "@/lib/flow/presets";
import type { FlowNodeKind, FlowStageCreate } from "@/types/flow.types";

import { tabError, tabFallback, useHubTournamentQuery } from "../hubQueries";
import { FlowIssues } from "./FlowIssues";
import { NodeInspector } from "./inspectors/NodeInspector";
import { FlowPalette } from "./FlowPalette";
import { PresetDialog } from "./PresetDialog";
import { useFlowEditor } from "./useFlowEditor";

/** A palette click lands this far right of the right-most node's card (`min-w-44`, 176 px, plus a gap). */
const CLICK_OFFSET = 176 + 40;

/** The Flow tab: palette, canvas, issues and Save. A viewer without `tournament.update` gets the canvas read-only. */
export function FlowEditor({ tournamentId }: Readonly<{ tournamentId: number }>) {
  const t = useTranslations("adminTournament.flow");
  const tKind = useTranslations("common.flow.kind");
  const tNames = useTranslations("adminTournament.flow.presets.names");
  const { canAccessPermission } = usePermissions();
  const { searchParams, setParams } = useQueryParams({ shallow: true, resetOnChange: [] });
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const editor = useFlowEditor(tournamentId);
  const tournament = useHubTournamentQuery(tournamentId).data;
  const workspaceId = tournament?.workspace_id ?? null;
  const canUpdate = canAccessPermission("tournament.update", workspaceId);
  const { read, draft, keyed, dirty, apply } = editor;

  if (editor.isError) return tabError(() => editor.refetch());
  if (!read || !draft || !keyed) return tabFallback;

  const readOnly = !canUpdate;
  const selected = draft.nodes.find((n) => n.key === searchParams?.get(FLOW_NODE_PARAM));
  // Palette (editable only), canvas, inspector (a node is selected).
  const columns = readOnly
    ? selected
      ? "lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]"
      : ""
    : selected
      ? "lg:grid-cols-[11rem_minmax(0,3fr)_minmax(0,2fr)]"
      : "lg:grid-cols-[11rem_minmax(0,1fr)]";
  const select = (key: string | null) => setParams({ [FLOW_NODE_PARAM]: key });
  const issueCounts = new Map([...keyed.nodeIssues].map(([key, list]) => [key, list.length]));
  const { nodes, edges } = toCanvas(draft, keyed.ports, issueCounts, new Set(keyed.edgeIssues.keys()), readOnly);
  const savedOrders = new Map((tournament?.stages ?? []).map((stage) => [stage.id, stage.order] as const));
  const doomed = deletedLifecycleNodes(draft);

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

  const labels: PresetLabels = {
    playoff: tNames("playoff"),
    groups: tNames("groups"),
    topPerGroup: (n) => tNames("topPerGroup", { n }),
    top: (n) => tNames("top", { n }),
    playoffTeams: tNames("playoffTeams"),
    swiss: tNames("swiss"),
    qualifiers: tNames("qualifiers"),
    day: (i) => tNames("day", { i }),
    dayTeams: (i) => tNames("dayTeams", { i }),
    season: tNames("season"),
    seasonTable: tNames("seasonTable")
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {canUpdate && hasOnlyStarterNodes(read) && !dirty ? (
          <Button type="button" variant="outline" onClick={() => setPresetsOpen(true)}>
            {t("toolbar.presets")}
          </Button>
        ) : null}
        {canUpdate && dirty ? (
          <>
            <span className="text-caption text-muted-foreground">{t("toolbar.unsaved")}</span>
            <Button type="button" disabled={editor.saving} onClick={() => (doomed.length > 0 ? setConfirmingDelete(true) : editor.save())}>
              {t("toolbar.save")}
            </Button>
            <Button type="button" variant="outline" disabled={editor.saving} onClick={editor.discard}>
              {t("toolbar.discard")}
            </Button>
          </>
        ) : null}
      </div>

      <div className={`grid gap-4 ${columns}`}>
        {readOnly ? null : (
          <div className="hidden lg:block">
            <FlowPalette onAdd={(kind) => add(kind)} />
          </div>
        )}
        <section aria-label={t("canvasLabel")}>
          <FlowCanvas
            nodes={nodes}
            edges={edges}
            readOnly={readOnly}
            heightClass="h-[70vh]"
            onNodeClick={select}
            onDropKind={add}
            onConnect={({ source, sourceHandle, target, targetHandle }) => {
              if (sourceHandle && targetHandle)
                apply((d) => assignStageOrders(connect(d, { source, sourceHandle, target, targetHandle }), savedOrders));
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
          />
        </section>
        {selected && tournament ? (
          <NodeInspector
            key={selected.key}
            tournamentId={tournamentId}
            tournament={tournament}
            read={read}
            node={selected}
            dirty={dirty}
            readOnly={readOnly}
            onChange={(patch) => apply((d) => updateNode(d, selected.key, patch))}
            onClose={() => select(null)}
          />
        ) : null}
      </div>

      <FlowIssues keyed={keyed} draft={draft} onSelect={select} />

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
