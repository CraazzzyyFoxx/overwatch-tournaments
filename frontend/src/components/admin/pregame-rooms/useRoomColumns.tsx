"use client";

import { useMemo, useSyncExternalStore } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { columnMeta } from "@/components/data-table";
import { ScheduledAtCell } from "@/components/admin/encounters/EncounterCells";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { pregameRoomHref } from "@/lib/encounter/pregame-room";
import { cn } from "@/lib/utils";
import type { PregameKindSummary, PregameRoomRow } from "@/types/admin.types";

import {
  ATTENTION_LABEL,
  ATTENTION_TONE,
  PHASE_LABEL,
  PHASE_TONE,
  currentStep,
  stepActionLabel
} from "./model";

/** The side's own name where there is one, so a cell never reads "home". */
function sideName(room: PregameRoomRow, side: "home" | "away"): string {
  return (side === "home" ? room.home_team?.name : room.away_team?.name) ?? side;
}

function ReadinessCell({ room }: Readonly<{ room: PregameRoomRow }>) {
  return (
    <div className="flex flex-col gap-1">
      {(["home", "away"] as const).map((side) => (
        <StatusPill key={side} tone={room.readiness[side] ? "success" : "neutral"}>
          <span className="max-w-[9rem] truncate">{sideName(room, side)}</span>
        </StatusPill>
      ))}
    </div>
  );
}

/**
 * The step the room is holding, in the words the room itself uses: which round
 * of the series, how far through its order, what the acting side has to do —
 * or, when an organizer stepped in, that the session is paused or cancelled.
 */
function StepCell({ room }: Readonly<{ room: PregameRoomRow }>) {
  const step = currentStep(room);
  if (!step) return <span className="text-muted-foreground">—</span>;
  const { kind, summary } = step;
  const cancelled = summary.status === "cancelled";

  return (
    <div className="min-w-0 text-sm">
      <p className="flex min-w-0 items-center gap-1.5 truncate">
        <span className="text-muted-foreground">{kind === "map" ? "Maps" : "Heroes"}</span>
        {summary.current_round != null ? (
          <span className="text-muted-foreground">· R{summary.current_round}</span>
        ) : null}
        {summary.step_index != null ? (
          <span className="tabular-nums text-muted-foreground">
            · {summary.step_index + 1}/{summary.step_count}
          </span>
        ) : null}
        {cancelled ? <StatusPill tone="danger">Cancelled</StatusPill> : null}
        {summary.paused_at != null ? <StatusPill tone="warning">Paused</StatusPill> : null}
      </p>
      {cancelled ? (
        <p className="truncate text-xs text-muted-foreground">Cancelled by an organizer</p>
      ) : summary.awaiting_choice ? (
        <p className="truncate text-xs text-warning">Waiting on who opens the round</p>
      ) : (
        <p className="truncate text-xs text-muted-foreground">
          {stepActionLabel(summary.step_action)}
          {summary.step_blind ? " (blind)" : ""}
          {summary.acting_sides.length > 0
            ? ` · ${summary.acting_sides.map((side) => sideName(room, side)).join(" & ")}`
            : ""}
        </p>
      )}
    </div>
  );
}

// Module-level so their identity is stable: `useSyncExternalStore`
// resubscribes whenever the subscribe function it is handed changes.
function subscribeEverySecond(onTick: () => void): () => void {
  const id = window.setInterval(onTick, 1000);
  return () => window.clearInterval(id);
}

function subscribeNever(): () => void {
  return () => {};
}

/**
 * Live countdown to the open step's deadline.
 *
 * Its own ticking clock rather than one in the browser: a `now` passed down
 * from the parent would rebuild every column definition each second, which is
 * the whole table re-rendering to move one number. The clock is an external
 * store snapshotted to the whole second, so repeated reads within a render
 * agree, and its server snapshot is `null`: rendering a remaining time on the
 * server would hydrate against a different second.
 */
