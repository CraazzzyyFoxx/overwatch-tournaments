import React from "react";
import Link from "next/link";
import { ArrowRight, CircleMinus, CirclePlus } from "lucide-react";

import userService from "@/services/user.service";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EncounterWithUserStats, UserEncounterTournament } from "@/types/user.types";

export interface UserRecentEncountersCardProps {
  userId: number;
  userName: string;
  limit?: number;
}

const getTournamentLabel = (tournament?: UserEncounterTournament | null) => {
  if (!tournament) {
    return "Tournament";
  }
  if (tournament.is_league) {
    return tournament.name;
  }
  return `Tournament ${tournament.number}`;
};

const getStageLabel = (encounter: EncounterWithUserStats) =>
  encounter.stage_item?.name ?? encounter.stage?.name ?? "";

const UserRecentEncountersCard = async ({
  userId,
  userName,
  limit = 5,
}: UserRecentEncountersCardProps) => {
  const encounters = await userService.getUserEncounters(userId, 1, limit);

  if (encounters.results.length === 0) {
    return null;
  }

  const userSlug = userName.replace("#", "-");

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="text-xl">Recent encounters</CardTitle>
          <CardDescription>Latest matches this player participated in.</CardDescription>
        </div>
        <Link
          href={`/users/${userSlug}?tab=matches`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          See all
          <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </CardHeader>

      <CardContent className="p-0">
        <div className="divide-y divide-border/40">
          {encounters.results.map((encounter: EncounterWithUserStats) => {
            const tournamentLabel = getTournamentLabel(encounter.tournament);
            const stageLabel = getStageLabel(encounter);
            const meta = stageLabel
              ? `${tournamentLabel} - ${stageLabel}`
              : tournamentLabel;
            const score = `${encounter.score.home}-${encounter.score.away}`;

            return (
              <Link
                key={encounter.id}
                href={`/encounters/${encounter.id}`}
                className="flex items-center justify-between gap-4 p-4 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <div className="min-w-0">
                  <div className="text-xs text-muted-foreground">{meta}</div>
                  <div className="text-sm font-medium truncate">{encounter.name}</div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="text-sm font-semibold tabular-nums">{score}</span>
                  {encounter.has_logs ? (
                    <CirclePlus className="h-4 w-4 text-emerald-500" aria-label="Has logs" />
                  ) : (
                    <CircleMinus className="h-4 w-4 text-red-500" aria-label="No logs" />
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};

export default UserRecentEncountersCard;
