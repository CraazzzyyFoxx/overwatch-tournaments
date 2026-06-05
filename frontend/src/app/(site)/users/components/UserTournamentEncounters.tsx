"use client";

import React from "react";
import { UserTournament } from "@/types/user.types";
import { useRouter } from "next/navigation";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import HeroImage from "@/components/hero/HeroImage";
import { PerformanceBadgeWithTooltip } from "@/components/PerformanceBagde";
import { CircleMinus, CirclePlus } from "lucide-react";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";

export interface UserTournamentEncountersProps {
  tournament: UserTournament;
  team_id: number;
}

const UserTournamentEncounters = ({ tournament, team_id }: UserTournamentEncountersProps) => {
  const { push } = useRouter();

  return (
    <ScrollArea>
      <TooltipProvider>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[350px]">Match</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Heroes</TableHead>
              <TableHead>MVP Score</TableHead>
              <TableHead className="text-center">Closeness</TableHead>
              <TableHead className="text-center">Logs</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tournament.encounters.map((encounter) => {
              const heroSet = new Set<string>();
              let color = "from-transparent";
              if (
                team_id == encounter.home_team_id &&
                encounter.score.home > encounter.score.away
              ) {
                color = "from-[#5ee790]";
              }
              if (
                team_id == encounter.home_team_id &&
                encounter.score.home < encounter.score.away
              ) {
                color = "from-[#e4485d]";
              }
              if (
                team_id == encounter.away_team_id &&
                encounter.score.home < encounter.score.away
              ) {
                color = "from-[#5ee790]";
              }
              if (
                team_id == encounter.away_team_id &&
                encounter.score.home > encounter.score.away
              ) {
                color = "from-[#e4485d]";
              }
              encounter.matches.forEach((match) => {
                match.heroes.forEach((hero) => {
                  heroSet.add(hero.image_path);
                });
              });

              const heroes = Array.from(heroSet);

              return (
                <TableRow
                  key={encounter.id}
                  onClick={() => {
                    push(`/encounters/${encounter.id}`);
                  }}
                >
                  <TableCell
                    className={`w-[50px] z-0 transition-colors bg-gradient-to-r ${color} to-transparent to-65%`}
                  >
                    {encounter.name}
                  </TableCell>
                  <TableCell>
                    {encounter.score.home} - {encounter.score.away}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-row gap-2 xs:w-[140px] md:w-full overflow-hidden">
                      {heroes.map((hero) => {
                        return (
                          <HeroImage key={`hero-${hero}`} hero={{ name: "", image_path: hero, role: "damage" }} size="sm" bare />
                        );
                      })}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-row gap-2">
                      {encounter.matches.map((match) => {
                        return (
                          <PerformanceBadgeWithTooltip
                            key={`performance-${encounter.id}-${match.id}`}
                            match={match}
                          />
                        );
                      })}
                    </div>
                  </TableCell>
                  <TableCell className="text-center">
                    {encounter.closeness ? `${(encounter.closeness * 100).toFixed(0)}%` : "-"}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      {encounter.has_logs ? (
                        <CirclePlus className="text-green-500" />
                      ) : (
                        <CircleMinus className="text-red-500" />
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TooltipProvider>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};

export default UserTournamentEncounters;
