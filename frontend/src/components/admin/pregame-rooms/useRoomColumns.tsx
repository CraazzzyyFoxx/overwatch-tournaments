"use client";

import { useMemo, useSyncExternalStore } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertTriangle, Check } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { columnMeta } from "@/components/data-table";
import { ScheduledAtCell } from "@/components/admin/encounters/EncounterCells";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { pregameRoomHref } from "@/lib/encounter/pregame-room";
import { cn } from "@/lib/utils";
import type { PregameKindSummary, PregameRoomRow } from "@/types/admin.types";

import { seatsBySlot } from "@/lib/encounter/seats";
import {
  ATTENTION_LABEL,
  ATTENTION_TONE,
  PHASE_LABEL,
  PHASE_TONE,
  currentStep,
  sortByKickoff,
  sortByPhase,
  stepActionLabel
} from "./model";

type PregameTranslator = ReturnType<typeof useTranslations<"adminMatches.pregame">>;

/**
 * The row's one status. An organizer stepping in (cancel, pause) outranks the
 * phase the room would otherwise be in; a finished room shows nothing, and a
 * room that is not running yet says so in plain text.
 */
function PhaseCell({ room, t }: Readonly<{ room: PregameRoomRow; t: PregameTranslator }>) {
  const summary = currentStep(room)?.summary;
  if (summary?.status === "cancelled") return <StatusPill tone="danger">{t("cancelled")}</StatusPill>;
  if (summary?.paused_at != null) return <StatusPill tone="warning">{t("paused")}</StatusPill>;
  if (room.phase === "done") return null;

  const label = t(PHASE_LABEL[room.phase] as Parameters<PregameTranslator>[0]);
  const tone = PHASE_TONE[room.phase];
  if (tone === "neutral") return <span className="text-sm text-muted-foreground">{label}</span>;
  return <StatusPill tone={tone}>{label}</StatusPill>;
}

/**
 * The step the room is holding, in the words the room itself uses: which round
 * of the series, how far through its order, what the acting side has to do.
 * A cancel or a pause is the phase column's to say.
 */
