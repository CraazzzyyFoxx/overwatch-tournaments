"use client";

import { useDroppable } from "@dnd-kit/core";
import { Pin } from "lucide-react";

import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { cn } from "@/lib/utils";
import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  MixParticipation,
  RotationRecommendation
} from "@/services/custom-game.service";

import { LineupRow } from "./LineupRow";

/**
 * One participation column's drop zone: a titled card that highlights while a
 * dragged row hovers over it, and holds that column's rows or an empty hint.
 */
export function LineupColumn({
  bucket,
  title,
  hint,
  emptyHint,
  rows,
  rotationByMember,
  canWrite,
  savingPlayerId,
  onPatchPlayer,
  onOpenPlayer,
  onRemovePlayer
}: Readonly<{
  bucket: MixParticipation;
  title: string;
  hint: string;
  emptyHint: string;
  rows: CustomGamePlayer[];
  rotationByMember: Map<number, RotationRecommendation>;
  canWrite: boolean;
  savingPlayerId: number | null;
  onPatchPlayer: (workspaceMemberId: number, patch: CustomGamePlayerPatch) => void;
  onOpenPlayer: (workspaceMemberId: number) => void;
  onRemovePlayer: (workspaceMemberId: number) => void;
}>) {
  const droppable = useDroppable({ id: bucket, disabled: !canWrite });
  const dimmed = bucket === "benched";

  return (
    <section
      ref={(node) => droppable.setNodeRef(node)}
      aria-label={title}
      className={cn(
        "flex flex-col gap-1.5 rounded-xl border px-2.5 py-2.5 transition-colors",
        droppable.isOver
          ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_7%,transparent)]"
          : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)]"
      )}
    >
      <div className="flex items-baseline gap-1.5 px-0.5">
        {bucket === "must_play" ? (
          <Pin
            className="size-3 shrink-0 text-[color:var(--aqt-amber)]"
            aria-hidden="true"
            fill="currentColor"
          />
        ) : null}
        <span
          className={cn(
            EYEBROW_CLASS,
            "tracking-label",
            bucket === "must_play" && "text-[color:var(--aqt-amber)]"
          )}
        >
          {title}
        </span>
        <span className="text-label text-[color:var(--aqt-fg-dim)]">{rows.length}</span>
        <span className="ml-auto hidden truncate text-label text-[color:var(--aqt-fg-faint)] sm:block">
          {hint}
        </span>
      </div>
      {rows.length === 0 ? (
        <p
          className={cn(
            "rounded-lg border border-dashed px-2.5 py-3 text-center text-label transition-colors",
            droppable.isOver
              ? "border-[color:var(--aqt-teal)] text-[color:var(--aqt-teal)]"
              : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-faint)]"
          )}
        >
          {emptyHint}
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {rows.map((row) => (
            <LineupRow
              key={row.workspace_member_id}
              row={row}
              rotationHint={rotationByMember.get(row.workspace_member_id)}
              canWrite={canWrite}
              saving={savingPlayerId === row.workspace_member_id}
              dimmed={dimmed}
              onPatch={(patch) => onPatchPlayer(row.workspace_member_id, patch)}
              onOpen={() => onOpenPlayer(row.workspace_member_id)}
              onRemove={() => onRemovePlayer(row.workspace_member_id)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
