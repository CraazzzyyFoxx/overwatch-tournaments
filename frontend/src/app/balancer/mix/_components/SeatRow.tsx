"use client";

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useTranslations } from "next-intl";
import { AlertCircle, Crown } from "lucide-react";

import { lineupSeatKey, playerTransitionName } from "@/app/balancer/mix/_room/room-model";
import { AWAY_CHIP_CLASS } from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { cn } from "@/lib/utils";

import type { MixOwner, PickupSeat } from "../pickup-lineup";

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
  owner,
  teamIndex,
  canDrag,
  activeDrag,
  away = false,
  onMakeCaptain
}: Readonly<{
  seat: PickupSeat;
  owner: MixOwner;
  teamIndex: number;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
  /** Stepped away but still seated in this lineup (spec §7.4). */
  away?: boolean;
  /** Omitted -- no "Make captain" (a viewer, a live lineup, a screenshot, or this seat already wears the crown). */
  onMakeCaptain?: () => void;
}>) {
  const tRoom = useTranslations("mixes.room");
  const tTeams = useTranslations("mixes.teams");
  const dragData: ActiveSeatDrag = { uuid: seat.uuid, role: seat.role, teamIndex, seat };
  const draggable = useDraggable({ id: seat.uuid, data: dragData, disabled: !canDrag });
  const droppable = useDroppable({ id: seat.uuid, data: dragData, disabled: !canDrag });
  const { grid } = owner;
  const slotLabel = useSlotLabel(owner.ontology);
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
      // The same name the player wears in the room, so entering it flies them from this row to their side.
      style={{ viewTransitionName: playerTransitionName(lineupSeatKey(seat.uuid)) }}
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
      {owner.showsRoles ? (
        <IconTooltip
          label={`${slotLabel(seat.role)}${seat.subRole ? ` \u00B7 ${seat.subRole}` : ""}`}
          className="size-6 shrink-0 items-center justify-center opacity-90"
        >
          <PlayerRoleIcon role={seat.role} ontology={owner.ontology} size={24} decorative />
        </IconTooltip>
      ) : null}
      <RankCrest rank={seat.rating} grid={grid} size={32} />
      <span
        className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]"
        title={seat.name}
      >
        {seat.name}
      </span>
      {seat.isCaptain ? (
        <IconTooltip label={tRoom("captain")} className="flex shrink-0 items-center">
          <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : onMakeCaptain ? (
        <IconTooltip control label={tRoom("makeCaptain")}>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={tRoom("makeCaptain")}
            onClick={onMakeCaptain}
            className="shrink-0 text-[color:var(--aqt-fg-faint)] hover:text-[color:var(--aqt-amber)]"
          >
            <Crown aria-hidden />
          </Button>
        </IconTooltip>
      ) : null}
      {away ? <span className={AWAY_CHIP_CLASS}>{tRoom("away")}</span> : null}
      {seat.offRole ? (
        <IconTooltip
          label={tTeams("offRole")}
          hint={tTeams("offRoleHint")}
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
export function SeatDragPreview({ seat, owner }: Readonly<{ seat: PickupSeat; owner: MixOwner }>) {
  const slotLabel = useSlotLabel(owner.ontology);
  const tRoom = useTranslations("mixes.room");
  return (
    <Card
      className="flex cursor-grabbing items-center gap-3 rounded-lg border-[color:var(--aqt-teal)] px-3.5 py-3"
    >
      {owner.showsRoles ? (
        <span className="flex size-6 shrink-0 items-center justify-center opacity-90">
          <PlayerRoleIcon role={seat.role} ontology={owner.ontology} size={24} label={slotLabel(seat.role)} decorative />
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]">
        {seat.name}
      </span>
      {/* No tooltip: the pointer sits on this ghost for the whole drag. */}
      {seat.isCaptain ? (
        <span role="img" aria-label={tRoom("captain")} className="flex shrink-0 items-center">
          <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
        </span>
      ) : null}
      <SeatRating seat={seat} />
    </Card>
  );
}

/**
 * The number the solver balanced on. In ranker mode that is the effective
 * rating, so the host's own open rating rides along in small type -- but only
 * when the correction actually moved it, otherwise it is noise.
 */
function SeatRating({ seat }: Readonly<{ seat: PickupSeat }>) {
  const t = useTranslations("mixes.teams");
  const effective = seat.rating == null ? null : Math.round(seat.rating);
  const open = seat.openRating == null ? null : Math.round(seat.openRating);
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      {open != null && effective != null && open !== effective ? (
        <span
          className="text-xs tabular-nums text-[color:var(--aqt-fg-dim)]"
          title={t("openRatingHint", { open: String(open), effective: String(effective) })}
        >
          {t("openRating", { rating: String(open) })}
        </span>
      ) : null}
      <span className="text-lg font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {effective == null ? "\u2014" : effective}
      </span>
    </span>
  );
}
