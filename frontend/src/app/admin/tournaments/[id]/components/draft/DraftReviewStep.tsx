"use client";

import { AlertTriangle, CheckCircle2, EyeOff, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftSeedResponse } from "@/types/draft.types";

import type { DraftPoolReadiness } from "./setup-model";
import { DraftSetupPreview } from "./DraftSetupPreview";
import type { DraftCaptainSetup, DraftSetupConfig } from "./setup-types";

interface DraftReviewStepProps {
  config: DraftSetupConfig;
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
  captains,
  orderedCaptainIds,
  pool,
  readiness,
  preview,
  previewPending,
  previewError,
  isReseed
}: DraftReviewStepProps) {
  const t = useTranslations("draftAdmin");
  const checks = [
    { label: t("reviewChecks.pool"), ok: readiness.blockers.length === 0 },
    { label: t("reviewChecks.captains"), ok: captains.ids.length === config.teamCount },
    { label: t("reviewChecks.roles"), ok: preview?.feasibility.is_feasible ?? false },
    {
      label: t("reviewChecks.accounts"),
      ok: captains.ids.every((id) => pool.find((entry) => entry.id === id)?.user_id != null)
    },
    { label: t("reviewChecks.order"), ok: orderedCaptainIds.length === config.teamCount },
    { label: t("reviewChecks.timer"), ok: config.pickTimeSeconds >= 10 },
    { label: t("reviewChecks.privacy"), ok: true }
  ];

  return (
    <div className="space-y-6">
      {previewPending && (
        <div className="flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm">
          <RefreshCw className="h-4 w-4 animate-spin text-primary" />
          {t("validatingDraft")}
        </div>
      )}
      {previewError && (
        <div className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" />
          {t("previewFailed")}
        </div>
      )}

      <div className="grid gap-2 sm:grid-cols-2">
        {checks.map((check) => (
          <div
            key={check.label}
            className="flex items-center gap-3 rounded-xl border border-border/70 bg-card px-4 py-3"
          >
            {check.ok ? (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
            ) : (
              <XCircle className="h-5 w-5 shrink-0 text-destructive" />
            )}
            <span className="text-sm">{check.label}</span>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Summary label={t("teams")} value={config.teamCount} />
        <Summary label={t("players")} value={readiness.actualPlayers} />
        <Summary label={t("totalPicks")} value={config.teamCount * (config.teamSize - 1)} />
      </div>

      {isReseed && preview && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="font-medium">{t("reseedDiff")}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{t("reseedDiffHint")}</p>
            </div>
            <Badge variant="outline">{t("dryRun")}</Badge>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <Diff label={t("teams")} before={preview.diff.teams_before} after={preview.diff.teams_after} />
            <Diff label={t("players")} before={preview.diff.players_before} after={preview.diff.players_after} />
            <Diff label={t("picks")} before={preview.diff.picks_before} after={preview.diff.picks_after} />
          </div>
        </div>
      )}

      <DraftSetupPreview
        orderedCaptainIds={orderedCaptainIds}
        pool={pool}
        rounds={config.teamSize - 1}
        format={config.format}
        roundRules={config.roundRules}
      />

      <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
        <div className="flex gap-3">
          <EyeOff className="mt-0.5 h-5 w-5 text-muted-foreground" />
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold">{t("privacyCheck")}</h3>
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{t("privacyCheckHint")}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function Diff({ label, before, after }: { label: string; before: number; after: number }) {
  return (
    <div className="rounded-xl bg-background/70 px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-sm">
        {before} → <strong>{after}</strong>
      </p>
    </div>
  );
}

