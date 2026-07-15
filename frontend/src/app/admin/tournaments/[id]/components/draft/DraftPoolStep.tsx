"use client";

import { AlertTriangle, CheckCircle2, Link2Off, ShieldAlert, Users, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { DraftFeasibility, DraftRole } from "@/types/draft.types";

import type { DraftPoolReadiness } from "./setup-model";

interface DraftPoolStepProps {
  readiness: DraftPoolReadiness;
  feasibility?: DraftFeasibility | null;
  loading: boolean;
  failed: boolean;
}

const ROLES: DraftRole[] = ["tank", "dps", "support"];
const BLOCKER_MESSAGE_KEYS = {
  not_enough_players: "blockers.not_enough_players",
  "role_shortage:tank": "blockers.role_shortage_tank",
  "role_shortage:dps": "blockers.role_shortage_dps",
  "role_shortage:support": "blockers.role_shortage_support"
} as const;

export function DraftPoolStep({ readiness, feasibility, loading, failed }: DraftPoolStepProps) {
  const t = useTranslations("draftAdmin");
  const percent = readiness.requiredPlayers
    ? Math.min(100, Math.round((readiness.actualPlayers / readiness.requiredPlayers) * 100))
    : 0;

  if (loading) {
    return <div className="h-52 animate-pulse rounded-2xl bg-muted/50" />;
  }
  if (failed) {
    return (
      <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-5 text-sm text-destructive">
        {t("poolLoadFailed")}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border/70 bg-card p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-muted-foreground">{t("poolPlayers")}</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {readiness.actualPlayers}
              <span className="ml-1 text-base font-normal text-muted-foreground">
                / {readiness.requiredPlayers}
              </span>
            </p>
          </div>
          <Badge variant={readiness.blockers.length === 0 ? "default" : "destructive"}>
            {readiness.blockers.length === 0 ? t("poolReady") : t("poolBlocked")}
          </Badge>
        </div>
        <Progress value={percent} className="mt-4 h-2" />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric
          icon={AlertTriangle}
          label={t("missingRanks")}
          value={readiness.missingRanks}
          warning={readiness.missingRanks > 0}
        />
        <Metric
          icon={Link2Off}
          label={t("missingAccounts")}
          value={readiness.missingAccounts}
          warning={readiness.missingAccounts > 0}
        />
        <Metric
          icon={XCircle}
          label={t("excludedPlayers")}
          value={readiness.excludedPlayers}
          warning={false}
        />
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">{t("roleCoverage")}</h3>
        <div className="grid gap-3 sm:grid-cols-3">
          {ROLES.map((role) => {
            const blocked = readiness.blockers.includes(`role_shortage:${role}`);
            return (
              <div
                key={role}
                className="flex items-center justify-between rounded-xl border border-border/70 bg-muted/20 px-4 py-3"
              >
                <span className="text-sm font-medium">{t(`roles.${role}`)}</span>
                <span className="flex items-center gap-2">
                  <strong className="tabular-nums">{readiness.roleCoverage[role]}</strong>
                  {blocked ? (
                    <ShieldAlert className="h-4 w-4 text-destructive" aria-label={t("blocker")} />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-label={t("ready")} />
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {(readiness.blockers.length > 0 || (feasibility && !feasibility.is_feasible)) && (
        <div className="rounded-2xl border border-destructive/30 bg-destructive/8 p-4">
          <div className="flex gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <div>
              <h3 className="font-medium text-destructive">{t("blockingIssues")}</h3>
              <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                {readiness.blockers.map((blocker) => (
                  <li key={blocker}>
                    • {t(BLOCKER_MESSAGE_KEYS[blocker as keyof typeof BLOCKER_MESSAGE_KEYS])}
                  </li>
                ))}
                {feasibility?.role_deficits.map((deficit) => (
                  <li key={deficit.role}>
                    • {t("roleDeficit", {
                      role: t(`roles.${deficit.role}`),
                      count: deficit.unmatched_slots
                    })}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {readiness.blockers.length === 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-800 dark:text-emerald-100">
          <Users className="h-5 w-5" />
          {t("poolCanContinue")}
        </div>
      )}
    </div>
  );
}

interface MetricProps {
  icon: typeof AlertTriangle;
  label: string;
  value: number;
  warning: boolean;
}

function Metric({ icon: Icon, label, value, warning }: MetricProps) {
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4">
      <div className="flex items-center justify-between">
        <Icon className={warning ? "h-4 w-4 text-amber-500" : "h-4 w-4 text-muted-foreground"} />
        <span className="text-xl font-semibold tabular-nums">{value}</span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
