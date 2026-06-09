"use client";

import {
  BALANCE_ROSTER_KEYS,
  TEAM_BADGE_ACCENTS,
  calculateTeamAverageFromPayload,
  calculateTeamTotalFromPayload,
} from "@/app/balancer/components/balancer-page-helpers";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type {
  InternalBalancePayload,
} from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { DroppableRoleSection } from "./BalanceEditorPlayerRows";

type BalanceEditorTeamCardProps = {
  team: InternalBalancePayload["teams"][number];
  teamIndex: number;
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  collapsed: boolean;
  onSelectPlayer?: (playerId: number | null) => void;
  onToggleTeam?: (teamId: number) => void;
};

export function BalanceEditorTeamCard({
  team,
  teamIndex,
  divisionGrid,
  selectedPlayerId,
  onSelectPlayer,
}: BalanceEditorTeamCardProps) {
  const total = Math.round(calculateTeamTotalFromPayload(team));
  const average = Math.round(calculateTeamAverageFromPayload(team));
  const teamAccent = TEAM_BADGE_ACCENTS[teamIndex % TEAM_BADGE_ACCENTS.length];

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-white/6 px-4 py-3">
        <div className="flex min-w-0 gap-2 items-center">
          <Badge
            className={cn(
              "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]",
              teamAccent,
            )}
          >
            #{team.id}
          </Badge>
          <div className="truncate text-sm font-semibold text-white/88" title={team.name}>
            {team.name}
          </div>
        </div>

        <div className="flex shrink-0 items-start gap-2">
          <div className="text-right">
            <div className="flex flex-wrap justify-end gap-x-3 gap-y-1 text-[11px] font-medium text-white/55">
              <span>
                Total: <span className="tabular-nums text-white/88">{total}</span>
              </span>
              <span>
                Avg: <span className="tabular-nums text-white/88">{average}</span>
              </span>
            </div>
            <div className="mt-1 flex flex-wrap justify-end gap-1.5" />
          </div>
          
        </div>
      </div>
      <Table wrapperClassName="overflow-x-auto overflow-y-visible" className="min-w-90">
        <TableHeader>
          <TableRow className="border-white/6 hover:bg-transparent">
            <TableHead className="h-8 w-13 px-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/35">
              Role
            </TableHead>
            <TableHead className="h-8 min-w-45 px-0 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/35">
              Player
            </TableHead>
            <TableHead className="h-8 w-18 px-2 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-white/35">
              Rank
            </TableHead>
            <TableHead className="h-8 w-22 px-3 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-white/35">
              Prefs
            </TableHead>
          </TableRow>
        </TableHeader>
        {BALANCE_ROSTER_KEYS.map((roleKey) => (
          <DroppableRoleSection
            key={`${team.id}-${roleKey}`}
            teamIndex={teamIndex}
            containerId={`${teamIndex}:${roleKey}`}
            roleKey={roleKey}
            players={team.roster[roleKey]}
            divisionGrid={divisionGrid}
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
          />
        ))}
      </Table>
    </div>
  );
}