function DeadlineCell({ summary }: Readonly<{ summary: PregameKindSummary | null }>) {
  const deadline = summary?.deadline_at ? Date.parse(summary.deadline_at) : null;
  const nowSecond = useSyncExternalStore<number | null>(
    deadline == null ? subscribeNever : subscribeEverySecond,
    () => Math.floor(Date.now() / 1000),
    () => null
  );

  if (deadline == null || Number.isNaN(deadline)) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (nowSecond == null) return <span className="text-muted-foreground tabular-nums">--:--</span>;

  const left = Math.round(deadline / 1000) - nowSecond;
  if (left <= 0) return <StatusPill tone="danger">Overdue</StatusPill>;

  const minutes = Math.floor(left / 60);
  return (
    <span className={cn("text-sm tabular-nums", left <= 30 && "font-semibold text-warning")}>
      {minutes}:{String(left % 60).padStart(2, "0")}
    </span>
  );
}

/**
 * One row per pre-game room: who plays, how far the room has got, and the one
 * link that takes an organizer into it.
 */
export function useRoomColumns({
  tournamentId,
  returnTo
}: Readonly<{
  tournamentId: number;
  /** Where "Open room" sends the organizer back to — this very screen. */
  returnTo: string;
}>): ColumnDef<PregameRoomRow>[] {
  return useMemo<ColumnDef<PregameRoomRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Match",
        meta: columnMeta<PregameRoomRow>({
          mandatory: true,
          searchValue: (row) =>
            [row.name, row.home_team?.name, row.away_team?.name].filter(Boolean).join(" ")
        }),
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[20rem]">
            <p className="truncate font-medium text-foreground" title={row.original.name}>
              {row.original.name}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.stage_name ?? "Unassigned"} · R{row.original.round} · Bo
              {row.original.best_of}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.home_team?.name ?? "TBD"} vs {row.original.away_team?.name ?? "TBD"}
              {row.original.home_score + row.original.away_score > 0 ? (
                <span className="font-mono tabular-nums">
                  {" "}
                  · {row.original.home_score}&ndash;{row.original.away_score}
                </span>
              ) : null}
            </p>
          </div>
        )
      },
      {
        accessorKey: "scheduled_at",
        header: "Scheduled",
        size: 132,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) => <ScheduledAtCell value={row.original.scheduled_at} />
      },
      {
        id: "readiness",
        header: "Ready",
        size: 148,
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) => <ReadinessCell room={row.original} />
      },
      {
        accessorKey: "phase",
        header: "Phase",
        size: 128,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) => (
          <StatusPill tone={PHASE_TONE[row.original.phase]}>
            {PHASE_LABEL[row.original.phase]}
          </StatusPill>
        )
      },
      {
        id: "step",
        header: "Current step",
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) => <StepCell room={row.original} />
      },
      {
        id: "timer",
        header: "Timer",
        size: 96,
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "core", align: "center" }),
        cell: ({ row }) => <DeadlineCell summary={currentStep(row.original)?.summary ?? null} />
      },
      {
        id: "games",
        header: "Maps",
        size: 112,
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "meta", align: "center" }),
        cell: ({ row }) => (
          <div className="text-sm">
            <span className="tabular-nums">
              {row.original.games.confirmed}/{row.original.games.total}
            </span>
            {row.original.games.disputed > 0 ? (
              <p className="text-xs text-danger">{row.original.games.disputed} disputed</p>
            ) : null}
          </div>
        )
      },
      {
        id: "attention",
        header: "Attention",
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) =>
          row.original.attention.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {row.original.attention.map((flag) => (
                <StatusPill key={flag} tone={ATTENTION_TONE[flag]}>
                  {ATTENTION_LABEL[flag]}
                </StatusPill>
              ))}
            </div>
          )
      },
      {
        id: "open",
        header: "",
        size: 128,
        enableSorting: false,
        enableResizing: false,
        meta: columnMeta<PregameRoomRow>({ align: "right" }),
        cell: ({ row }) => (
          <Button asChild variant="outline" size="sm">
            <Link href={pregameRoomHref(tournamentId, row.original.encounter_id, returnTo)}>
              <ExternalLink aria-hidden className="size-3.5" />
              Open room
            </Link>
          </Button>
        )
      }
    ],
    [tournamentId, returnTo]
  );
}
