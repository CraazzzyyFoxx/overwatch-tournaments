"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { FactList } from "@/components/kit/FactList";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftFormatSettings, DraftSeedResponse } from "@/types/draft.types";

import { DraftReseedDiff } from "./DraftReseedDiff";
import type { DraftPoolReadiness } from "./setup-model";
import { DraftSetupPreview } from "./DraftSetupPreview";
import type { DraftCaptainSetup, DraftSetupConfig } from "./setup-types";

interface DraftReviewStepProps {
  config: DraftSetupConfig;
  /** The team count in effect (pinned, else the pool's maximum). */
  teamCount: number;
  /** The format the session is drafted with, resolved to `rounds`. */
  format: DraftFormatSettings;
  /** `roster_shape.draft_rounds` from the server; never derived from a size. */
  rounds: number;
  captains: DraftCaptainSetup;
  orderedCaptainIds: number[];
  pool: AdminRegistration[];
  readiness: DraftPoolReadiness;
  preview: DraftSeedResponse | null;
  previewPending: boolean;
  previewError: boolean;
  isReseed: boolean;
}

export function DraftReviewStep({
  config,
  teamCount,
  format,
  rounds,
  captains,
  orderedCaptainIds,
  pool,
  readiness,
  preview,
  previewPending,
  previewError,
  isReseed
}: Readonly<DraftReviewStepProps>) {
  const t = useTranslations("draftAdmin");
  const checks = [
    { label: t("reviewChecks.pool"), ok: readiness.blockers.length === 0 },
    { label: t("reviewChecks.captains"), ok: captains.ids.length === teamCount },
    { label: t("reviewChecks.roles"), ok: preview?.feasibility.is_feasible ?? false },
    {
      label: t("reviewChecks.accounts"),
      ok: captains.ids.every((id) => pool.find((entry) => entry.id === id)?.user_id != null)
    },
    { label: t("reviewChecks.order"), ok: orderedCaptainIds.length === teamCount },
    { label: t("reviewChecks.timer"), ok: config.pickTimeSeconds >= 10 }
  ];

  return (
    <div className="space-y-6">
      {previewPending && (
        <p role="status" className="text-sm text-muted-foreground">
          {t("validatingDraft")}
        </p>
      )}
      {previewError && (
        <Alert tone="danger">
          <AlertTitle>{t("previewFailed")}</AlertTitle>
          <AlertDescription>{t("previewFailedHint")}</AlertDescription>
        </Alert>
      )}

      <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {checks.map((check) => (
          <li key={check.label} className="flex items-center gap-3 text-sm">
            {check.ok ? (
              <CheckCircle2
                className="h-4 w-4 shrink-0 text-success"
                role="img"
                aria-label={t("ready")}
              />
            ) : (
              <XCircle
                className="h-4 w-4 shrink-0 text-danger"
                role="img"
                aria-label={t("blocker")}
              />
            )}
            {check.label}
          </li>
        ))}
      </ul>

      <FactList
        size="sm"
        facts={[
          { label: t("teamCount"), value: teamCount },
          { label: t("poolPlayers"), value: readiness.actualPlayers },
          { label: t("totalPicks"), value: teamCount * rounds },
          { label: t("pickTime"), value: `${config.pickTimeSeconds}s` },
          {
            label: t("overtime"),
            value: config.overtimeSeconds > 0 ? `${config.overtimeSeconds}s` : t("overtimeOff")
          }
        ]}
      />

      {isReseed && preview && (
        <section>
          <h3 className="text-sm font-semibold">{t("reseedDiff")}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{t("reseedDiffHint")}</p>
          <DraftReseedDiff diff={preview.diff} />
        </section>
      )}

      <DraftSetupPreview
        orderedCaptainIds={orderedCaptainIds}
        pool={pool}
        rounds={rounds}
        format={format.format}
        roundRules={format.round_rules}
      />
    </div>
  );
}
