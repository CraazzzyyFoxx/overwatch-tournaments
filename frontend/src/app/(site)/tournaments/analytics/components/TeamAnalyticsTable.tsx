import React, { useMemo } from "react";
import { PerformanceV2, PlayerAnalytics, TeamAnalytics } from "@/types/analytics.types";
import ExplanationPopover from "@/app/(site)/tournaments/analytics/components/ExplanationPopover";
import {
  formatAnalyticsNumber,
  formatConfidencePercent,
  getConfidenceBadgeClass,
  getConfidenceBreakdownLines
} from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { sortTeamPlayers } from "@/utils/player";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { ArrowDown, ArrowUp } from "lucide-react";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import PlayerName from "@/components/PlayerName";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { TypographyH4 } from "@/components/ui/typography";
import { TournamentTeamCardSkeleton } from "@/components/TournamentTeamCard";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from "@/components/ui/tooltip";

import { useQueryClient } from "@tanstack/react-query";
import analyticsService from "@/services/analytics.service";
import { usePermissions } from "@/hooks/usePermissions";
import DivisionIcon from "@/components/DivisionIcon";
import type { DivisionGridVersion } from "@/types/workspace.types";

const ChangeDivisionModal = ({
  player,
  open,
  setOpen
}: {
  player: PlayerAnalytics;
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const [division, setDivision] = React.useState(player.shift ?? 0);
  const queryClient = useQueryClient();

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setOpen(false);

    analyticsService.patchPlayerShift(player.team_id, player.id, division).then(() => {
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["analytics"] }).then();
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Edit shift</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="division" className="text-right">
              Shift
            </Label>
            <Input
              id="division"
              defaultValue={division}
              className="col-span-3"
              onChange={(e) => setDivision(Number(e.target.value))}
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="submit" onClick={onSubmit}>
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

const TournamentPlayerRow = ({
  player,
  tournamentGrid,
  performance,
  tournamentId,
  algorithmId
}: {
  player: PlayerAnalytics;
  tournamentGrid?: DivisionGridVersion | null;
  performance?: PerformanceV2;
  tournamentId: number;
  algorithmId?: number;
}) => {
  const [open, setOpen] = React.useState(false);
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission("analytics.update");

  const pointsCellBase = "text-center tabular-nums";
  const confidenceLines = getConfidenceBreakdownLines(player);

  const isNewPlayer = !!player.is_newcomer;
  const isNewToRole = !isNewPlayer && !!player.is_newcomer_role;

  const isHighPoints = player.points >= 1;
  const isLowPoints = player.points <= -1;
  const isExtremePoints = isHighPoints || isLowPoints;

  const rowTone = isNewPlayer
    ? "bg-muted/40 hover:bg-muted/50"
    : isNewToRole
      ? "bg-muted/20 hover:bg-muted/30"
      : "";

  const rowTitle = isNewPlayer ? "New player" : isNewToRole ? "New to role" : undefined;

  return (
    <>
      <TableRow className={rowTone} title={rowTitle}>
        <TableCell className="font-medium relative pl-4">
          {isNewPlayer ? (
            <span className="pointer-events-none absolute left-1 top-2 bottom-2 w-1.5 rounded-full bg-foreground/25" />
          ) : isNewToRole ? (
            <span className="pointer-events-none absolute left-1 top-2 bottom-2 flex items-stretch gap-[2px]">
              <span className="w-[2px] rounded-full bg-foreground/20" />
              <span className="w-[2px] rounded-full bg-foreground/20" />
            </span>
          ) : null}
          <PlayerRoleIcon role={player.role} size={22} />
        </TableCell>
        <TableCell>
          <PlayerName player={player} includeSpecialization={false} excludeBadge={true} />
        </TableCell>
        <TableCell>
          <div className="flex justify-center">
            <DivisionIcon
              division={player.division}
              tournamentGrid={tournamentGrid}
              width={30}
              height={30}
            />
          </div>
        </TableCell>
        <TableCell className="text-center">{formatAnalyticsNumber(player.move_2)}</TableCell>
        <TableCell className="text-center">{formatAnalyticsNumber(player.move_1)}</TableCell>
        <TableCell className={pointsCellBase}>
          {isExtremePoints ? (
            <span
              className={cn(
                "inline-flex items-center justify-center gap-1 rounded-md border bg-muted/55 px-2 py-0.5 font-semibold",
                isHighPoints
                  ? "border-red-400/60"
                  : isLowPoints
                    ? "border-emerald-400/30"
                    : "border-border/60"
              )}
              title={isHighPoints ? "High points" : "Low points"}
            >
              {isHighPoints ? (
                <ArrowUp className="h-3.5 w-3.5 text-red-400" aria-hidden="true" />
              ) : (
                <ArrowDown className="h-3.5 w-3.5 text-emerald-300/80" aria-hidden="true" />
              )}
              <span>
                {isHighPoints
                  ? `+${formatAnalyticsNumber(player.points)}`
                  : formatAnalyticsNumber(player.points)}
              </span>
            </span>
          ) : (
            formatAnalyticsNumber(player.points)
          )}
        </TableCell>
        <TableCell className={pointsCellBase}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge
                variant="outline"
                className={cn(
                  "justify-center rounded-md px-2 py-0.5 font-semibold",
                  getConfidenceBadgeClass(player.confidence)
                )}
              >
                {formatConfidencePercent(player.confidence)}
              </Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-56 space-y-1 text-left">
              {confidenceLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </TooltipContent>
          </Tooltip>
        </TableCell>
        <TableCell
          onDoubleClick={canEdit ? () => setOpen(true) : undefined}
          className={cn("text-center", canEdit && "cursor-pointer")}
        >
          {formatAnalyticsNumber(player.shift)}
        </TableCell>
        <TableCell className="text-center tabular-nums">
          {performance ? performance.impact_score.toFixed(0) : "—"}
        </TableCell>
        <TableCell className="text-center tabular-nums">
          {performance ? `${Math.round(performance.log_coverage * 100)}%` : "—"}
        </TableCell>
        <TableCell className="text-center">
          {performance ? (
            <ExplanationPopover
              playerId={player.id}
              tournamentId={tournamentId}
              algorithmId={algorithmId}
            />
          ) : null}
        </TableCell>
      </TableRow>
      {canEdit && <ChangeDivisionModal player={player} open={open} setOpen={setOpen} />}
    </>
  );
};

export const TournamentTeamTable = ({
  players,
  tournamentGrid,
  performanceByPlayer,
  tournamentId,
  algorithmId
}: {
  players: PlayerAnalytics[];
  tournamentGrid?: DivisionGridVersion | null;
  performanceByPlayer?: Record<number, PerformanceV2>;
  tournamentId: number;
  algorithmId?: number;
}) => {
  // @ts-ignore
  const sortedPlayers: PlayerAnalytics[] = useMemo(() => {
    return sortTeamPlayers(players);
  }, [players]);
  return (
    <TooltipProvider delayDuration={150}>
      <ScrollArea>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Role</TableHead>
              <TableHead>Battle tag</TableHead>
              <TableHead className="text-center">Div</TableHead>
              <TableHead className="text-center">Move 2</TableHead>
              <TableHead className="text-center">Move 1</TableHead>
              <TableHead className="text-center">Points</TableHead>
              <TableHead className="text-center">Confidence</TableHead>
              <TableHead className="text-center">Manual</TableHead>
              <TableHead className="text-center" title="Performance v2 impact score (0-100 percentile within role)">
                Impact
              </TableHead>
              <TableHead className="text-center" title="Fraction of player&apos;s matches that have full log coverage">
                Logs
              </TableHead>
              <TableHead className="text-center" title="Open SHAP feature contributions">
                Why
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedPlayers.map((player) => (
              <TournamentPlayerRow
                key={player.id}
                player={player}
                tournamentGrid={tournamentGrid}
                performance={performanceByPlayer?.[player.id]}
                tournamentId={tournamentId}
                algorithmId={algorithmId}
              />
            ))}
          </TableBody>
        </Table>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </TooltipProvider>
  );
};

const TeamAnalyticsCard = ({
  team,
  performanceByPlayer,
  tournamentId,
  algorithmId
}: {
  team: TeamAnalytics;
  performanceByPlayer?: Record<number, PerformanceV2>;
  tournamentId: number;
  algorithmId?: number;
}) => {
  const color = useMemo(() => {
    let color = "text-group-a";

    if (team.group?.name == "B") color = "text-group-b";
    if (team.group?.name == "C") color = "text-group-c";
    if (team.group?.name == "D") color = "text-group-d";
    return color;
  }, [team]);

  return (
    <Card id={team.id.toString()} key={team.id}>
      <div className="flex flex-row justify-between p-6">
        <div>
          <TypographyH4>Team {team.name}</TypographyH4>
          <div className="flex gap-2">
            <small className="text-sm font-medium leading-none">Placement: {team.placement}</small>
          </div>
        </div>
        <div className="text-right">
          <TypographyH4 className={color}>Group {team.group?.name}</TypographyH4>
        </div>
      </div>
      <CardContent className="p-0">
        <TournamentTeamTable
          players={team.players}
          tournamentGrid={team.tournament?.division_grid_version}
          performanceByPlayer={performanceByPlayer}
          tournamentId={tournamentId}
          algorithmId={algorithmId}
        />
      </CardContent>
    </Card>
  );
};

const TeamAnalyticsTable = ({
  teams,
  isLoading,
  performanceByPlayer,
  tournamentId,
  algorithmId
}: {
  teams: TeamAnalytics[];
  isLoading: boolean;
  performanceByPlayer?: Record<number, PerformanceV2>;
  tournamentId: number;
  algorithmId?: number;
}) => {
  return (
    <div className="grid grid-cols-2 xs:grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-8">
      {isLoading ? (
        <>
          <TournamentTeamCardSkeleton />
          <TournamentTeamCardSkeleton />
          <TournamentTeamCardSkeleton />
          <TournamentTeamCardSkeleton />
          <TournamentTeamCardSkeleton />
          <TournamentTeamCardSkeleton />
        </>
      ) : (
        teams.map((team) => (
          <TeamAnalyticsCard
            key={team.id}
            team={team}
            performanceByPlayer={performanceByPlayer}
            tournamentId={tournamentId}
            algorithmId={algorithmId}
          />
        ))
      )}
    </div>
  );
};

export default TeamAnalyticsTable;
