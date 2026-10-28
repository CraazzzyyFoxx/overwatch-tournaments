"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { NextActionHero } from "@/components/kit/NextActionHero";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import adminService from "@/services/admin.service";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { tabError, tabFallback, useHubStagesQuery, useHubTournamentQuery } from "../hubQueries";
import { buildChecklist, hasChallongeSource, pickNextAction } from "@/components/admin/tournament-checklist";
import { LifecycleChecklist } from "./LifecycleChecklist";
import { PhaseStepper } from "./PhaseStepper";

/** Overview (T3 body): the next action, where the tournament is, what it still needs. */
export default function OverviewTabPage() {
  const t = useTranslations("adminTournament.overview");
  const checklistT = useTranslations("adminTournaments.checklist");
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const isValidTournamentId = Number.isFinite(tournamentId) && tournamentId > 0;

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const stagesQuery = useHubStagesQuery(tournamentId);
  // Living-checklist data (§3, D13). Freshness comes from window focus and the
  // shell's realtime invalidation — deliberately NO refetchInterval (CG-O4).
  const readinessQuery = useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).readiness,
    queryFn: () => adminService.getTournamentReadiness(tournamentId),
    enabled: isValidTournamentId,
    refetchOnWindowFocus: true
  });

  const tournament = tournamentQuery.data;

  if (tournamentQuery.isLoading || stagesQuery.isLoading) {
    return tabFallback;
  }
  if (!tournament) {
    return tabError(tournamentQuery.refetch);
  }

  const readiness = readinessQuery.data;
  const checklistItems = readiness
    ? buildChecklist(readiness, {
        basePath: `/admin/tournaments/${tournamentId}`,
        status: tournament.status,
        hasChallongeSource: hasChallongeSource(tournament, stagesQuery.data ?? [])
      }, checklistT)
    : [];
  const draftStatus = readiness?.draft_session_status;
  const draftRunning = draftStatus === "live" || draftStatus === "paused";

  // F3 ·3: the one thing worth doing next. Same `buildChecklist` the list
  // below renders — ranked, not a second data source, so the hero and the
  // checklist can never disagree. Nothing open: no hero — the status
  // transition is the header's job.
  const nextAction = pickNextAction(checklistItems);

  return (
    <div className="flex flex-col gap-4">
      {nextAction?.href ? (
        <NextActionHero
          eyebrow={t("nextAction")}
          title={
            nextAction.detail
              ? t("nextActionTitle", { label: nextAction.label, detail: nextAction.detail })
              : nextAction.label
          }
          href={nextAction.href}
          cta={t("open")}
        />
      ) : null}
      <PhaseStepper tournament={tournament} />
      {/* Draft live -> Open draft board (§15): the shortest path to the work. */}
      {draftRunning ? (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>{t("teamDraft", { status: draftStatus })}</span>
            <Button asChild size="sm" variant="outline" className="shrink-0">
              <Link href={`/admin/tournaments/${tournamentId}/teams/draft`}>{t("openDraftBoard")}</Link>
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
      {readinessQuery.isError ? (
        tabError(readinessQuery.refetch)
      ) : (
        <LifecycleChecklist items={checklistItems} isLoading={readinessQuery.isLoading} />
      )}
    </div>
  );
}
