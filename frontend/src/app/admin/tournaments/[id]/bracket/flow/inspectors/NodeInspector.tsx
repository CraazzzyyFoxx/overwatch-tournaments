"use client";

import { Trash2, X } from "lucide-react";
import type { ComponentProps } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { STAGE_TYPE_LABELS } from "@/lib/bracket/projection";
import { isLifecycle } from "@/lib/flow/kinds";
import { canDelete, type DraftNode } from "@/lib/flow/flowDraft";
import type { FlowRead } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

import { FormationMode, RegistrationFields, ScreenLink, formationScreen } from "./LifecycleInspectors";
import { Field, SelectField } from "./fields";
import { PureInspector } from "./PureInspectors";

type Patch = Partial<Pick<DraftNode, "name" | "config" | "x" | "y" | "stage">>;

type Props = Readonly<{
  tournamentId: number;
  tournament: Tournament;
  /** The admin flow read (results and participants for the pure nodes). */
  read: FlowRead;
  node: DraftNode;
  readOnly: boolean;
  onChange: (patch: Patch) => void;
  /** Drops the node and its edges from the draft. */
  onDelete: () => void;
  onClose: () => void;
}>;

/** The config form of a pure node, with the game's role dictionary (role names, glyphs, order) for the by-role views. */
function PureNodeBody({ tournament, ...props }: Readonly<{ tournament: Tournament } & ComponentProps<typeof PureInspector>>) {
  const ontology = useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  return <PureInspector {...props} ontology={ontology} />;
}

/**
 * The side panel of the selected node: its name and the settings that shape the graph, all of them draft edits saved with
 * the flow. Everything else about the node (entries, schedules, sessions, the stage itself) is one link away, on its screen.
 */
export function NodeInspector({ tournamentId, tournament, read, node, readOnly, onChange, onDelete, onClose }: Props) {
  const t = useTranslations("adminTournament.flow.inspector");
  const tKind = useTranslations("common.flow.kind");
  const tStatus = useTranslations("common.flow.status");
  const tType = useTranslations("adminBracket.labels.types");
  const rename = (name: string) => onChange({ name, ...(node.stage ? { stage: { ...node.stage, name } } : {}) });
  const base = `/admin/tournaments/${tournamentId}`;

  let body = null;
  if (!isLifecycle(node.kind)) {
    body = <PureNodeBody tournament={tournament} node={node} read={read} readOnly={readOnly} onChange={onChange} />;
  } else if (node.kind === "registration") {
    body = (
      <>
        <RegistrationFields node={node} readOnly={readOnly} onChange={onChange} />
        {node.id === null ? null : (
          <ScreenLink href={`${base}/settings/registration?node=${node.id}`}>{t("openRegistration")}</ScreenLink>
        )}
      </>
    );
  } else if (node.kind === "formation") {
    const screen = node.id === null ? null : formationScreen(tournamentId, node.id, String(node.config.mode ?? "manual"));
    body = (
      <>
        <FormationMode tournament={tournament} node={node} readOnly={readOnly} onChange={onChange} />
        {screen ? <ScreenLink href={screen.href}>{t(screen.label)}</ScreenLink> : null}
      </>
    );
  } else if (node.stage) {
    body = (
      <SelectField
        label={t("stageType")}
        value={node.stage.stage_type}
        options={Object.keys(STAGE_TYPE_LABELS).map((type) => [type, tType(type as never)] as const)}
        disabled={readOnly}
        onChange={(stage_type) => onChange({ stage: { ...node.stage!, stage_type } as NonNullable<DraftNode["stage"]> })}
      />
    );
  } else {
    const stage = tournament.stages?.find((s) => s.id === node.stageId);
    body = (
      <>
        {stage ? (
          <div className="grid gap-1.5">
            <p className="text-label text-muted-foreground">{t("stageType")}</p>
            <p className="text-caption">{tType(stage.stage_type as never)}</p>
          </div>
        ) : null}
        <ScreenLink href={`${base}/bracket?stage=${node.stageId}`}>{t("openStage")}</ScreenLink>
      </>
    );
  }

  return (
    <aside className="space-y-4 self-start rounded-lg border bg-card p-4" aria-label={node.name}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-label text-muted-foreground">
            {[tKind(node.kind), node.status ? tStatus(node.status) : null].filter(Boolean).join(" · ")}
          </p>
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
