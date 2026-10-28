"use client";

import { forwardRef, useCallback, useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useQuery } from "@tanstack/react-query";
import { UserX } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { TONE_CLASS } from "@/components/ui/tone";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import { memberDisplayName } from "@/lib/workspace/member";
import type { DivisionGrid, WorkspaceMember } from "@/types/workspace.types";
import type {
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalancePlayer,
} from "@/types/balancer-admin.types";
import type { RoleOntology } from "@/lib/roster/ontology";

import { BalanceEditorPlayerPreviewRow } from "./BalanceEditorPlayerRows";
import { BalanceEditorTeamCard } from "./BalanceEditorTeamCard";
import {
  balanceBucketKeys,
  canPlayerPlayRole,
  findBalancePlayerLocation,
  moveBalancePlayer,
  resolveBalanceDropTarget,
  type BalanceActiveDrag,
} from "./balance-editor-helpers";
import { useBalancerDragGhosts } from "./useBalancerDragGhosts";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";

type BalanceEditorProps = {
  value: InternalBalancePayload | null;
  onChange: (payload: InternalBalancePayload) => void;
  divisionGrid: DivisionGrid;
  /** The tournament owner's role dictionary: role names, glyphs and the order of the buckets. `null` while it loads. */
  ontology: RoleOntology | null;
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
    ontology,
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
  const t = useTranslations("balancerTool.editor");
  const [activePlayer, setActivePlayer] = useState<{
    player: InternalBalancePlayer;
    roleKey: BalancerRosterKey;
  } | null>(null);
  // Keyboard as well as pointer: the rows already carry dnd-kit's `attributes`
  // (focusable, `role="button"`), so Space lifts a player, the arrows move the
  // drag between role sections and Space drops. Without this sensor the only
  // way to move anybody was a mouse drag.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  );
  const teamCards = useMemo(() => value?.teams ?? [], [value]);
  // The buckets this tournament's roster shape actually fields (a 1-2-2 shape
  // has no open row, an all-open shape only that one), in the owner game's role
  // order: the same capacity read the move rules gate on, so the card never
  // shows a seat nobody can fill.
  const bucketKeys = useMemo(
    () => (value ? balanceBucketKeys(value, ontology) : []),
    [value, ontology],
  );

  const { remoteDrags, broadcastDragStart, broadcastDragOver, broadcastDragEnd } =
    useBalancerDragGhosts({ topic: realtimeTopic, currentUserId });

  const membersQuery = useQuery({
    queryKey: workspaceQueryKeys.members(workspaceId),
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
      playableRoles: bucketKeys.filter((role) => canPlayerPlayRole(activePlayer.player, role)),
    };
  }, [activePlayer, bucketKeys]);

  if (!value || teamCards.length === 0) {
    return (
      <div className="rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-6 text-sm text-[color:var(--aqt-fg-dim)]">
        {t("empty")}
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
          <div className={cn("flex flex-wrap items-center gap-2 rounded-xl border px-4 py-3", TONE_CLASS.danger)}>
            <span className="inline-flex items-center gap-1.5 text-label font-medium uppercase tracking-label">
              <UserX className="h-3.5 w-3.5" aria-hidden />
              {t("unassigned")}
            </span>
            {benchedPlayers.map((player) => (
              <Badge key={player.uuid} shape="pill" tone="danger">
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
              bucketKeys={bucketKeys}
              divisionGrid={divisionGrid}
              selectedPlayerId={selectedPlayerId}
              collapsed={collapsedTeamIds.includes(team.id)}
              activeDrag={activeDrag}
              ontology={ontology}
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
            ontology={ontology}
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
});
