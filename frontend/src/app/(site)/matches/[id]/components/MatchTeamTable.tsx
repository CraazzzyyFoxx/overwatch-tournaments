"use client";

import React from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
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
  const t = useTranslations();
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
          <TableHead className="min-w-[240px] sticky left-0 z-5">
            {t("matches.teamLabel", { name: team.name })}
          </TableHead>
          <TableHead className="text-center">{t("matches.col.division")}</TableHead>
          <TableHead className="text-center">{t("common.heroes")}</TableHead>
          <TableHead className="text-center">{t("matches.col.prs")}</TableHead>
          <TableHead className="text-center">{t("matches.col.fb")}</TableHead>
          <TableHead className="text-center">{t("matches.col.e")}</TableHead>
          <TableHead className="text-center">{t("matches.col.d")}</TableHead>
          <TableHead className="text-center">{t("matches.col.a")}</TableHead>
          <TableHead className="text-center">{t("matches.col.kd")}</TableHead>
          <TableHead className="text-center">{t("matches.col.kad")}</TableHead>
          <TableHead className="text-center">{t("matches.col.sk")}</TableHead>
          <TableHead className="text-center">{t("matches.col.ok")}</TableHead>
          <TableHead className="text-center">{t("matches.col.heroDamage")}</TableHead>
          <TableHead className="text-center">{t("matches.col.dmgFb")}</TableHead>
          <TableHead className="text-center">{t("matches.col.healingDealt")}</TableHead>
          <TableHead className="text-center">{t("matches.col.damageBlocked")}</TableHead>
          <TableHead className="text-center">{t("matches.col.dltDamage")}</TableHead>
          <TableHead className="text-center">{t("matches.col.ultUsedEarned")}</TableHead>
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
