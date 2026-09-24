"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import type { DraftGating } from "@/lib/draft/logic";
import { seatOf, viewerCount } from "@/lib/draft/room-model";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftPresenceState } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { Tournament } from "@/types/tournament.types";

interface RoomHeaderProps {
  tournament: Tournament;
  board: DraftBoard;
  gating: DraftGating;
  presence: DraftPresenceState;
  connectionState: RealtimeConnectionState;
}

type RoomStatus = "live" | "paused" | "completed" | "notStarted" | "cancelled" | "blocked";

const STATUS_COLOR: Record<RoomStatus, string> = {
  live: "var(--aqt-live)",
  paused: "var(--aqt-amber)",
  blocked: "var(--aqt-rose)",
  completed: "var(--aqt-fg-faint)",
  notStarted: "var(--aqt-fg-muted)",
  cancelled: "var(--aqt-fg-faint)"
};

function roomStatus(board: DraftBoard): RoomStatus {
  const { status, blocked_reason } = board.session;
  if (blocked_reason != null && (status === "paused" || status === "live")) return "blocked";
  if (status === "setup" || status === "ready") return "notStarted";
  return status;
}

/** Identification row: where am I, what is the draft doing, who am I in it, am I connected. */
export function RoomHeader({ tournament, board, gating, presence, connectionState }: Readonly<RoomHeaderProps>) {
  const t = useTranslations("draftRedesign");
  const session = board.session;
  const status = roomStatus(board);
  const color = STATUS_COLOR[status];
  const seat = seatOf(gating);
  const myTeam = board.teams.find((team) => team.id === gating.myTeamId) ?? null;

  return (
    <div className="mx-auto flex min-h-[52px] max-w-[1720px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 sm:px-6 xl:h-[52px] xl:flex-nowrap xl:py-0">
      <Link
        href={`/tournaments/${tournament.id}`}
        title={t("room.back")}
        className="-ml-1 inline-flex min-h-11 min-w-0 items-center gap-1.5 rounded-md px-1 text-sm text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] sm:min-h-8"
      >
        <ChevronLeft className="h-4 w-4 shrink-0" aria-hidden />
        <span className="truncate">{tournament.name}</span>
      </Link>
      <span aria-hidden className="hidden h-5 w-px bg-[color:var(--aqt-border-2)] sm:block" />
      <h1 className="font-onest text-lg font-semibold leading-tight">{t("shell.title")}</h1>
      <span
        className="inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-semibold uppercase tracking-[0.08em]"
        style={{ color, borderColor: `color-mix(in srgb, ${color} 45%, transparent)` }}
      >
        <span
          aria-hidden
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            status === "live" && "animate-pulse motion-reduce:animate-none"
          )}
          style={{ background: color }}
        />
        {t(`shell.status.${status}`)}
      </span>

      {/* No live region on the counters: they tick on their own. Only the
          connection state announces itself. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 sm:ml-auto xl:flex-nowrap">
        <span className="hidden whitespace-nowrap text-[13px] text-[color:var(--aqt-fg-dim)] md:inline">
          {t("shell.formatLine", {
            format: t(`shell.formatName.${session.format}`),
            teams: board.teams.length,
            rounds: session.rounds,
            seconds: session.pick_time_seconds
          })}
        </span>
        <span className="whitespace-nowrap text-[13px] tabular-nums text-[color:var(--aqt-fg-dim)]">
          {t("shell.viewers", { count: viewerCount(presence) })}
        </span>
        <span className="inline-flex h-[30px] max-w-full items-center truncate rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-3 text-[13px] font-medium text-[color:var(--aqt-fg-muted)]">
          {seat === "captain" || seat === "captain_admin"
            ? t(`shell.seat.${seat}`, { team: myTeam?.name ?? "" })
            : t(`shell.seat.${seat}`)}
        </span>
        <ConnectionIndicator connectionState={connectionState} />
      </div>
    </div>
  );
}
