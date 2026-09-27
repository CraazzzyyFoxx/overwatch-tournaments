"use client";

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { AlertCircle } from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { OW_REFERENCE_GRID, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { ROLES, ROLE_LABELS } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";

import type { PickupSeat } from "../pickup-lineup";

export type ActiveSeatDrag = { uuid: string; role: string; teamIndex: number; seat: PickupSeat };

/**
 * One seat, wired as both drag source and drop target under the same id
 * (dnd-kit tracks the two registries independently, so this is safe): drag it
 * onto another team's seat of the same role to swap them. Cross-role or
 * same-team drops are still accepted here and left to the server's 422 --
 * this only dims a target that obviously cannot work, it does not duplicate
 * that validation.
 */
export function SeatRow({
  seat,
  teamIndex,
  canDrag,
  activeDrag
}: Readonly<{
  seat: PickupSeat;
  teamIndex: number;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
}>) {
  const dragData: ActiveSeatDrag = { uuid: seat.uuid, role: seat.role, teamIndex, seat };
  const draggable = useDraggable({ id: seat.uuid, data: dragData, disabled: !canDrag });
  const droppable = useDroppable({ id: seat.uuid, data: dragData, disabled: !canDrag });
  const grid = OW_REFERENCE_GRID;
  const division = resolveDivisionFromRank(grid, seat.rating);
  const icon = ROLES.find((item) => item.code === seat.role)?.icon ?? "Support";
  const isValidTarget =
    activeDrag != null &&
    activeDrag.uuid !== seat.uuid &&
    activeDrag.role === seat.role &&
    activeDrag.teamIndex !== teamIndex;
  const isDropReady = droppable.isOver && isValidTarget;

  return (
    <li
      ref={(node) => {
        draggable.setNodeRef(node);
        droppable.setNodeRef(node);
      }}
      {...draggable.attributes}
      {...draggable.listeners}
      className={cn(
        "flex items-center gap-3 rounded-lg border px-3.5 py-3 transition-colors",
        canDrag && "touch-none active:cursor-grabbing",
        draggable.isDragging
          ? "opacity-40"
          : isDropReady
            ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)]"
            : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] hover:bg-[color:var(--aqt-overlay-3)]"
      )}
    >
      <span
        className="flex size-6 shrink-0 items-center justify-center opacity-90"
        title={`${ROLE_LABELS[seat.role]}${seat.subRole ? ` \u00B7 ${seat.subRole}` : ""}`}
      >
        <PlayerRoleIcon role={icon} size={24} label={ROLE_LABELS[seat.role]} />
      </span>
      {division == null ? null : (
        <DivisionIcon
          division={division}
          tournamentGrid={grid}
          width={32}
          height={32}
          className="shrink-0"
        />
      )}
      <span
        className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]"
        title={seat.name}
      >
        {seat.name}
      </span>
      {seat.offRole ? (
        <span
          title="Assigned off their first-preference role"
          className="flex size-4 shrink-0 items-center justify-center text-[color:var(--aqt-amber)]"
        >
          <AlertCircle className="size-3.5" aria-hidden="true" />
          <span className="sr-only">Off-role</span>
        </span>
      ) : null}
      <span className="shrink-0 text-lg font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {seat.rating == null ? "\u2014" : Math.round(seat.rating)}
      </span>
    </li>
  );
}

/** The dragged seat's own row, detached from the list, following the pointer. */
export function SeatDragPreview({ seat }: Readonly<{ seat: PickupSeat }>) {
  const icon = ROLES.find((item) => item.code === seat.role)?.icon ?? "Support";
  return (
    <div
      className={cn(
        PANEL_CLASS,
        "flex cursor-grabbing items-center gap-3 rounded-lg border-[color:var(--aqt-teal)] px-3.5 py-3 shadow-lg"
      )}
    >
      <span className="flex size-6 shrink-0 items-center justify-center opacity-90">
        <PlayerRoleIcon role={icon} size={24} label={ROLE_LABELS[seat.role]} decorative />
      </span>
      <span className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]">
        {seat.name}
      </span>
      <span className="shrink-0 text-lg font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {seat.rating == null ? "\u2014" : Math.round(seat.rating)}
      </span>
    </div>
  );
}
