"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { GitBranch, Link2, MessageSquare, ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { NextActionHero } from "@/components/kit/NextActionHero";
import type { Tone } from "@/components/kit/tone";
import adminService from "@/services/admin.service";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { tabFallback, useHubStagesQuery, useHubTournamentQuery } from "../hubQueries";
import { buildChecklist, hasChallongeSource } from "@/components/admin/tournament-checklist";
import { LifecycleChecklist } from "./LifecycleChecklist";
import { PhaseStepper } from "./PhaseStepper";

export default function OverviewTabPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const isValidTournamentId = Number.isFinite(tournamentId) && tournamentId > 0;

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const stagesQuery = useHubStagesQuery(tournamentId);
  const discordChannelQuery = useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).discordChannel,
    queryFn: () => adminService.getDiscordChannel(tournamentId),
    enabled: isValidTournamentId
  });
  // Living-checklist data (§3, D13). Freshness comes from window focus and the
  // shell's realtime invalidation — deliberately NO refetchInterval (CG-O4).
  const readinessQuery = useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).readiness,
    queryFn: () => adminService.getTournamentReadiness(tournamentId),
    enabled: isValidTournamentId,
    refetchOnWindowFocus: true
  });

  const tournament = tournamentQuery.data;
  const stages = stagesQuery.data ?? [];

  if (tournamentQuery.isLoading || stagesQuery.isLoading) {
    return tabFallback;
  }
  if (!tournament) {
    return null;
  }

  const basePath = `/admin/tournaments/${tournamentId}`;
  const challongeSourced = hasChallongeSource(tournament, stages);
  const readiness = readinessQuery.data;
  const checklistItems = readiness
    ? buildChecklist(readiness, {
        basePath,
        schedule: tournament.phase_schedule.map((entry) => entry.status),
        hasChallongeSource: challongeSourced
      })
    : [];
  const draftSessionStatus = readiness?.draft_session_status;
  const draftRunning = draftSessionStatus === "live" || draftSessionStatus === "paused";

  // F3 ·3: the one thing worth doing next. Same `buildChecklist` the list
  // below renders — ranked, not a second data source, so the hero and the
  // checklist can never disagree.
  const nextAction = checklistItems.find(
    (item) => (item.state === "warn" || item.state === "todo") && item.href
  );
  const logsTotal = readiness?.encounters_total ?? 0;
  const logsCovered = readiness?.encounters_with_logs ?? 0;
  const logCoverage = logsTotal > 0 ? Math.round((logsCovered / logsTotal) * 100) : null;

  // Read-only integration state. Configuring these lives on the Settings tab —
  // Overview answers "where is this tournament", not "how is it wired".
  const discordChannel = discordChannelQuery.data;
  const linkedStagesCount = stages.filter((stage) => Boolean(stage.challonge_slug)).length;
  const structuredStagesCount = stages.filter((stage) => stage.items.length > 0).length;
  const stagesTone: Tone =
    stages.length === 0 || structuredStagesCount < stages.length ? "warning" : "success";
  const discordTone: Tone = discordChannel?.is_active
    ? "success"
    : discordChannel
      ? "neutral"
      : "warning";

  return (
    <div className="flex flex-col gap-4">
      {nextAction ? (
        <NextActionHero
          eyebrow="Next action"
          title={nextAction.detail ? `${nextAction.label} — ${nextAction.detail}` : nextAction.label}
          href={nextAction.href!}
          cta="Open"
        />
      ) : null}
      <PhaseStepper tournament={tournament} />
      {draftRunning ? (
        // "Draft live -> Teams" banner (UA-O9). PR-2c moved the draft board
        // under the Teams tab, so this links straight at its final address
        // instead of riding the draft->teams redirect.
        <Card className="border-warning/40 bg-warning/10">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="text-sm text-warning">
              Team draft is {draftSessionStatus} — manage it from the draft board.
            </p>
            <Button asChild size="sm" variant="outline">
              <Link href={`${basePath}/teams/draft`}>Open draft board</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}
      <LifecycleChecklist items={checklistItems} isLoading={readinessQuery.isLoading} />
      <StatTileGrid className="xl:grid-cols-4">
        <StatTile
          label="Stages"
          value={stages.length === 0 ? "None yet" : `${stages.length} configured`}
          detail={
            stages.length === 0
              ? "Add a stage before match operations"
              : `${structuredStagesCount}/${stages.length} with structure`
          }
          tone={stagesTone}
          icon={GitBranch}
        />
        <StatTile
          label="Challonge"
          value={challongeSourced ? "Connected" : "Manual"}
          detail={
            challongeSourced
              ? `${linkedStagesCount} linked stage${linkedStagesCount === 1 ? "" : "s"}`
              : "Brackets are managed in this workspace"
          }
          tone={challongeSourced ? "success" : "neutral"}
          icon={Link2}
        />
        <StatTile
          label="Discord"
          value={
            discordChannelQuery.isLoading
              ? "Checking…"
              : discordChannel?.is_active
                ? "Monitoring"
                : discordChannel
                  ? "Paused"
                  : "Not configured"
          }
          detail={discordChannel?.channel_name ?? "Match log intake"}
          tone={discordTone}
          icon={MessageSquare}
        />
        <StatTile
          label="Log coverage"
          value={logCoverage === null ? "—" : `${logCoverage}%`}
          detail={
            logsTotal === 0
              ? "No encounters yet"
              : `${logsCovered}/${logsTotal} encounters with logs`
          }
          tone={logCoverage === null ? "neutral" : logCoverage >= 90 ? "success" : "warning"}
          icon={ScrollText}
        />
      </StatTileGrid>
    </div>
  );
}
