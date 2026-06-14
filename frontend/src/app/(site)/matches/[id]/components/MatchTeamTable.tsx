import React from "react";
import Image from "next/image";
import { PlayerWithStats, TeamWithStats } from "@/types/team.types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { sortTeamPlayers } from "@/utils/player";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PerformanceBadge } from "@/components/PerformanceBagde";
import { ScrollBar, ScrollArea } from "@/components/ui/scroll-area";
import DivisionIcon from "@/components/DivisionIcon";
import type { DivisionGridVersion } from "@/types/workspace.types";

interface MatchTeamTableProps {
  team: TeamWithStats;
  isHome: boolean;
  maxHeroes: number;
  matchRound: number;
  tournamentGrid?: DivisionGridVersion | null;
}

const MatchTeamTable = ({ team, isHome, maxHeroes, matchRound, tournamentGrid }: MatchTeamTableProps) => {
  // @ts-ignore
  const sortedPlayers: PlayerWithStats[] = sortTeamPlayers(team.players);
  const backgroundColor = isHome ? "[#104e48]" : "[#4c2332]";

  const validatedPlayers = [];

  for (let playerI = 0; playerI < sortedPlayers.length; playerI++) {
    const player = sortedPlayers[playerI];
    if (player.heroes[matchRound]?.length > 0) {
      validatedPlayers.push(player);
    }
  }

  return (
    <Table className="overflow-x-auto">
      <TableHeader>
        <TableRow className={`bg-${backgroundColor} hover:bg-${backgroundColor}`}>
          <TableHead className="min-w-[240px] sticky left-0 z-5">Team {team.name}</TableHead>
          <TableHead className="text-center">Division</TableHead>
          <TableHead className="text-center">Heroes</TableHead>
          <TableHead className="text-center">PRS</TableHead>
          <TableHead className="text-center">FB</TableHead>
          <TableHead className="text-center">E</TableHead>
          <TableHead className="text-center">D</TableHead>
          <TableHead className="text-center">A</TableHead>
          <TableHead className="text-center">K/D</TableHead>
          <TableHead className="text-center">KA/D</TableHead>
          <TableHead className="text-center">SK</TableHead>
          <TableHead className="text-center">OK</TableHead>
          <TableHead className="text-center">Hero Damage</TableHead>
          <TableHead className="text-center">Dmg/FB</TableHead>
          <TableHead className="text-center">Healing Dealt</TableHead>
          <TableHead className="text-center">Damage Blocked</TableHead>
          <TableHead className="text-center">Dlt Damage</TableHead>
          <TableHead className="text-center">Ult Used/Earned</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {validatedPlayers.map((player) => {
          const color = isHome ? "from-[#104e48]" : "from-[#4c2332]";
          const missingHeroes = maxHeroes - player.heroes[matchRound].length;

          if (missingHeroes > 0) {
            for (let i = 0; i < missingHeroes; i++) {
              // @ts-ignore
              player.heroes[matchRound].push({ id: i, name: " ", image_path: "" });
            }
          }

          return (
            <TableRow key={player.id} className="hover:bg-background">
              <TableCell
                className={`flex flex-row items-center gap-2 bg-gradient-to-r ${color} via-background to-background min-w-[240px] sticky left-0 z-10`}
              >
                <PlayerRoleIcon role={player.role} />
                <PlayerName player={player} includeSpecialization={true} />
              </TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <DivisionIcon division={player.division} width={32} height={32} tournamentGrid={tournamentGrid} />
                </div>
              </TableCell>
              <TableCell>
                <div className="flex flex-row gap-1.5">
                  {player.heroes[matchRound].map((hero) => {
                    return (
                      // Возможно надо будет вернуть AvatarImage
                      <Avatar key={`hero-${hero.id}`}>
                        {hero.image_path ? (
                          <Image
                            src={hero.image_path}
                            alt={hero.name}
                            layout="fill"
                            objectFit="cover"
                          />
                        ) : (
                          <AvatarFallback delayMs={200} className="bg-background">
                            {hero.name.slice(0, 3)}
                          </AvatarFallback>
                        )}
                      </Avatar>
                    );
                  })}
                </div>
              </TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <PerformanceBadge performance={player.stats[matchRound].performance} />
                </div>
              </TableCell>
              <TableCell className="text-center">{player.stats[matchRound].final_blows}</TableCell>
              <TableCell className="text-center">{player.stats[matchRound].eliminations}</TableCell>
              <TableCell className="text-center">{player.stats[matchRound].deaths}</TableCell>
              <TableCell className="text-center">{player.stats[matchRound].assists}</TableCell>
              <TableCell className="text-center">{player.stats[matchRound].kd}</TableCell>
              <TableCell className="text-center">{player.stats[matchRound].kda}</TableCell>
              <TableCell className="text-center">{player.stats[matchRound].solo_kills}</TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].objective_kills}
              </TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].hero_damage_dealt.toFixed(0)}
              </TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].damage_fb.toFixed(0)}
              </TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].healing_dealt.toFixed(0)}
              </TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].damage_blocked.toFixed(0)}
              </TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].damage_delta.toFixed(0)}
              </TableCell>
              <TableCell className="text-center">
                {player.stats[matchRound].ultimates_used}/
                {player.stats[matchRound].ultimates_earned}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};

export default MatchTeamTable;
