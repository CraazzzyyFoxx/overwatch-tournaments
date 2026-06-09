"use client";

import { Fragment, type CSSProperties, type HTMLAttributes, type Ref } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { Crown } from "lucide-react";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import type { DivisionGrid } from "@/types/workspace.types";
import type {
  BalancerRosterKey,
  InternalBalancePlayer,
} from "@/types/balancer-admin.types";

import {
  parseInternalBalancePlayerId,
} from "./balance-editor-helpers";

type BalanceEditorPlayerPreviewRowProps = {
  player: InternalBalancePlayer;
  roleKey: BalancerRosterKey;
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  dragging?: boolean;
  dragHandleProps?: HTMLAttributes<HTMLDivElement>;
  rowRef?: Ref<HTMLDivElement>;
  style?: CSSProperties;
  onSelectPlayer?: (playerId: number | null) => void;
};

type BalanceEditorPlayerTableRowProps = {
  player: InternalBalancePlayer;
  roleKey: BalancerRosterKey;
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  dragging?: boolean;
  dropActive?: boolean;
  dragHandleProps?: HTMLAttributes<HTMLTableRowElement>;
  rowRef?: Ref<HTMLTableRowElement>;
  style?: CSSProperties;
  onSelectPlayer?: (playerId: number | null) => void;
};

type DroppableRoleSectionProps = {
  teamIndex: number;
  containerId: string;
  roleKey: BalancerRosterKey;
  players: InternalBalancePlayer[];
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  onSelectPlayer?: (playerId: number | null) => void;
};

export function BalanceEditorPlayerPreviewRow({
  player,
  roleKey,
  divisionGrid,
  selectedPlayerId,
  dragging = false,
  dragHandleProps,
  rowRef,
  style,
  onSelectPlayer,
}: BalanceEditorPlayerPreviewRowProps) {
  return (
    <div className="w-[24rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-border bg-card shadow-2xl shadow-black/40">
      <table className="w-full caption-bottom text-sm">
        <tbody>
          <BalanceEditorPlayerTableRow
            player={player}
            roleKey={roleKey}
            divisionGrid={divisionGrid}
            selectedPlayerId={selectedPlayerId}
            dragging={dragging}
            dragHandleProps={dragHandleProps as HTMLAttributes<HTMLTableRowElement> | undefined}
            rowRef={rowRef as Ref<HTMLTableRowElement> | undefined}
            style={style}
            onSelectPlayer={onSelectPlayer}
          />
        </tbody>
      </table>
    </div>
  );
}

