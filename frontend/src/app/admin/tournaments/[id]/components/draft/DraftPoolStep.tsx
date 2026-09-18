"use client";

import { AlertTriangle, CheckCircle2, Link2Off, ShieldAlert, Users, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { TONE_CLASS } from "@/components/admin/tone";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DraftFeasibility, DraftRole } from "@/types/draft.types";

import type { DraftPoolReadiness } from "./setup-model";

interface DraftPoolStepProps {
  readiness: DraftPoolReadiness;
  feasibility?: DraftFeasibility | null;
  loading: boolean;
  failed: boolean;
}

const ROLES: DraftRole[] = ["tank", "damage", "support"];
const BLOCKER_MESSAGE_KEYS = {
  not_enough_players: "blockers.not_enough_players",
  pool_unranked: "blockers.pool_unranked",
  "role_shortage:tank": "blockers.role_shortage_tank",
  "role_shortage:damage": "blockers.role_shortage_damage",
  "role_shortage:support": "blockers.role_shortage_support"
} as const;

export function DraftPoolStep({ readiness, feasibility, loading, failed }: Readonly<DraftPoolStepProps>) {
  const t = useTranslations("draftAdmin");
  const percent = readiness.requiredPlayers
    ? Math.min(100, Math.round((readiness.actualPlayers / readiness.requiredPlayers) * 100))
    : 0;

  if (loading) {
    return <Skeleton className="h-52 w-full rounded-2xl" />;
  }
  if (failed) {
    return (
      <div className={cn("rounded-2xl border p-5 text-sm", TONE_CLASS.danger)}>
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
          <StatusPill tone={readiness.blockers.length === 0 ? "success" : "danger"}>
            {readiness.blockers.length === 0 ? t("poolReady") : t("poolBlocked")}
          </StatusPill>
        </div>
        <Progress value={percent} className="mt-4 h-2" aria-label={t("poolPlayers")} />
      </div>

      <StatTileGrid className="sm:grid-cols-3 md:grid-cols-3 xl:grid-cols-3">
        <StatTile
          icon={AlertTriangle}
          label={t("missingRanks")}
          value={readiness.missingRanks}
          tone={readiness.missingRanks > 0 ? "warning" : "neutral"}
        />
        <StatTile
          icon={Link2Off}
          label={t("missingAccounts")}
          value={readiness.missingAccounts}
          tone={readiness.missingAccounts > 0 ? "warning" : "neutral"}
        />
        <StatTile icon={XCircle} label={t("excludedPlayers")} value={readiness.excludedPlayers} />
      </StatTileGrid>

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
                    <ShieldAlert
                      className="h-4 w-4 text-danger"
                      role="img"
                      aria-label={t("blocker")}
                    />
                  ) : (
                    <CheckCircle2
                      className="h-4 w-4 text-success"
                      role="img"
                      aria-label={t("ready")}
                    />
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {(readiness.blockers.length > 0 || (feasibility && !feasibility.is_feasible)) && (
        <div className={cn("rounded-2xl border p-4", TONE_CLASS.danger)}>
          <div className="flex gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
            <div>
              <h3 className="font-medium">{t("blockingIssues")}</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {readiness.blockers.map((blocker) => (
                  <li key={blocker}>
                    {t(BLOCKER_MESSAGE_KEYS[blocker as keyof typeof BLOCKER_MESSAGE_KEYS], {
                      count: readiness.missingRanks
                    })}
                  </li>
                ))}
                {feasibility?.slot_deficits.map((deficit) => (
                  <li key={deficit.slot_code}>
                    {t("roleDeficit", {
                      role: t(`roles.${deficit.slot_code}`),
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
        <div
          className={cn(
            "flex items-center gap-3 rounded-xl border px-4 py-3 text-sm",
            TONE_CLASS.success
          )}
        >
          <Users className="h-5 w-5 shrink-0" aria-hidden />
          {t("poolCanContinue")}
        </div>
      )}
    </div>
  );
}
