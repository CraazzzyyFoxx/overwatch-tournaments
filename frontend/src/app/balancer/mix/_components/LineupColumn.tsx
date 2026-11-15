"use client";

import { useDroppable } from "@dnd-kit/core";
import { Pin } from "lucide-react";

import { CAPTION_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { cn } from "@/lib/utils";
import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  MixParticipation,
  RotationRecommendation
} from "@/services/custom-game.service";

import type { MixOwner } from "../pickup-lineup";
import { LineupRow } from "./LineupRow";

/**
 * One participation group's drop zone: an open group under a hairline (no
 * frame of its own inside the lineup card) that tints teal while a dragged row
 * hovers over it, and holds that group's rows or one dashed drop line.
 */
export function LineupColumn({
  bucket,
  title,
  hint,
  emptyHint,
  rows,
  lobbyCount,
  rotationByMember,
  owner,
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
  lobbyCount: number;
  rotationByMember: Map<number, RotationRecommendation>;
  owner: MixOwner;
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
      aria-label={title}
      className="border-t border-[color:var(--aqt-border)] px-2 py-1.5 first:border-t-0"
    >
      <div
        ref={(node) => droppable.setNodeRef(node)}
        className={cn(
          "flex flex-col gap-1 rounded-lg py-1.5 transition-colors",
          droppable.isOver && "bg-[color:color-mix(in_srgb,var(--aqt-teal)_7%,transparent)]"
        )}
      >
        <div className="flex items-baseline gap-1.5 px-2">
          {bucket === "must_play" ? (
            <Pin
              className="size-3 shrink-0 text-[color:var(--aqt-amber)]"
              aria-hidden="true"
              fill="currentColor"
            />
          ) : null}
          <Eyebrow>{title}</Eyebrow>
          <span className={CAPTION_CLASS}>{rows.length}</span>
          <span className={cn(CAPTION_CLASS, "ml-auto hidden truncate sm:block")}>{hint}</span>
        </div>
        {rows.length === 0 ? (
          <p
            className={cn(
              "rounded-lg border border-dashed px-2.5 py-2 text-center text-label transition-colors",
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
                owner={owner}
                canWrite={canWrite}
                lobbyCount={lobbyCount}
                saving={savingPlayerId === row.workspace_member_id}
                dimmed={dimmed}
                onPatch={(patch) => onPatchPlayer(row.workspace_member_id, patch)}
                onOpen={() => onOpenPlayer(row.workspace_member_id)}
                onRemove={() => onRemovePlayer(row.workspace_member_id)}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
