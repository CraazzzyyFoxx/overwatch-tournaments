"use client";

import { useState } from "react";

import { DndContext, DragOverlay, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";

import { teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { useDragSensors } from "@/hooks/useDragSensors";
import { cn } from "@/lib/utils";

import type { PickupTeam, PickupVariant } from "../pickup-lineup";
import { SeatDragPreview, SeatRow, type ActiveSeatDrag } from "./SeatRow";
import { VariantMetrics } from "./VariantMetrics";

export function VariantView({
  variant,
  canWrite,
  capturing,
  onRenameTeam,
  onSwapSeats
}: Readonly<{
  variant: PickupVariant;
  canWrite: boolean;
  /** A screenshot is being taken: the rename pencils drop out so the card exports as a plain matchup. */
  capturing: boolean;
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  /** Omitted -- seats render without drag handles, matching a `canWrite=false` viewer. */
  onSwapSeats?: (firstUuid: string, secondUuid: string) => void | Promise<unknown>;
}>) {
  const twoTeams = variant.teams.length === 2;
  const canDrag = canWrite && onSwapSeats != null;
  const [activeDrag, setActiveDrag] = useState<ActiveSeatDrag | null>(null);
  // A plain click on a seat must stay a click, so the drag waits for the house
  // 6px of intent -- see `useDragSensors`.
  const sensors = useDragSensors();

  const handleDragStart = (event: DragStartEvent) => {
    const data = event.active.data.current as ActiveSeatDrag | undefined;
    if (data) setActiveDrag(data);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDrag(null);
    const firstUuid = String(event.active.id);
    const secondUuid = event.over ? String(event.over.id) : null;
    if (!secondUuid || secondUuid === firstUuid || !onSwapSeats) return;
    void onSwapSeats(firstUuid, secondUuid);
  };

  return (
    // One card with a divider column, not two cards: the matchup is a single
    // object, and a gap between two boxes read as two unrelated rosters. The
    // verdict pills live inside it too, centred over the seam between the
    // teams and above their rosters -- inside the same border, not a strip
    // floating above the card on its own. Who the option left out is not
    // repeated here: the lineup column already marks them benched.
    <div className={cn(PANEL_CLASS, "overflow-hidden rounded-2xl")}>
      <div className="flex flex-wrap items-center justify-center gap-1.5 border-b border-[color:var(--aqt-border)] px-4 py-2.5">
        <VariantMetrics variant={variant} />
      </div>
      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setActiveDrag(null)}
      >
        <div className={cn("flex items-stretch", twoTeams ? "flex-col lg:flex-row" : "flex-col")}>
          {variant.teams.map((team, teamIndex) => (
            <TeamColumnAndDivider
              key={team.id}
              team={team}
              teamIndex={teamIndex}
              showDivider={twoTeams && teamIndex === 0}
              canWrite={canWrite}
              // The pencil is a 28px square on the 28px title line, so
              // withholding it during capture leaves no hole in the image.
              onRenameTeam={capturing ? undefined : onRenameTeam}
              canDrag={canDrag}
              activeDrag={activeDrag}
            />
          ))}
        </div>
        {/* Follows the pointer instead of the seat teleporting under it --
              without this dnd-kit still swaps correctly, it just looks broken
              mid-drag (the dragged row snaps back until drop). */}
        <DragOverlay>{activeDrag ? <SeatDragPreview seat={activeDrag.seat} /> : null}</DragOverlay>
      </DndContext>
    </div>
  );
}

function TeamColumnAndDivider({
  team,
  teamIndex,
  showDivider,
  canWrite,
  onRenameTeam,
  canDrag,
  activeDrag
}: Readonly<{
  team: PickupTeam;
  teamIndex: number;
  showDivider: boolean;
  canWrite: boolean;
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
}>) {
  return (
    <>
      <TeamColumn
        team={team}
        teamIndex={teamIndex}
        canWrite={canWrite}
        onRenameTeam={onRenameTeam}
        canDrag={canDrag}
        activeDrag={activeDrag}
      />
      {showDivider ? (
        <div
          aria-hidden="true"
          className="flex shrink-0 items-center justify-center border-y border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] py-2 lg:w-16 lg:border-x lg:border-y-0 lg:py-0"
        >
          <span className="font-display text-ui font-bold tracking-label text-[color:var(--aqt-fg-faint)]">
            VS
          </span>
        </div>
      ) : null}
    </>
  );
}

function TeamColumn({
  team,
  teamIndex,
  canWrite,
  onRenameTeam,
  canDrag,
  activeDrag
}: Readonly<{
  team: PickupTeam;
  teamIndex: number;
  canWrite: boolean;
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
}>) {
  const accent = teamAccent(teamIndex);

  return (
    <section className="min-w-0 flex-1 px-4 pb-4 pt-4">
      <header className="flex items-baseline gap-2.5 border-b border-[color:var(--aqt-border)] pb-3">
        <span aria-hidden="true" className={cn("h-4 w-[3px] shrink-0 rounded-sm", accent.bar)} />
        <InlineEditText
          value={team.name}
          label="team name"
          canEdit={canWrite && onRenameTeam != null}
          onSave={(next) => onRenameTeam?.(teamIndex, next)}
          textClassName="truncate font-display text-xl font-bold tracking-[0.01em] text-[color:var(--aqt-fg)]"
        />
        <span
          className={cn(
            "ml-auto shrink-0 text-label uppercase tracking-label",
            "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          avg
        </span>
        <span className="shrink-0 text-xl font-bold tabular-nums text-[color:var(--aqt-fg)]">
          {team.averageRank == null ? "\u2014" : Math.round(team.averageRank)}
        </span>
      </header>
      <ul className="mt-2.5 space-y-1">
        {team.seats.map((seat) => (
          <SeatRow
            key={`${seat.uuid}:${seat.role}`}
            seat={seat}
            teamIndex={teamIndex}
            canDrag={canDrag}
            activeDrag={activeDrag}
          />
        ))}
      </ul>
    </section>
  );
}
