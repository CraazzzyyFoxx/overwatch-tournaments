"use client";

import { Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { STAGE_TYPE_LABELS } from "@/lib/bracket/projection";
import { isLifecycle } from "@/lib/flow/kinds";
import { canDelete, type DraftNode } from "@/lib/flow/flowDraft";
import type { FlowRead } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

import { FormationInspector, FormationMode, RegistrationInspector, StageInspector } from "./LifecycleInspectors";
import { Field, SelectField } from "./fields";
import { PureInspector } from "./PureInspectors";

type Patch = Partial<Pick<DraftNode, "name" | "config" | "x" | "y" | "stage">>;

type Props = Readonly<{
  tournamentId: number;
  tournament: Tournament;
  /** The admin flow read (results and participants for the pure nodes' previews). */
  read: FlowRead;
  node: DraftNode;
  /** The graph has unsaved edits: the embedded forms save on their own, so they wait. */
  dirty: boolean;
  readOnly: boolean;
  onChange: (patch: Patch) => void;
  /** Drops the node and its edges from the draft. */
  onDelete: () => void;
  onClose: () => void;
}>;

/** The side panel of the selected node: its name, then the screens of its kind. */
export function NodeInspector({ tournamentId, tournament, read, node, dirty, readOnly, onChange, onDelete, onClose }: Props) {
  const t = useTranslations("adminTournament.flow.inspector");
  const tKind = useTranslations("common.flow.kind");
  const tStatus = useTranslations("common.flow.status");
  const tType = useTranslations("adminBracket.labels.types");
  const saved = node.id === null ? undefined : tournament.flow_nodes?.find((n) => n.id === node.id);
  const rename = (name: string) => onChange({ name, ...(node.stage ? { stage: { ...node.stage, name } } : {}) });

  let body = null;
  if (!isLifecycle(node.kind)) {
    body = <PureInspector node={node} read={read} readOnly={readOnly} onChange={onChange} />;
  } else if (node.id === null) {
    body = (
      <>
        {node.stage ? (
          <SelectField
            label={t("stageType")}
            value={node.stage.stage_type}
            options={Object.keys(STAGE_TYPE_LABELS).map((type) => [type, tType(type as never)] as const)}
            disabled={readOnly}
            onChange={(stage_type) => onChange({ stage: { ...node.stage!, stage_type } as NonNullable<DraftNode["stage"]> })}
          />
        ) : null}
        <p className="text-caption text-muted-foreground">{t("saveFirst")}</p>
      </>
    );
  } else if (saved) {
    const mode = String(node.config.mode ?? "manual");
    body = (
      <>
        {node.kind === "formation" ? (
          <FormationMode tournament={tournament} node={node} readOnly={readOnly} onChange={onChange} />
        ) : null}
        {dirty ? (
          <p className="text-caption text-muted-foreground">{t("saveOrDiscard")}</p>
        ) : node.kind === "registration" ? (
          <RegistrationInspector tournamentId={tournamentId} tournament={tournament} saved={saved} readOnly={readOnly} />
        ) : node.kind === "formation" ? (
          <FormationInspector tournamentId={tournamentId} tournament={tournament} saved={saved} readOnly={readOnly} mode={mode} />
        ) : (
          <StageInspector tournamentId={tournamentId} node={node} onClose={onClose} />
        )}
      </>
    );
  }

  return (
    <aside className="space-y-4 rounded-lg border bg-card p-4" aria-label={node.name}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 text-label text-muted-foreground">
            {tKind(node.kind)}
            {node.status ? (
              <Badge tone="neutral" size="sm">
                {tStatus(node.status)}
              </Badge>
            ) : null}
          </div>
          <Field label={t("name")}>
            {(id) => <Input id={id} value={node.name} disabled={readOnly} onChange={(e) => rename(e.target.value)} />}
          </Field>
        </div>
        {readOnly ? null : (
          <Button
            type="button"
            variant="ghost-destructive"
            size="icon-sm"
            aria-label={t("delete")}
            title={canDelete(node) ? t("delete") : t("deleteLocked")}
            disabled={!canDelete(node)}
            onClick={onDelete}
          >
            <Trash2 aria-hidden />
          </Button>
        )}
        <Button type="button" variant="ghost" size="icon-sm" aria-label={t("close")} onClick={onClose}>
          <X aria-hidden />
        </Button>
      </div>
      {body}
    </aside>
  );
}
