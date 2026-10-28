"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent
} from "@dnd-kit/core";
import { AlertTriangle, Trash2, Wand2 } from "lucide-react";

import { CAPTION_CLASS, CARD_TITLE_CLASS } from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useDragSensors } from "@/hooks/useDragSensors";
import { useSlotLabel } from "@/hooks/useSlotLabel";
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
  summarizeRoleSupply,
  type MixOwner
} from "./pickup-lineup";

type PickupLobbyPanelProps = {
  canWrite: boolean;
  hasMix: boolean;
  rows: CustomGamePlayer[];
  /** How many lobbies this mix runs: role demand scales with it, and rows gain a lobby badge. */
  lobbyCount?: number;
  /** The mix owner's game: the roles the supply strip counts, their names and the grid the ranks are on. */
  owner: MixOwner;
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
  /** Fires every actionable rotation hint at once (see `computeRotationHintPatches`). */
  onApplyRotationHints: () => void;
  applyingHints: boolean;
};

/** One drag-and-drop column per participation state, in the order a host reads commitment. */
const COLUMNS: readonly MixParticipation[] = ["must_play", "pool", "benched"];

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
  lobbyCount = 1,
  owner,
  rotation = [],
  savingPlayerId,
  clearing,
  onPatchPlayer,
  onClear,
  onRemovePlayer,
  onOpenPlayer,
  onApplyRotationHints,
  applyingHints,
}: Readonly<PickupLobbyPanelProps>) {
  const t = useTranslations("mixes.lineup");
  const lineup = sortLineup(rows);
  const summary = summarizeLineup(rows, owner.roles);
  const supply = summarizeRoleSupply(rows, owner, lobbyCount);
  const slotLabel = useSlotLabel(owner.ontology);
  const rotationByMember = new Map(rotation.map((r) => [r.workspace_member_id, r]));
  const pendingHintCount = computeRotationHintPatches(rows, rotation).length;
  const columns = COLUMNS.map((bucket) => ({
    bucket,
    title: t(`columns.${bucket}.title`),
    hint: t(`columns.${bucket}.hint`),
    emptyHint: t(`columns.${bucket}.empty`),
    rows: lineup.filter((row) => row.participation === bucket),
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
    <Card className="flex min-w-0 flex-col">
      <div className="flex items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-4 py-3.5">
        <h2 className={CARD_TITLE_CLASS}>{t("title")}</h2>
        <span className={CAPTION_CLASS}>
          {t("inBalance", { count: summary.active })}
          {summary.benched > 0 ? ` \u00B7 ${t("benchedCount", { count: summary.benched })}` : ""}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {canWrite && rotation.length > 0 ? (
            <IconTooltip
              control
              label={pendingHintCount > 0 ? t("applyHintsCount", { count: pendingHintCount }) : t("hintsMatch")}
            >
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(
                  pendingHintCount > 0 && "text-[color:var(--aqt-amber)] hover:text-[color:var(--aqt-amber)]",
                )}
                disabled={applyingHints || pendingHintCount === 0}
                onClick={onApplyRotationHints}
              >
                <Wand2 aria-hidden="true" />
                <span className="sr-only">{t("applyHints")}</span>
              </Button>
            </IconTooltip>
          ) : null}
          {canWrite && rows.length > 0 ? (
            <>
              {/* Icon-only: the confirm dialog already spells the action out in
                  full. */}
              <IconTooltip control label={t("emptyLobby")}>
                <Button
                  type="button"
                  variant="ghost-destructive"
                  size="icon-sm"
                  disabled={clearing}
                  onClick={() => setClearOpen(true)}
                >
                  <Trash2 aria-hidden="true" />
                  <span className="sr-only">{t("emptyLobby")}</span>
                </Button>
              </IconTooltip>
              <ConfirmDialog
                open={clearOpen}
                onOpenChange={setClearOpen}
                intent={{
                  title: t("emptyLobbyTitle"),
                  description: t("emptyLobbyDescription", { count: rows.length }),
                  confirmLabel: t("emptyLobbyConfirm"),
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

      {rows.length > 0 && supply.length > 0 ? (
        <div className="flex flex-wrap border-b border-[color:var(--aqt-border)]">
          {supply.map((entry) => (
            <div
              key={entry.role}
              className="min-w-[7.5rem] flex-1 border-r border-[color:var(--aqt-border)] px-3.5 py-2.5 last:border-r-0"
            >
              <div className="flex items-center gap-1.5">
                <PlayerRoleIcon role={entry.role} ontology={owner.ontology} size={16} decorative />
                <Eyebrow tone="dim">{slotLabel(entry.role)}</Eyebrow>
                <span
                  className={cn(
                    "ml-auto text-caption font-semibold tabular-nums",
                    entry.short > 0
                      ? "text-[color:var(--aqt-amber)]"
                      : "text-[color:var(--aqt-fg-muted)]",
                  )}
                >
                  {entry.short > 0
                    ? t("supplyShort", { supply: entry.supply, short: entry.short })
                    : t("supply", { supply: entry.supply, need: entry.need })}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {summary.blocking > 0 ? (
        <p className="flex items-start gap-2 border-b border-[color:var(--aqt-border)] px-4 py-2.5 text-caption text-[color:var(--aqt-amber)]">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span>{t("blocking", { count: summary.blocking })}</span>
        </p>
      ) : null}

      {!hasMix ? (
        <PageStateCard
          state="empty"
          title={t("noMixTitle")}
          description={t("noMixDescription")}
          className="border-0 bg-transparent px-4 py-10"
        />
      ) : lineup.length === 0 ? (
        <PageStateCard
          state="empty"
          title={t("emptyLineupTitle")}
          description={canWrite ? t("emptyLineupHost") : t("emptyLineupViewer")}
          className="border-0 bg-transparent px-4 py-10"
        />
      ) : (
        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setDraggingRow(null)}
        >
          <div className="flex flex-col" aria-label={t("listLabel")}>
            {columns.map((column) => (
              <LineupColumn
                key={column.bucket}
                bucket={column.bucket}
                title={column.title}
                hint={column.hint}
                emptyHint={column.emptyHint}
                rows={column.rows}
                lobbyCount={lobbyCount}
                rotationByMember={rotationByMember}
                owner={owner}
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
          <DragOverlay>{draggingRow ? <LineupDragPreview row={draggingRow} owner={owner} /> : null}</DragOverlay>
        </DndContext>
      )}
    </Card>
  );
}
