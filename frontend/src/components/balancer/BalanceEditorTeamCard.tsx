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
import { isRoleDropAllowed, type BalanceActiveDrag } from "./balance-editor-helpers";
import type { RemoteDrag } from "./useBalancerDragGhosts";

type BalanceEditorTeamCardProps = {
  team: InternalBalancePayload["teams"][number];
  teamIndex: number;
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  collapsed: boolean;
  activeDrag?: BalanceActiveDrag | null;
  /** Other users' in-progress drags currently targeting this team. */
  remoteDrags?: RemoteDrag[];
  resolveActorName?: (userId: number) => string;
  onSelectPlayer?: (playerId: number | null) => void;
  onToggleTeam?: (teamId: number) => void;
};

export function BalanceEditorTeamCard({
  team,
  teamIndex,
  divisionGrid,
  selectedPlayerId,
  activeDrag = null,
  remoteDrags = [],
  resolveActorName,
  onSelectPlayer,
}: BalanceEditorTeamCardProps) {
  const total = Math.round(calculateTeamTotalFromPayload(team));
  const average = Math.round(calculateTeamAverageFromPayload(team));
  const teamAccent = TEAM_BADGE_ACCENTS[teamIndex % TEAM_BADGE_ACCENTS.length];

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <div className="flex min-w-0 gap-2 items-center">
          <Badge
            className={cn(
              "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]",
              teamAccent,
            )}
          >
            #{team.id}
          </Badge>
          <div className="truncate text-sm font-semibold text-[color:var(--aqt-fg)]" title={team.name}>
            {team.name}
          </div>
        </div>

        <div className="flex shrink-0 items-start gap-2">
          <div className="text-right">
            <div className="flex flex-wrap justify-end gap-x-3 gap-y-1 text-[11px] font-medium text-[color:var(--aqt-fg-muted)]">
              <span>
                Total: <span className="tabular-nums text-[color:var(--aqt-fg)]">{total}</span>
              </span>
              <span>
                Avg: <span className="tabular-nums text-[color:var(--aqt-fg)]">{average}</span>
              </span>
            </div>
            <div className="mt-1 flex flex-wrap justify-end gap-1.5" />
          </div>
          
        </div>
      </div>
      {remoteDrags.length > 0 ? (
        <div className="flex flex-col gap-1 border-b border-cyan-300/15 bg-cyan-500/5 px-4 py-2">
          {remoteDrags.map((drag) => (
            <div
              key={drag.userId}
              className="flex items-center gap-1.5 text-[11px] text-cyan-100/80"
            >
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/70" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-300" />
              </span>
              <span className="font-medium text-cyan-50/90">
                {resolveActorName?.(drag.userId) ?? `User #${drag.userId}`}
              </span>
              <span className="text-cyan-100/55">moving</span>
              <span className="truncate font-medium text-cyan-50/90" title={drag.playerName}>
                {drag.playerName || "player"}
              </span>
              {drag.overRoleKey ? (
                <span className="text-cyan-100/55">&rarr; {drag.overRoleKey}</span>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <Table wrapperClassName="overflow-x-auto overflow-y-visible" className="min-w-90">
        <TableHeader>
          <TableRow className="border-[color:var(--aqt-border)] hover:bg-transparent">
            <TableHead className="h-8 w-13 px-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Role
            </TableHead>
            <TableHead className="h-8 min-w-45 px-0 text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Player
            </TableHead>
            <TableHead className="h-8 w-18 px-2 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
              Rank
            </TableHead>
            <TableHead className="h-8 w-22 px-3 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
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
            dropDisabled={activeDrag != null && !isRoleDropAllowed(activeDrag, roleKey)}
            onSelectPlayer={onSelectPlayer}
          />
        ))}
      </Table>
    </div>
  );
}
