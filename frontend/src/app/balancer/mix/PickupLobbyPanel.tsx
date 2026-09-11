"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  AlertTriangle,
  Armchair,
  GripVertical,
  Pin,
  RotateCw,
  SlidersHorizontal,
  Trash2,
  Wand2,
  X,
} from "lucide-react";

import {
  ICON_BUTTON_CLASS,
  PANEL_CLASS,
  splitBattleTag,
} from "@/app/balancer/components/balancer-page-helpers";
import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  EYEBROW_CLASS,
  ROLE_ICON_COLOR,
} from "@/app/balancer/pickup/pickup-chrome";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { OW_REFERENCE_GRID, resolveDivisionFromRank } from "@/lib/division-grid";
import { ROLE_LABELS, ROLES } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  MixParticipation,
  RotationRecommendation,
} from "@/services/custom-game.service";

import {
  LINEUP_ROLES,
  averageRank,
  computeRotationHintPatches,
  getLineupIssue,
  playerLabel,
  resolveRoleOrder,
  sortLineup,
  summarizeLineup,
  summarizeRoleSupply,
  toggleRole,
} from "./pickup-lineup";

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
  // 6px before a drag starts: without it, a plain click on a row (opening the
  // sheet, toggling a role, removing) reads as a zero-distance drag and
  // dnd-kit swallows the event.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

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
            <AlertDialog>
              <AlertDialogTrigger asChild>
                {/* Icon-only: the confirm dialog already spells the action out in
                    full, and a text button here competed with Add players. */}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className={cn(ICON_BUTTON_CLASS, "size-7 shrink-0 hover:text-rose-200")}
                  title="Empty the lobby"
                  disabled={clearing}
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">Empty the lobby</span>
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Empty the lobby?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {`This removes all ${rows.length} players from this mix, along with their role order. Ranks are not affected \u2014 they live in your own book and the workspace roster.`}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep the lobby</AlertDialogCancel>
                  <AlertDialogAction onClick={onClear}>Remove everyone</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
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
                <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-white/[0.05]">
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

/**
 * One participation column's drop zone: a titled card that highlights while a
 * dragged row hovers over it, and holds that column's rows or an empty hint.
 */
function LineupColumn({
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
  onRemovePlayer,
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
          : "border-[color:var(--aqt-border-2)] bg-white/[0.012]",
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
            bucket === "must_play" && "text-[color:var(--aqt-amber)]",
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
              : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-faint)]",
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

/**
 * The roles a player can be seated in, in the order the host set them.
 *
 * Three facts in one 102px rail, none of them a number: **which** roles the
 * balancer may use (a tinted tile vs a flat dim glyph), **which one comes
 * first** (the role-coloured underline, and leftmost position), and **which
 * selection will fail** (the amber ring — a role switched on with no rank
 * behind it, which rejects the whole run server-side).
 *
 * The order is the balancer's stored priority (see `resolveRoleOrder`), so a
 * click here only ever turns a role on or off — reordering belongs to the
 * player sheet, which has room for a drag list.
 */
function RolePriorityRail({
  row,
  label,
  canWrite,
  saving,
  onPatch,
}: Readonly<{
  row: CustomGamePlayer;
  label: string;
  canWrite: boolean;
  saving: boolean;
  onPatch: (patch: CustomGamePlayerPatch) => void;
}>) {
  const order = resolveRoleOrder(row);
  // Off roles trail the selected ones in canonical order: an unselected role
  // has no priority, so placing them at all would imply one.
  const off = LINEUP_ROLES.filter((role) => !order.includes(role));

  return (
    <div
      role="group"
      aria-label={`Roles for ${label}`}
      className="flex w-[102px] shrink-0 items-center justify-end gap-1.5"
    >
      {[...order, ...off].map((role) => {
        const position = order.indexOf(role);
        const isOn = position !== -1;
        const isPrimary = position === 0;
        const roleRank = row.ranks[role];
        const icon = ROLES.find((item) => item.code === role)?.icon ?? "Support";
        return (
          <button
            key={role}
            type="button"
            disabled={!canWrite || saving}
            aria-pressed={isOn}
            aria-label={`${ROLE_LABELS[role]} for ${label}, ${
              isOn ? (isPrimary ? "first choice" : "also plays") : "off"
            }${roleRank == null ? ", no rank" : `, ${roleRank} points`}`}
            title={
              roleRank == null
                ? `${ROLE_LABELS[role]}: no rank`
                : `${ROLE_LABELS[role]}: ${roleRank} pts`
            }
            onClick={() => onPatch({ roles: toggleRole(order, role) })}
            className={cn(
              "relative flex size-[30px] shrink-0 items-center justify-center rounded-lg transition-opacity",
              isOn ? "opacity-100" : "opacity-30",
              isOn && roleRank == null && "ring-1 ring-amber-400/70",
              "disabled:cursor-default",
            )}
          >
            <PlayerRoleIcon
              role={icon}
              size={19}
              decorative
              color={isOn ? ROLE_ICON_COLOR[role] : undefined}
            />
          </button>
        );
      })}
    </div>
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
  pinned,
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
        isOwed ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-fg-faint)]",
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{hint.reason}</span>
    </span>
  );
}

/**
 * One lineup row, draggable between the three `LineupColumn`s.
 *
 * The whole row is both the click target that opens the drawer and the drag
 * source that moves it between columns — a `PointerSensor` activation
 * distance (see `PickupLobbyPanel`) tells the two apart, the same pattern the
 * matchup board's seat rows already use. A click that started inside a
 * `RowAction` still belongs to that control, never the row's own onOpen.
 */
function LineupRow({
  row,
  rotationHint,
  canWrite,
  saving,
  dimmed,
  onPatch,
  onOpen,
  onRemove,
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
    disabled: !canDrag,
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
        "hover:border-[color:var(--aqt-border-2)] hover:bg-white/[0.025]",
        canDrag && "touch-none active:cursor-grabbing",
        issue && "border-amber-400/35",
        draggable.isDragging ? "opacity-30" : dimmed && "opacity-60",
      )}
    >
      <GripVertical
        className={cn("size-3.5 shrink-0", canDrag ? "text-[color:var(--aqt-fg-faint)]" : "text-transparent")}
        aria-hidden="true"
      />

      <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
        <span className="truncate text-caption font-semibold text-[color:var(--aqt-fg)]">
          {name}
        </span>
        {suffix ? (
          <span className="shrink-0 text-xs text-[color:var(--aqt-fg-faint)]">
            {suffix}
          </span>
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
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-[color:var(--aqt-fg-faint)] transition-colors hover:bg-white/[0.05] hover:text-[color:var(--aqt-fg-muted)]"
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
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-[color:var(--aqt-fg-faint)] transition-colors hover:bg-white/[0.05] hover:text-[color:var(--aqt-rose)]"
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
function LineupDragPreview({ row }: Readonly<{ row: CustomGamePlayer }>) {
  const label = playerLabel(row);
  const { name, suffix } = splitBattleTag(label);
  const rank = averageRank(row);

  return (
    <div
      className={cn(
        PANEL_CLASS,
        "flex w-[280px] cursor-grabbing items-center gap-2 rounded-lg border-[color:var(--aqt-teal)] px-2.5 py-2 shadow-lg",
      )}
    >
      <GripVertical className="size-3.5 shrink-0 text-[color:var(--aqt-fg-faint)]" aria-hidden="true" />
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
