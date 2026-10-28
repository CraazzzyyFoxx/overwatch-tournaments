"use client";

import { useId } from "react";
import { CheckCircle2, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { FactList } from "@/components/kit/FactList";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import type { DraftFeasibility } from "@/types/draft.types";

import { MAX_DRAFT_TEAM_COUNT, MIN_DRAFT_TEAM_COUNT, type DraftPoolReadiness } from "./setup-model";

interface DraftPoolStepProps {
  readiness: DraftPoolReadiness;
  feasibility?: DraftFeasibility | null;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  /** The team count in effect: the pinned one, else the pool's maximum. */
  teamCount: number;
  /** `maxDraftTeamCount` — how many teams this pool can fill at most. */
  maxTeamCount: number;
  /** False while the count follows the maximum. */
  pinned: boolean;
  /** A number pins the count; `null` follows the maximum again. */
  onTeamCountChange: (next: number | null) => void;
  locked?: boolean;
  /** The owner game's role dictionary: the names of the roles the pool must cover. */
  ontology: RoleOntology | null;
}

export function DraftPoolStep({
  readiness,
  feasibility,
  loading,
  failed,
  onRetry,
  teamCount,
  maxTeamCount,
  pinned,
  onTeamCountChange,
  locked = false,
  ontology
}: Readonly<DraftPoolStepProps>) {
  const t = useTranslations("draftAdmin");
  const slotLabel = useSlotLabel(ontology);
  // A one-role game's every seat is that role: its shortage is a count of seats, named by no role.
  const named = showsRoles(ontology);
  // Max is disabled while locked or already following the maximum; these lines say why.
  const maxHintId = useId();
  const lockedHintId = useId();
  const percent = readiness.requiredPlayers
    ? Math.min(100, Math.round((readiness.actualPlayers / readiness.requiredPlayers) * 100))
    : 0;

  if (loading) {
    return <Skeleton className="h-52 w-full rounded-xl" />;
  }
  if (failed) {
    return <PageStateCard state="error" description={t("poolLoadFailed")} onAction={onRetry} />;
  }

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm text-muted-foreground">{t("poolPlayers")}</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {readiness.actualPlayers}
              <span className="ml-1 text-base font-normal text-muted-foreground">
                / {readiness.requiredPlayers}
              </span>
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="draft-team-count">{t("teamCount")}</Label>
            <div className="flex items-center gap-2">
              <NumberInput
                id="draft-team-count"
                integer
                min={MIN_DRAFT_TEAM_COUNT}
                max={MAX_DRAFT_TEAM_COUNT}
                disabled={locked}
                value={teamCount}
                onValueChange={(next) => onTeamCountChange(next ?? MIN_DRAFT_TEAM_COUNT)}
                className="w-20"
              />
              <Button
                type="button"
                variant="outline"
                disabled={locked || !pinned}
                aria-describedby={locked ? `${maxHintId} ${lockedHintId}` : maxHintId}
                onClick={() => onTeamCountChange(null)}
              >
                {t("teamCountMax")}
              </Button>
            </div>
            <p id={maxHintId} className="text-xs tabular-nums text-muted-foreground">
              {t("teamCountMaxHint", { count: maxTeamCount })}
            </p>
            {locked && (
              <p id={lockedHintId} className="text-xs text-muted-foreground">
                {t("teamCountLocked")}
              </p>
            )}
          </div>
        </div>
        <Progress value={percent} className="mt-4" aria-label={t("poolPlayers")} />
        <FactList
          className="mt-4"
          facts={[
            {
              label: t("missingRanks"),
              value: readiness.missingRanks,
              tone: readiness.missingRanks > 0 ? "warning" : undefined
            },
            {
              label: t("missingAccounts"),
              value: readiness.missingAccounts,
              tone: readiness.missingAccounts > 0 ? "warning" : undefined
            },
            { label: t("excludedPlayers"), value: readiness.excludedPlayers }
          ]}
        />
      </Card>

      {named && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">{t("roleCoverage")}</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            {Object.keys(readiness.roleCoverage).map((role) => {
              const blocked = readiness.blockers.includes(`role_shortage:${role}`);
              return (
                <div
                  key={role}
                  className="flex items-center justify-between rounded-xl border border-border px-4 py-3"
                >
                  <span className="text-sm font-medium">{slotLabel(role)}</span>
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
      )}

      {(readiness.blockers.length > 0 || (feasibility && !feasibility.is_feasible)) && (
        <Alert tone="warning">
          <ShieldAlert className="size-4" aria-hidden />
          <AlertTitle>{t("blockingIssues")}</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
              {readiness.blockers.map((blocker) => (
                <li key={blocker}>
                  {blocker.startsWith("role_shortage:")
                    ? named
                      ? t("blockers.role_shortage", { role: slotLabel(blocker.slice("role_shortage:".length)) })
                      : t("blockers.seat_shortage")
                    : blocker === "pool_unranked"
                      ? t("blockers.pool_unranked", { count: readiness.missingRanks })
                      : t("blockers.not_enough_players")}
                </li>
              ))}
              {feasibility?.slot_deficits.map((deficit) => (
                <li key={deficit.slot_code}>
                  {named
                    ? t("roleDeficit", { role: slotLabel(deficit.slot_code), count: deficit.unmatched_slots })
                    : t("seatDeficit", { count: deficit.unmatched_slots })}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
