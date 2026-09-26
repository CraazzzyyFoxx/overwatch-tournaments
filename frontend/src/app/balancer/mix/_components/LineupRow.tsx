"use client";

import type { ReactNode } from "react";

import { useDraggable } from "@dnd-kit/core";
import { Armchair, GripVertical, RotateCw, SlidersHorizontal, X } from "lucide-react";

import { PANEL_CLASS, splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import DivisionIcon from "@/components/DivisionIcon";
import { OW_REFERENCE_GRID, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  RotationRecommendation
} from "@/services/custom-game.service";

import { averageRank, getLineupIssue, playerLabel } from "../pickup-lineup";
import { RolePriorityRail } from "./RolePriorityRail";

/**
 * Marks a subtree as owning its own clicks, so the clickable row skips it.
 *
 * A plain wrapper with no handler: putting `onClick` on a `<span>` to swallow
 * the bubble made the row's own logic depend on a non-interactive element
 * having a listener, which the design gate rightly rejects. The row filters by
 * this attribute instead — the same `data-card-action` convention the
 * tournament pool row uses.
 */
function RowAction({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span data-card-action className="flex shrink-0 items-center">
      {children}
    </span>
  );
}

/**
 * The rotation-fairness verdict for one row, as a single 18px icon -- a
 * `neutral` verdict (or none loaded yet) renders nothing, so a mix with no
 * map history yet looks exactly like it did before this existed. `must_play`
 * (owed a seat the longest) and `should_rest` (played the most in a row) are
 * the only two a host acts on, so they are the only two with an icon; the
 * reason string carries the specific streak into the tooltip instead of a
 * wider label competing with the role rail for room. A row the host already
 * pinned (the `must_play` column) never renders one either -- the backend always
 * verdicts a pin `must_play` too (see `mix_rotation.recommend_rotation`), and
 * repeating "owed a seat" next to a seat already guaranteed by the Pin icon
 * is the same fact said twice.
 */
function RotationHintBadge({
  hint,
  pinned
}: Readonly<{ hint: RotationRecommendation | undefined; pinned: boolean }>) {
  if (!hint || hint.status === "neutral" || pinned) {
    return null;
  }
  const isOwed = hint.status === "must_play";
  const Icon = isOwed ? RotateCw : Armchair;
  return (
    <span
      title={hint.reason}
      className={cn(
        "flex size-[18px] shrink-0 items-center justify-center",
        isOwed ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-fg-faint)]"
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{hint.reason}</span>
    </span>
  );
}

type LineupRowProps = {
  row: CustomGamePlayer;
  /** This member's rotation-fairness verdict, if the fetch has one. */
  rotationHint: RotationRecommendation | undefined;
  canWrite: boolean;
  saving: boolean;
  /** Benched rows read de-emphasised and freeze their role rail. */
  dimmed: boolean;
  onPatch: (patch: CustomGamePlayerPatch) => void;
  onOpen: () => void;
  onRemove: () => void;
};

/**
 * One lineup row, draggable between the three `LineupColumn`s.
 *
 * The whole row is both the click target that opens the drawer and the drag
 * source that moves it between columns — a `PointerSensor` activation
 * distance (see `useDragSensors`) tells the two apart, the same pattern the
 * matchup board's seat rows already use. A click that started inside a
 * `RowAction` still belongs to that control, never the row's own onOpen.
 */
export function LineupRow({
  row,
  rotationHint,
  canWrite,
  saving,
  dimmed,
  onPatch,
  onOpen,
  onRemove
}: Readonly<LineupRowProps>) {
  // The global OW grid, not the workspace's: balancer-service resolves a mix's
  // ranks against the grid with `workspace_id=None`, so these ranks are on the
  // OW scale. Labelling them with a workspace's tiers renames the same number.
  const grid = OW_REFERENCE_GRID;
  const label = playerLabel(row);
  const { name, suffix } = splitBattleTag(label);
  const issue = getLineupIssue(row);
  const rank = averageRank(row);
  const division = resolveDivisionFromRank(grid, rank);
  const canDrag = canWrite && !saving;
  const draggable = useDraggable({
    id: String(row.workspace_member_id),
    data: { row },
    disabled: !canDrag
  });

  return (
    <li
      ref={(node) => draggable.setNodeRef(node)}
      {...draggable.listeners}
      {...draggable.attributes}
      title={`${label} \u2014 roles and ranks`}
      onClick={(event) => {
        // `event.target` on a click landing on the role/remove buttons' SVG
        // icon is an `SVGElement`, which is not an `HTMLElement` \u2014 checking
        // the narrower type let those clicks fall through to `onOpen()`.
        if (event.target instanceof Element && event.target.closest("[data-card-action]")) {
          return;
        }
        onOpen();
      }}
      className={cn(
        "flex items-center gap-2 rounded-lg border border-transparent px-2 py-2 transition-colors",
        "hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-2)]",
        canDrag && "touch-none active:cursor-grabbing",
        issue && "border-amber-400/35",
        draggable.isDragging ? "opacity-30" : dimmed && "opacity-60"
      )}
    >
      <GripVertical
        className={cn(
          "size-3.5 shrink-0",
          canDrag ? "text-[color:var(--aqt-fg-faint)]" : "text-transparent"
        )}
        aria-hidden="true"
      />

      <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
        <span className="truncate text-caption font-semibold text-[color:var(--aqt-fg)]">
          {name}
        </span>
        {suffix ? (
          <span className="shrink-0 text-xs text-[color:var(--aqt-fg-faint)]">{suffix}</span>
        ) : null}
      </span>

      <RotationHintBadge hint={rotationHint} pinned={row.participation === "must_play"} />

      <RowAction>
        <RolePriorityRail
          row={row}
          label={label}
          canWrite={canWrite && !dimmed}
          saving={saving}
          onPatch={onPatch}
        />
      </RowAction>

      <div className="flex w-[92px] shrink-0 items-center justify-end gap-1.5">
        {division == null ? null : (
          <DivisionIcon division={division} tournamentGrid={grid} width={22} height={22} />
        )}
        {/* One number, one meaning: the mean of the effective ranks the balancer
            will use. The `*` that used to mark a per-mix pin is gone with the pin
            itself — which layer each role resolved from is named in the sheet. */}
        <span
          title="Mean effective rank across this player's roles"
          className="text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]"
        >
          {rank ?? "\u2014"}
        </span>
      </div>

      <button
        type="button"
        onClick={onOpen}
        title="Advanced settings"
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-[color:var(--aqt-fg-faint)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg-muted)]"
      >
        <SlidersHorizontal className="size-[15px]" aria-hidden="true" />
        <span className="sr-only">{`Advanced settings for ${label}`}</span>
      </button>

      {canWrite ? (
        <RowAction>
          <button
            type="button"
            onClick={onRemove}
            title="Remove from this mix"
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-[color:var(--aqt-fg-faint)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-rose)]"
          >
            <X className="size-3.5" aria-hidden="true" />
            <span className="sr-only">{`Remove ${label} from this mix`}</span>
          </button>
        </RowAction>
      ) : null}
    </li>
  );
}

/** The dragged row's own card, detached from its column, following the pointer. */
export function LineupDragPreview({ row }: Readonly<{ row: CustomGamePlayer }>) {
  const label = playerLabel(row);
  const { name, suffix } = splitBattleTag(label);
  const rank = averageRank(row);

  return (
    <div
      className={cn(
        PANEL_CLASS,
        "flex w-[280px] cursor-grabbing items-center gap-2 rounded-lg border-[color:var(--aqt-teal)] px-2.5 py-2 shadow-lg"
      )}
    >
      <GripVertical
        className="size-3.5 shrink-0 text-[color:var(--aqt-fg-faint)]"
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate text-caption font-semibold text-[color:var(--aqt-fg)]">
        {name}
        {suffix ? (
          <span className="ml-1 text-xs text-[color:var(--aqt-fg-faint)]">{suffix}</span>
        ) : null}
      </span>
      <span className="shrink-0 text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]">
        {rank ?? "\u2014"}
      </span>
    </div>
  );
}
