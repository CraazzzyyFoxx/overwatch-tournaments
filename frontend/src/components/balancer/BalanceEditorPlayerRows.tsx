"use client";

import { Fragment, type CSSProperties, type HTMLAttributes, type Ref } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { Card } from "@/components/ui/card";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import { formatSubRoleLabel } from "@/lib/player";
import type { DivisionGrid } from "@/types/workspace.types";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
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
  ontology: RoleOntology | null;
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
  ontology: RoleOntology | null;
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
  ontology: RoleOntology | null;
  selectedPlayerId?: number | null;
  /** The active drag cannot legally drop into this role — block + dim it. */
  dropDisabled?: boolean;
  onSelectPlayer?: (playerId: number | null) => void;
};

export function BalanceEditorPlayerPreviewRow({
  player,
  roleKey,
  divisionGrid,
  ontology,
  selectedPlayerId,
  dragging = false,
  dragHandleProps,
  rowRef,
  style,
  onSelectPlayer,
}: Readonly<BalanceEditorPlayerPreviewRowProps>) {
  return (
    <Card className="w-[24rem] max-w-[calc(100vw-2rem)] overflow-hidden">
      <Table>
        <TableBody>
          <BalanceEditorPlayerTableRow
            player={player}
            roleKey={roleKey}
            divisionGrid={divisionGrid}
            ontology={ontology}
            selectedPlayerId={selectedPlayerId}
            dragging={dragging}
            dragHandleProps={dragHandleProps as HTMLAttributes<HTMLTableRowElement> | undefined}
            rowRef={rowRef as Ref<HTMLTableRowElement> | undefined}
            style={style}
            onSelectPlayer={onSelectPlayer}
          />
        </TableBody>
      </Table>
    </Card>
  );
}

function BalanceEditorPlayerTableRow({
  player,
  roleKey,
  divisionGrid,
  ontology,
  selectedPlayerId,
  dragging = false,
  dropActive = false,
  dragHandleProps,
  rowRef,
  style,
  onSelectPlayer,
}: Readonly<BalanceEditorPlayerTableRowProps>) {
  const t = useTranslations("balancerTool.editor");
  const slotLabel = useSlotLabel(ontology);
  const playerId = parseInternalBalancePlayerId(player);
  const division = resolveDivisionFromRank(divisionGrid, player.assigned_rating);
  const isSelected = playerId !== null && selectedPlayerId === playerId;
  const preferredRoles = player.role_preferences.slice(0, 3);
  const preferredRole = preferredRoles[0];
  const assignedOffRole =
    !player.is_flex && preferredRole !== undefined && preferredRole !== roleKey;
  const subRoleLabel = formatSubRoleLabel(player.sub_role);

  return (
    <TableRow
      ref={rowRef}
      style={style}
      aria-current={isSelected ? "true" : undefined}
      className={cn(
        "cursor-grab focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring active:cursor-grabbing",
        dragging && "opacity-40",
        dropActive && "bg-[color:var(--aqt-overlay-3)]",
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
          <PlayerRoleIcon role={roleKey} ontology={ontology} size={18} />
        </div>
      </TableCell>
      <TableCell className="min-w-45 py-2.5 pr-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <div className="flex min-w-0 items-center gap-2">
            {player.is_captain ? <Crown aria-hidden className="size-3.5 shrink-0 text-[color:var(--aqt-warm)]" /> : null}
            <span className="truncate text-sm font-semibold text-[color:var(--aqt-fg)]" title={player.name}>
              {player.name}
            </span>
          </div>
          {subRoleLabel ? (
            <Eyebrow tone="dim" className="truncate" title={subRoleLabel}>
              {subRoleLabel}
            </Eyebrow>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="w-18 px-2 py-2.5">
        <div className="flex justify-center">
          {division != null ? <RankCrest division={division} grid={divisionGrid} size={26} /> : null}
        </div>
      </TableCell>
      <TableCell className="w-22 px-3 py-2.5">
        <div className="flex items-center justify-center gap-1">
          {preferredRoles.map((preference, index) => {
            const highlightPreferredRole = assignedOffRole && index === 0;

            return (
              <span
                key={`${player.uuid}-${preference}-${index}`}
                className="flex items-center justify-center opacity-85"
                title={
                  highlightPreferredRole ? t("offRole", { role: slotLabel(roleKey) }) : undefined
                }
              >
                <PlayerRoleIcon
                  role={preference}
                  ontology={ontology}
                  size={14}
                  color={highlightPreferredRole ? "var(--aqt-amber)" : undefined}
                />
              </span>
            );
          })}
        </div>
      </TableCell>
    </TableRow>
  );
}

function BalanceEditorInsertSlotRow({
  teamIndex,
  roleKey,
  insertIndex,
  disabled = false,
}: Readonly<{
  teamIndex: number;
  roleKey: BalancerRosterKey;
  insertIndex: number;
  disabled?: boolean;
}>) {
  const { setNodeRef, isOver } = useDroppable({
    id: `player-slot:${teamIndex}:${roleKey}:${insertIndex}`,
    data: {
      kind: "insert-slot",
      teamIndex,
      roleKey,
      insertIndex,
    },
    disabled,
  });

  return (
    <TableRow className="h-0 border-0 hover:bg-transparent">
      <TableCell colSpan={4} className="relative h-0 p-0">
        <div ref={setNodeRef} className="absolute inset-x-0 -top-1.5 z-10 h-3">
          <div
            className={cn(
              "absolute inset-x-3 top-1/2 -translate-y-1/2 rounded-full transition-all",
              isOver
                ? "h-1 bg-[color:var(--aqt-teal)]"
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
    dropDisabled?: boolean;
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
    disabled: props.dropDisabled,
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
  ontology,
  selectedPlayerId,
  dropDisabled = false,
  onSelectPlayer,
}: Readonly<DroppableRoleSectionProps>) {
  const t = useTranslations("balancerTool.editor");
  const slotLabel = useSlotLabel(ontology);
  const { setNodeRef, isOver } = useDroppable({
    id: containerId,
    data: {
      kind: "role-container",
      teamIndex,
      roleKey,
    },
    disabled: dropDisabled,
  });

  return (
    <TableBody
      ref={setNodeRef}
      className={cn(
        "transition-colors",
        isOver && "bg-[color:var(--aqt-overlay-2)]",
        dropDisabled && "cursor-not-allowed opacity-35",
      )}
    >
      {players.map((player, playerIndex) => (
        <Fragment key={player.uuid}>
          <DraggableBalanceEditorPlayerTableRow
            player={player}
            teamIndex={teamIndex}
            playerIndex={playerIndex}
            roleKey={roleKey}
            divisionGrid={divisionGrid}
            ontology={ontology}
            selectedPlayerId={selectedPlayerId}
            dropDisabled={dropDisabled}
            onSelectPlayer={onSelectPlayer}
          />
          {playerIndex < players.length - 1 ? (
            <BalanceEditorInsertSlotRow
              teamIndex={teamIndex}
              roleKey={roleKey}
              insertIndex={playerIndex + 1}
              disabled={dropDisabled}
            />
          ) : null}
        </Fragment>
      ))}

      {players.length === 0 ? (
        <TableRow className="hover:bg-transparent">
          <TableCell
            colSpan={4}
            className={cn(eyebrowClass(), "px-3 py-2.5 text-center")}
          >
            {t("dropHere", { role: slotLabel(roleKey).toLowerCase() })}
          </TableCell>
        </TableRow>
      ) : null}
    </TableBody>
  );
}
