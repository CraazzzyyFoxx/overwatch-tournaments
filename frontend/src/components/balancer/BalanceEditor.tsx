"use client";

import { forwardRef, useCallback, useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useQuery } from "@tanstack/react-query";
import { UserX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import workspaceService from "@/services/workspace.service";
import { memberDisplayName } from "@/lib/workspace-member";
import type { DivisionGrid, WorkspaceMember } from "@/types/workspace.types";
import type {
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalancePlayer,
} from "@/types/balancer-admin.types";

import { BALANCE_ROSTER_KEYS } from "@/app/balancer/components/balancer-page-helpers";

import { BalanceEditorPlayerPreviewRow } from "./BalanceEditorPlayerRows";
import { BalanceEditorTeamCard } from "./BalanceEditorTeamCard";
import {
  canPlayerPlayRole,
  findBalancePlayerLocation,
  moveBalancePlayer,
  resolveBalanceDropTarget,
  type BalanceActiveDrag,
} from "./balance-editor-helpers";
import { useBalancerDragGhosts } from "./useBalancerDragGhosts";

type BalanceEditorProps = {
  value: InternalBalancePayload | null;
  onChange: (payload: InternalBalancePayload) => void;
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  onSelectPlayer?: (playerId: number | null) => void;
  collapsedTeamIds?: number[];
  onToggleTeam?: (teamId: number) => void;
  /** Realtime topic for broadcasting live-drag ghosts to other viewers. */
  realtimeTopic?: string | null;
  /** Current user's auth id — used to ignore our own broadcast echoes. */
  currentUserId?: number | null;
  /** Workspace whose members resolve ghost actor names. */
  workspaceId?: number | null;
};

export const BalanceEditor = forwardRef<HTMLDivElement, BalanceEditorProps>(function BalanceEditor(
  {
    value,
    onChange,
    divisionGrid,
    selectedPlayerId = null,
    onSelectPlayer,
    collapsedTeamIds = [],
    onToggleTeam,
    realtimeTopic = null,
    currentUserId = null,
    workspaceId = null,
  },
  ref,
) {
  const [activePlayer, setActivePlayer] = useState<{
    player: InternalBalancePlayer;
    roleKey: BalancerRosterKey;
  } | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const teamCards = useMemo(() => value?.teams ?? [], [value]);

  const { remoteDrags, broadcastDragStart, broadcastDragOver, broadcastDragEnd } =
    useBalancerDragGhosts({ topic: realtimeTopic, currentUserId });

  const membersQuery = useQuery({
    queryKey: ["workspace", "members", workspaceId],
    queryFn: () => workspaceService.getMembersAll(workspaceId as number),
    enabled: workspaceId !== null,
    staleTime: 5 * 60 * 1000,
  });

  const membersById = useMemo(
    () =>
      new Map<number, WorkspaceMember>(
        (membersQuery.data ?? []).map((member) => [member.auth_user_id, member]),
      ),
    [membersQuery.data],
  );

  const resolveActorName = useCallback(
    (userId: number) => memberDisplayName(membersById.get(userId), userId),
    [membersById],
  );

  const activeDrag = useMemo<BalanceActiveDrag | null>(() => {
    if (!activePlayer) {
      return null;
    }
    return {
      currentRole: activePlayer.roleKey,
      playableRoles: BALANCE_ROSTER_KEYS.filter((role) =>
        canPlayerPlayRole(activePlayer.player, role),
      ),
    };
  }, [activePlayer]);

  if (!value || teamCards.length === 0) {
    return (
      <div className="rounded-2xl border border-white/8 bg-white/2 px-4 py-6 text-sm text-white/45">
        Run the balancer to edit teams.
      </div>
    );
  }

  const handleDragStart = (event: DragStartEvent) => {
    const playerId = String(event.active.id);
    const location = findBalancePlayerLocation(value, playerId);
    if (!location) {
      setActivePlayer(null);
      return;
    }

    const player = value.teams[location.teamIndex].roster[location.roleKey][location.playerIndex];
    setActivePlayer({ player, roleKey: location.roleKey });
    broadcastDragStart({
      playerId,
      playerName: player.name,
      fromTeamIndex: location.teamIndex,
      fromRoleKey: location.roleKey,
    });
  };

  const handleDragOver = (event: DragOverEvent) => {
    const target = resolveBalanceDropTarget(
      event.over ? String(event.over.id) : null,
      event.over?.data.current,
    );
    broadcastDragOver({
      overTeamIndex: target?.teamIndex ?? null,
      overRoleKey: target?.roleKey ?? null,
      overInsertIndex: target?.kind === "insert-slot" ? target.insertIndex : null,
    });
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActivePlayer(null);
    broadcastDragEnd();
    const nextPayload = moveBalancePlayer(
      value,
      String(event.active.id),
      resolveBalanceDropTarget(
        event.over ? String(event.over.id) : null,
        event.over?.data.current,
      ),
    );

    if (nextPayload) {
      onChange(nextPayload);
    }
  };

  const handleDragCancel = () => {
    setActivePlayer(null);
    broadcastDragEnd();
  };

  const benchedPlayers = value.benched_players ?? [];

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div ref={ref} className="space-y-4">
        {benchedPlayers.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-rose-400/20 bg-rose-500/5 px-4 py-3">
            <span className="inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-rose-200/80">
              <UserX className="h-3.5 w-3.5" />
              Unassigned
            </span>
            {benchedPlayers.map((player) => (
              <Badge
                key={player.uuid}
                className="rounded-full border-rose-300/20 bg-rose-500/12 text-rose-100 hover:bg-rose-500/12"
              >
                {player.name}
              </Badge>
            ))}
          </div>
        ) : null}

        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] gap-3">
          {teamCards.map((team, teamIndex) => (
            <BalanceEditorTeamCard
              key={`${team.id}-${teamIndex}`}
              team={team}
              teamIndex={teamIndex}
              divisionGrid={divisionGrid}
              selectedPlayerId={selectedPlayerId}
              collapsed={collapsedTeamIds.includes(team.id)}
              activeDrag={activeDrag}
              remoteDrags={remoteDrags.filter((drag) => drag.overTeamIndex === teamIndex)}
              resolveActorName={resolveActorName}
              onSelectPlayer={onSelectPlayer}
              onToggleTeam={onToggleTeam}
            />
          ))}
        </div>
      </div>

      <DragOverlay>
        {activePlayer ? (
          <BalanceEditorPlayerPreviewRow
            player={activePlayer.player}
            roleKey={activePlayer.roleKey}
            divisionGrid={divisionGrid}
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
});
