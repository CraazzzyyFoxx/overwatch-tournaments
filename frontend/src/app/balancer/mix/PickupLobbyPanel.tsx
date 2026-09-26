"use client";

import { useState } from "react";

import {
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent
} from "@dnd-kit/core";
import { AlertTriangle, Trash2, Wand2 } from "lucide-react";

import { ICON_BUTTON_CLASS, PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  EYEBROW_CLASS
} from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useDragSensors } from "@/hooks/useDragSensors";
import { ROLE_LABELS, ROLES } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  MixParticipation,
  RotationRecommendation
} from "@/services/custom-game.service";

import { LineupColumn } from "./_components/LineupColumn";
import { LineupDragPreview } from "./_components/LineupRow";
import {
  computeRotationHintPatches,
  sortLineup,
  summarizeLineup,
  summarizeRoleSupply
} from "./pickup-lineup";

type PickupLobbyPanelProps = {
  canWrite: boolean;
  hasMix: boolean;
  rows: CustomGamePlayer[];
  /**
   * Rotation-fairness verdict per roster member, from `usePickupMix`'s
   * `rotationQuery`. Optional, and defaulted to empty, so an older caller (or
   * a not-yet-loaded fetch) just renders the lineup without hints.
   */
  rotation?: RotationRecommendation[];
  savingPlayerId: number | null;
  clearing: boolean;
  onPatchPlayer: (workspaceMemberId: number, patch: CustomGamePlayerPatch) => void;
  onClear: () => void;
  onRemovePlayer: (workspaceMemberId: number) => void;
  onOpenPlayer: (workspaceMemberId: number) => void;
  onOpenPool: () => void;
  /** Fires every actionable rotation hint at once (see `computeRotationHintPatches`). */
  onApplyRotationHints: () => void;
  applyingHints: boolean;
};

/** One drag-and-drop column per participation state, in the order a host reads commitment. */
const COLUMNS: readonly {
  bucket: MixParticipation;
  title: string;
  hint: string;
  emptyHint: string;
}[] = [
  {
    bucket: "must_play",
    title: "Must play",
    hint: "Guaranteed a seat",
    emptyHint: "Drag a player here to guarantee their seat",
  },
  {
    bucket: "pool",
    title: "In the pool",
    hint: "In the balance",
    emptyHint: "Drag a player here to put them in the balance",
  },
  {
    bucket: "benched",
    title: "Benched",
    hint: "Sitting out, settings kept",
    emptyHint: "Drag a player here to bench them",
  },
];

/**
 * The lineup: who is in this mix, who the next balance will use, and whether the
 * roles they picked can actually fill two teams.
 *
 * Membership belongs to the player pool — adding or removing someone there
 * writes here. This column owns *participation and commitment*, split into
 * three columns a host drags a player between: guaranteed a seat
 * (`must_play`), optional in the balance (`pool`), or sitting out
 * (`benched` -- sitting out, settings kept). A drop writes the one
 * `participation` field without touching role order or ranks, so "he's late,
 * start without him" costs one drag and no rework.
 *
 * The role-supply strip sits above the columns on purpose. A host reads "short
 * 1 tank" before pressing Balance, instead of reading a seated lineup
 * afterwards and guessing which player the solver had to move off their first
 * choice.
 */