function StepCell({ room, t }: Readonly<{ room: PregameRoomRow; t: PregameTranslator }>) {
  const step = currentStep(room);
  if (!step) return null;
  const { kind, summary } = step;

  return (
    <div className="min-w-0 text-sm">
      <p className="flex min-w-0 items-center gap-1.5 truncate text-muted-foreground">
        <span>{kind === "map" ? t("maps") : t("heroes")}</span>
        {summary.current_round != null ? <span>· R{summary.current_round}</span> : null}
        {summary.step_index != null ? (
          <span className="tabular-nums">
            · {summary.step_index + 1}/{summary.step_count}
          </span>
        ) : null}
      </p>
      {summary.status === "cancelled" ? null : summary.awaiting_choice ? (
        <p className="truncate text-xs text-warning">{t("waitingOpener")}</p>
      ) : summary.step_action ? (
        <p className="truncate text-xs text-muted-foreground">
          {t("stepSummary", {
            action: t(stepActionLabel(summary.step_action) as Parameters<PregameTranslator>[0]),
            blind: summary.step_blind ? t("blind") : "",
            sides:
              summary.acting_team_ids.length > 0
                ? ` · ${summary.acting_team_ids
                    .map((id) => room.teams.find((seat) => seat.encounter_team_id === id)?.name ?? "?")
                    .join(" & ")}`
                : ""
          })}
        </p>
      ) : null}
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
function DeadlineCell({ summary, t }: Readonly<{ summary: PregameKindSummary | null; t: PregameTranslator }>) {
  const deadline = summary?.deadline_at ? Date.parse(summary.deadline_at) : null;
  const nowSecond = useSyncExternalStore<number | null>(
    deadline == null ? subscribeNever : subscribeEverySecond,
    () => Math.floor(Date.now() / 1000),
    () => null
  );

  if (deadline == null || Number.isNaN(deadline) || nowSecond == null) return null;

  const left = Math.round(deadline / 1000) - nowSecond;
  if (left <= 0) return <span className="text-sm text-danger">{t("overdue")}</span>;

  const minutes = Math.floor(left / 60);
  return (
    <span className={cn("text-sm tabular-nums", left <= 30 && "font-semibold text-warning")}>
      {minutes}:{String(left % 60).padStart(2, "0")}
    </span>
  );
}

/** Every flag on the row as one glyph; the flags themselves are its label. */
function AttentionCell({ room, t }: Readonly<{ room: PregameRoomRow; t: PregameTranslator }>) {
  if (room.attention.length === 0) return null;
  const label = room.attention
    .map((flag) => t(ATTENTION_LABEL[flag] as Parameters<PregameTranslator>[0]))
    .join(", ");
  const danger = room.attention.some((flag) => ATTENTION_TONE[flag] === "danger");
  return <StatusIcon icon={AlertTriangle} label={label} variant={danger ? "destructive" : "warning"} />;
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
  const t = useTranslations("adminMatches.pregame");
  return useMemo<ColumnDef<PregameRoomRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: t("match"),
        meta: columnMeta<PregameRoomRow>({
          mandatory: true,
          searchValue: (row) =>
            [row.name, ...row.teams.map((seat) => seat.name)].filter(Boolean).join(" ")
        }),
        cell: ({ row }) => {
          const seats = seatsBySlot(row.original.teams);
          return (
            <div className="min-w-0 max-w-[20rem]">
              <p className="truncate font-medium text-foreground" title={row.original.name}>
                {row.original.name}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {t("matchDetails", {
                  stage: row.original.stage_name ?? t("unassigned"),
                  round: row.original.round
                })}
              </p>
              {/* Readiness rides on the names it is about, rather than a
                  column that repeats them. */}
              <p className="flex min-w-0 items-center gap-1 truncate text-xs text-muted-foreground">
                {seats.length === 0
                  ? t("tbd")
                  : seats.map((seat, index) => (
                      <span key={seat.encounter_team_id} className="inline-flex items-center gap-1">
                        {index > 0 ? <span>{t("vs")}</span> : null}
                        <span className="truncate">{seat.name}</span>
                        {row.original.readiness[String(seat.encounter_team_id)] ? (
                          <StatusIcon icon={Check} label={t("ready")} variant="success" className="size-3.5" />
                        ) : null}
                      </span>
                    ))}
                {row.original.teams.some((seat) => seat.score > 0) ? (
                  <span className="tabular-nums">
                    · {seats.map((seat) => seat.score).join(":")}
                  </span>
                ) : null}
              </p>
            </div>
          );
        }
      },
      {
        accessorKey: "scheduled_at",
        header: t("scheduled"),
        size: 132,
        sortingFn: sortByKickoff,
        // Picked again, it starts where the table's default does: newest first.
        sortDescFirst: true,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) => <ScheduledAtCell value={row.original.scheduled_at} />
      },
      {
        accessorKey: "phase",
        header: t("phaseColumn"),
        size: 128,
        sortingFn: sortByPhase,
        meta: columnMeta<PregameRoomRow>({ category: "core", align: "center" }),
        cell: ({ row }) => <PhaseCell room={row.original} t={t} />
      },
      {
        id: "step",
        header: t("currentStep"),
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "core" }),
        cell: ({ row }) => <StepCell room={row.original} t={t} />
      },
      {
        id: "timer",
        header: t("timer"),
        size: 96,
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "core", align: "center" }),
        cell: ({ row }) => <DeadlineCell summary={currentStep(row.original)?.summary ?? null} t={t} />
      },
      {
        id: "games",
        header: t("maps"),
        size: 96,
        enableSorting: false,
        meta: columnMeta<PregameRoomRow>({ category: "meta", align: "center" }),
        cell: ({ row }) => (
          <span className="text-sm tabular-nums">
            {row.original.games.confirmed}/{row.original.games.total}
          </span>
        )
      },
      {
        id: "attention",
        header: t("attentionColumn"),
        size: 96,
        // How many flags the room carries, the most first.
        accessorFn: (row) => row.attention.length,
        sortDescFirst: true,
        meta: columnMeta<PregameRoomRow>({ category: "core", align: "center" }),
        cell: ({ row }) => <AttentionCell room={row.original} t={t} />
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
              {t("openRoom")}
            </Link>
          </Button>
        )
      }
    ],
    [tournamentId, returnTo, t]
  );
}
