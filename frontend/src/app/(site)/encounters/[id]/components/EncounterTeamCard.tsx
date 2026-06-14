import React from "react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Team } from "@/types/team.types";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { CircleMinus, CirclePlus, Recycle } from "lucide-react";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import PlayerName from "@/components/PlayerName";
import DivisionIcon from "@/components/DivisionIcon";
import { sortTeamPlayers } from "@/utils/player";
import type { DivisionGridVersion } from "@/types/workspace.types";

const EncounterTeamCard = ({
  team,
  isHome,
  tournamentGrid,
}: {
  team: Team;
  isHome: boolean;
  tournamentGrid?: DivisionGridVersion | null;
}) => {
  const titleColor = isHome ? "text-[#16e5b4]" : "text-[#ff4655]";
  const sortedPlayers = sortTeamPlayers(team.players);
  const backgroundColor = isHome
    ? "bg-[#104e48] hover:bg-[#104e48]"
    : "bg-[#4c2332] hover:bg-[#4c2332]";

  return (
    <Card>
      <CardHeader className="px-0 pl-4">
        <CardTitle className={`scroll-m-20 text-2xl font-semibold tracking-tight ${titleColor}`}>
          {team.name}
        </CardTitle>
        <p className={`leading-7 ${titleColor}`}>
          Placement: {team.placement ? team.placement : "Unknown"}
        </p>
      </CardHeader>
      <ScrollArea>
        <Table>
          <TableHeader>
            <TableRow className={backgroundColor}>
              <TableHead className="text-white">Name</TableHead>
              <TableHead className="text-center text-white">Division</TableHead>
              <TableHead className="text-center text-white">New</TableHead>
              <TableHead className="text-center text-white">New Role</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedPlayers.map((player, index) => {
              const color = isHome ? "from-[#104e48]" : "from-[#4c2332]";

              return (
                <TableRow key={player.id} className="hover:bg-background">
                  <TableCell
                    className={`flex flex-row items-center gap-2 bg-gradient-to-r ${color} via-background to-background ${index == sortedPlayers.length - 1 ? "rounded-b-lg" : ""}`}
                  >
                    <div className="flex flex-row items-center gap-2">
                      {player.is_substitution ? (
                        <div>
                          <Recycle />
                        </div>
                      ) : (
                        <PlayerRoleIcon role={player.role} />
                      )}
                      <PlayerName player={player} includeSpecialization={true} />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      <DivisionIcon
                        division={player.division}
                        width={32}
                        height={32}
                        tournamentGrid={tournamentGrid}
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      {player.is_newcomer ? (
                        <CirclePlus className="text-red-500" />
                      ) : (
                        <CircleMinus className="text-green-500" />
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      {player.is_newcomer_role ? (
                        <CirclePlus className="text-red-500" />
                      ) : (
                        <CircleMinus className="text-green-500" />
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </Card>
  );
};

export default EncounterTeamCard;
