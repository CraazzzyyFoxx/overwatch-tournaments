"use client";

import { useId, type ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Switch } from "@/components/ui/switch";
import type { DraftNode } from "@/lib/flow/flowDraft";
import { nodeDraftFormat, registrationNodeConfig } from "@/lib/tournament/flow-nodes";
import type { Tournament } from "@/types/tournament.types";

import { DraftFormatFields } from "../../../components/draft/DraftFormatFields";
import { resolveDraftFormat } from "../../../components/draft/setup-model";
import { SelectField } from "./fields";

type Props = Readonly<{ node: DraftNode; readOnly: boolean; onChange: (patch: Pick<DraftNode, "config">) => void }>;

/** The one way out of the inspector: the full screen of what the node stands for. */
export function ScreenLink({ href, children }: Readonly<{ href: string; children: ReactNode }>) {
  return (
    <Button asChild variant="outline" size="sm">
      <Link href={href}>{children}</Link>
    </Button>
  );
}

/** What a registration passes on down the graph: who signs up, and whether only checked-in entries move on. */
export function RegistrationFields({ node, readOnly, onChange }: Props) {
  const tIntake = useTranslations("registrationFormAdmin.page.intake");
  const tStatus = useTranslations("registrationFormAdmin.status");
  const checkInId = useId();
  const config = registrationNodeConfig(node);
  return (
    <>
      <SelectField
        label={tIntake("label")}
        value={config.intake}
        options={[
          ["solo", tIntake("solo")],
          ["team", tIntake("team")]
        ]}
        disabled={readOnly}
        onChange={(intake) => onChange({ config: { ...node.config, intake } })}
      />
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-0.5">
          <Label htmlFor={checkInId}>{tStatus("checkInLabel")}</Label>
          <p className="text-caption text-muted-foreground">{tStatus("checkInHint")}</p>
        </div>
        <Switch
          id={checkInId}
          checked={config.check_in}
          disabled={readOnly}
          onCheckedChange={(check_in) => onChange({ config: { ...node.config, check_in } })}
        />
      </div>
    </>
  );
}

const MODES = ["balancer", "draft", "registered", "manual"] as const;

/**
 * The mode and, in `draft` mode, the draft format rule edit the draft config (a saved node may change its mode only
 * while `draft`). The server refuses a format change while a draft is in flight.
 */
export function FormationMode({ tournament, node, readOnly, onChange }: Props & Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("adminTournament.flow.inspector");
  const tDraft = useTranslations("draftAdmin");
  const rounds = tournament.roster_shape?.draft_rounds ?? 0;
  const locked = tournament.roster_locked_by_draft === true;
  return (
    <>
      <SelectField
        label={t("mode")}
        value={String(node.config.mode ?? "manual")}
        options={MODES.map((mode) => [mode, t(`modes.${mode}`)] as const)}
        disabled={readOnly || (node.id !== null && node.status !== "draft")}
        onChange={(mode) => onChange({ config: { ...node.config, mode } })}
      />
      {node.config.mode === "draft" ? (
        <div className="space-y-2">
          {locked ? <p className="text-caption text-warning">{tDraft("formatLockedByDraft")}</p> : null}
          <DraftFormatFields
            value={resolveDraftFormat(nodeDraftFormat(node), rounds)}
            rounds={rounds}
            disabled={readOnly || locked}
            onChange={(draft_format) => onChange({ config: { ...node.config, draft_format } })}
          />
        </div>
      ) : null}
    </>
  );
}

/** The screen a saved formation's teams are made on, by its mode. */
export function formationScreen(tournamentId: number, nodeId: number, mode: string) {
  const base = `/admin/tournaments/${tournamentId}`;
  switch (mode) {
    case "balancer":
      return { href: `/balancer?tournament=${tournamentId}&node=${nodeId}`, label: "openBalancer" } as const;
    case "draft":
      return { href: `${base}/teams/draft?node=${nodeId}`, label: "openDraft" } as const;
    case "registered":
      return { href: `${base}/registration/teams`, label: "openRegisteredTeams" } as const;
    default:
      return { href: `${base}/teams/roster`, label: "openRoster" } as const;
  }
}