function BalanceEditorPlayerTableRow({
  player,
  roleKey,
  divisionGrid,
  selectedPlayerId,
  dragging = false,
  dropActive = false,
  dragHandleProps,
  rowRef,
  style,
  onSelectPlayer,
}: BalanceEditorPlayerTableRowProps) {
  const playerId = parseInternalBalancePlayerId(player);
  const division = resolveDivisionFromRank(divisionGrid, player.assigned_rating);
  const isSelected = playerId !== null && selectedPlayerId === playerId;
  const preferredRoles = player.role_preferences.slice(0, 3);
  const preferredRole = preferredRoles[0];
  const assignedOffRole =
    !player.is_flex && preferredRole !== undefined && preferredRole !== roleKey;

  return (
    <TableRow
      ref={rowRef}
      style={style}
      className={cn(
        "cursor-grab border-white/5 active:cursor-grabbing",
        dragging && "opacity-40",
        dropActive && "bg-white/[0.05]",
        isSelected
          ? "bg-violet-500/8 shadow-[inset_0_0_0_1px_rgba(139,92,246,0.24)] hover:bg-violet-500/[0.1]"
          : "hover:bg-white/[0.03]",
      )}
      onClick={() => {
        if (playerId !== null) {
          onSelectPlayer?.(playerId);
        }
      }}
      {...dragHandleProps}
    >
      <TableCell className="w-13 px-4 py-2.5">
        <div className="flex justify-center">
          <PlayerRoleIcon role={roleKey} size={18} />
        </div>
      </TableCell>
      <TableCell className="min-w-45 py-2.5 pr-2">
        <div className="flex min-w-0 items-center gap-2">
          {player.is_captain ? <Crown className="h-3.5 w-3.5 shrink-0 text-amber-300" /> : null}
          <span className="truncate text-sm font-semibold text-white/88" title={player.name}>
            {player.name}
          </span>
        </div>
      </TableCell>
      <TableCell className="w-18 px-2 py-2.5">
        <div className="flex justify-center">
          {division != null ? (
            <span title={`Division ${division}`}>
              <PlayerDivisionIcon division={division} width={26} height={26} />
            </span>
          ) : (
            <span className="text-xs text-white/25">-</span>
          )}
        </div>
      </TableCell>
      <TableCell className="w-22 px-3 py-2.5">
        <div className="flex items-center justify-center gap-1">
          {preferredRoles.length > 0 ? (
            preferredRoles.map((preference, index) => {
              const highlightPreferredRole = assignedOffRole && index === 0;

              return (
                <span
                  key={`${player.uuid}-${preference}-${index}`}
                  className="flex items-center justify-center opacity-85"
                  title={
                    highlightPreferredRole ? `Off-role: assigned ${roleKey}` : undefined
                  }
                >
                  <PlayerRoleIcon
                    role={preference}
                    size={14}
                    color={highlightPreferredRole ? "#fbbf24" : undefined}
                  />
                </span>
              );
            })
          ) : (
            <span className="text-xs text-white/25">-</span>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

function BalanceEditorInsertSlotRow({
  teamIndex,
  roleKey,
  insertIndex,
}: {
  teamIndex: number;
  roleKey: BalancerRosterKey;
  insertIndex: number;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `player-slot:${teamIndex}:${roleKey}:${insertIndex}`,
    data: {
      kind: "insert-slot",
      teamIndex,
      roleKey,
      insertIndex,
    },
  });

  return (
    <TableRow className="h-0 border-0 hover:bg-transparent">
      <TableCell colSpan={4} className="relative h-0 p-0">
        <div ref={setNodeRef} className="absolute inset-x-0 -top-1.5 z-10 h-3">
          <div
            className={cn(
              "absolute inset-x-3 top-1/2 -translate-y-1/2 rounded-full transition-all",
              isOver
                ? "h-1 bg-cyan-300/80 shadow-[0_0_0_1px_rgba(103,232,249,0.22)]"
                : "h-px bg-transparent",
            )}
          />
        </div>
      </TableCell>
    </TableRow>
  );
}

function DraggableBalanceEditorPlayerTableRow(
  props: BalanceEditorPlayerTableRowProps & {
    player: InternalBalancePlayer;
    teamIndex: number;
    playerIndex: number;
  },
) {
  const { attributes, listeners, setNodeRef: setDraggableNodeRef, transform, isDragging } = useDraggable({
    id: props.player.uuid,
  });
  const { setNodeRef: setDroppableNodeRef, isOver } = useDroppable({
    id: `player-row:${props.teamIndex}:${props.roleKey}:${props.player.uuid}`,
    data: {
      kind: "player-row",
      teamIndex: props.teamIndex,
      roleKey: props.roleKey,
      playerIndex: props.playerIndex,
      playerId: props.player.uuid,
    },
  });
  const style = transform ? { transform: CSS.Translate.toString(transform) } : undefined;
  const setNodeRef = (node: HTMLTableRowElement | null) => {
    setDraggableNodeRef(node);
    setDroppableNodeRef(node);
  };

  return (
    <BalanceEditorPlayerTableRow
      {...props}
      dragging={isDragging}
      dropActive={isOver}
      rowRef={setNodeRef}
      style={style}
      dragHandleProps={{ ...listeners, ...attributes }}
    />
  );
}

export function DroppableRoleSection({
  teamIndex,
  containerId,
  roleKey,
  players,
  divisionGrid,
  selectedPlayerId,
  onSelectPlayer,
}: DroppableRoleSectionProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: containerId,
    data: {
      kind: "role-container",
      teamIndex,
      roleKey,
    },
  });

  return (
    <TableBody ref={setNodeRef} className={cn("transition-colors", isOver && "bg-white/3")}>
      {players.map((player, playerIndex) => (
        <Fragment key={player.uuid}>
          <DraggableBalanceEditorPlayerTableRow
            player={player}
            teamIndex={teamIndex}
            playerIndex={playerIndex}
            roleKey={roleKey}
            divisionGrid={divisionGrid}
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
          />
          {playerIndex < players.length - 1 ? (
            <BalanceEditorInsertSlotRow
              teamIndex={teamIndex}
              roleKey={roleKey}
              insertIndex={playerIndex + 1}
            />
          ) : null}
        </Fragment>
      ))}

      {players.length === 0 ? (
        <TableRow className="border-white/5 hover:bg-transparent">
          <TableCell
            colSpan={4}
            className="px-3 py-2.5 text-center text-[11px] uppercase tracking-[0.14em] text-white/24"
          >
            Drop {roleKey.toLowerCase()} here
          </TableCell>
        </TableRow>
      ) : null}
    </TableBody>
  );
}
