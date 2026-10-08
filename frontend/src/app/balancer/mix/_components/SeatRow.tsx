"use client";

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { AlertCircle } from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { OW_REFERENCE_GRID, getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
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
      <IconTooltip
        label={`${ROLE_LABELS[seat.role]}${seat.subRole ? ` \u00B7 ${seat.subRole}` : ""}`}
        className="size-6 shrink-0 items-center justify-center opacity-90"
      >
        <PlayerRoleIcon role={icon} size={24} decorative />
      </IconTooltip>
      {division == null ? null : (
        <IconTooltip
          label={getDivisionLabel(grid, division) ?? String(division)}
          className="shrink-0"
        >
          <DivisionIcon division={division} tournamentGrid={grid} width={32} height={32} />
        </IconTooltip>
      )}
      <span
        className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]"
        title={seat.name}
      >
        {seat.name}
      </span>
      {seat.offRole ? (
        <IconTooltip
          label="Off-role"
          hint="Assigned off their first-preference role"
          className="size-4 shrink-0 items-center justify-center text-[color:var(--aqt-amber)]"
        >
          <AlertCircle className="size-3.5" aria-hidden="true" />
        </IconTooltip>
      ) : null}
      <SeatRating seat={seat} />
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
      <SeatRating seat={seat} />
    </div>
  );
}

/**
 * The number the solver balanced on. In ranker mode that is the effective
 * rating, so the host's own open rating rides along in small type -- but only
 * when the correction actually moved it, otherwise it is noise.
 */
function SeatRating({ seat }: Readonly<{ seat: PickupSeat }>) {
  const effective = seat.rating == null ? null : Math.round(seat.rating);
  const open = seat.openRating == null ? null : Math.round(seat.openRating);
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      {open != null && effective != null && open !== effective ? (
        <span
          className="text-xs tabular-nums text-[color:var(--aqt-fg-dim)]"
          title={`Open rating ${open}; the ranker balanced on ${effective}`}
        >
          open {open}
        </span>
      ) : null}
      <span className="text-lg font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {effective == null ? "\u2014" : effective}
      </span>
    </span>
  );
}