export function PickupLobbyPanel({
  canWrite,
  hasMix,
  rows,
  rotation = [],
  savingPlayerId,
  clearing,
  onPatchPlayer,
  onClear,
  onRemovePlayer,
  onOpenPlayer,
  onOpenPool,
  onApplyRotationHints,
  applyingHints,
}: Readonly<PickupLobbyPanelProps>) {
  const lineup = sortLineup(rows);
  const summary = summarizeLineup(rows);
  const supply = summarizeRoleSupply(rows);
  const rotationByMember = new Map(rotation.map((r) => [r.workspace_member_id, r]));
  const pendingHintCount = computeRotationHintPatches(rows, rotation).length;
  const columns = COLUMNS.map((def) => ({
    ...def,
    rows: lineup.filter((row) => row.participation === def.bucket),
  }));

  const [draggingRow, setDraggingRow] = useState<CustomGamePlayer | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  // A plain click on a row (opening the sheet, toggling a role, removing) must
  // stay a click, so the drag waits for the house 6px of intent -- see
  // `useDragSensors`.
  const sensors = useDragSensors();

  const handleDragStart = (event: DragStartEvent) => {
    const data = event.active.data.current as { row: CustomGamePlayer } | undefined;
    if (data) setDraggingRow(data.row);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setDraggingRow(null);
    const target = event.over?.id;
    if (target !== "must_play" && target !== "pool" && target !== "benched") {
      return;
    }
    const memberId = Number(event.active.id);
    const row = lineup.find((item) => item.workspace_member_id === memberId);
    if (!row || row.participation === target) {
      return;
    }
    onPatchPlayer(memberId, { participation: target });
  };

  return (
    <div className={cn(PANEL_CLASS, "flex min-w-0 flex-col")}>
      <div className="flex items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-4 py-3.5">
        <h2 className={CARD_TITLE_CLASS}>Lineup</h2>
        <span className={CAPTION_CLASS}>
          {`${summary.active} in the balance`}
          {summary.benched > 0 ? ` \u00B7 ${summary.benched} benched` : ""}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {canWrite ? (
            <button
              type="button"
              onClick={onOpenPool}
              className={cn(
                EYEBROW_CLASS,
                "rounded px-1 tracking-label text-[color:var(--aqt-teal)] transition-colors hover:text-[color:color-mix(in_srgb,var(--aqt-teal)_80%,white)]",
              )}
            >
              Add players &rarr;
            </button>
          ) : null}
          {canWrite && rotation.length > 0 ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={cn(
                ICON_BUTTON_CLASS,
                "size-7 shrink-0",
                pendingHintCount > 0 && "text-[color:var(--aqt-amber)] hover:text-[color:var(--aqt-amber)]",
              )}
              title={
                pendingHintCount > 0
                  ? `Apply ${pendingHintCount} rotation hint${pendingHintCount === 1 ? "" : "s"}`
                  : "Lineup already matches the rotation hints"
              }
              disabled={applyingHints || pendingHintCount === 0}
              onClick={onApplyRotationHints}
            >
              <Wand2 className="size-3.5" aria-hidden="true" />
              <span className="sr-only">Apply rotation hints</span>
            </Button>
          ) : null}
          {canWrite && rows.length > 0 ? (
            <>
              {/* Icon-only: the confirm dialog already spells the action out in
                  full, and a text button here competed with Add players. */}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className={cn(ICON_BUTTON_CLASS, "size-7 shrink-0 hover:text-rose-200")}
                title="Empty the lobby"
                disabled={clearing}
                onClick={() => setClearOpen(true)}
              >
                <Trash2 className="size-3.5" aria-hidden="true" />
                <span className="sr-only">Empty the lobby</span>
              </Button>
              <ConfirmDialog
                open={clearOpen}
                onOpenChange={setClearOpen}
                intent={{
                  title: "Empty the lobby?",
                  description: `This removes all ${rows.length} players from this mix, along with their role order. Ranks are not affected \u2014 they live in your own book and the workspace roster.`,
                  confirmLabel: "Remove everyone",
                  tone: "danger"
                }}
                pending={clearing}
                onConfirm={() => {
                  setClearOpen(false);
                  onClear();
                }}
              />
            </>
          ) : null}
        </div>
      </div>

      {rows.length > 0 ? (
        <div className="flex border-b border-[color:var(--aqt-border)]">
          {supply.map((entry) => {
            const icon = ROLES.find((role) => role.code === entry.role)?.icon ?? "Support";
            return (
              <div
                key={entry.role}
                className="flex-1 border-r border-[color:var(--aqt-border)] px-3.5 py-2.5 last:border-r-0"
              >
                <div className="flex items-center gap-1.5">
                  <PlayerRoleIcon role={icon} size={16} decorative />
                  <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                    {ROLE_LABELS[entry.role]}
                  </span>
                  <span
                    className={cn(
                      "ml-auto text-caption font-semibold tabular-nums",
                      entry.short > 0
                        ? "text-[color:var(--aqt-amber)]"
                        : "text-[color:var(--aqt-emerald)]",
                    )}
                  >
                    {entry.short > 0
                      ? `${entry.supply} of ${entry.need} \u00B7 short ${entry.short}`
                      : `${entry.supply} of ${entry.need}`}
                  </span>
                </div>
                <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      entry.short > 0
                        ? "bg-[color:var(--aqt-amber)]"
                        : "bg-[color:var(--aqt-emerald)]",
                    )}
                    style={{
                      width: `${Math.min(100, Math.round((entry.supply / entry.need) * 100))}%`,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      {summary.blocking > 0 ? (
        <p className="flex items-start gap-2 border-b border-[color:var(--aqt-border)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_6%,transparent)] px-4 py-2.5 text-caption text-[color:var(--aqt-amber)]">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span>
            {summary.blocking === 1
              ? "1 player has no ranked role and will fail the balance."
              : `${summary.blocking} players have no ranked role and will fail the balance.`}
          </span>
        </p>
      ) : null}

      <div className="p-2.5">
        {!hasMix ? (
          <PageStateCard
            state="empty"
            title="No mix selected"
            description="Open a mix from the list to start filling its lineup."
            className="px-4 py-8"
          />
        ) : lineup.length === 0 ? (
          <PageStateCard
            state="empty"
            title="Lineup is empty"
            description={
              canWrite
                ? "Add players from the workspace pool to put them in this mix."
                : "No players have been added to this mix."
            }
            className="px-4 py-8"
          />
        ) : (
          <DndContext
            sensors={sensors}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragCancel={() => setDraggingRow(null)}
          >
            <div className="flex flex-col gap-2.5" aria-label="Mix lineup">
              {columns.map((column) => (
                <LineupColumn
                  key={column.bucket}
                  bucket={column.bucket}
                  title={column.title}
                  hint={column.hint}
                  emptyHint={column.emptyHint}
                  rows={column.rows}
                  rotationByMember={rotationByMember}
                  canWrite={canWrite}
                  savingPlayerId={savingPlayerId}
                  onPatchPlayer={onPatchPlayer}
                  onOpenPlayer={onOpenPlayer}
                  onRemovePlayer={onRemovePlayer}
                />
              ))}
            </div>
            {/* Follows the pointer instead of the row teleporting under it --
                without this dnd-kit still moves it correctly, it just looks
                broken mid-drag (the dragged row snaps back until drop). */}
            <DragOverlay>{draggingRow ? <LineupDragPreview row={draggingRow} /> : null}</DragOverlay>
          </DndContext>
        )}
      </div>
    </div>
  );
}
