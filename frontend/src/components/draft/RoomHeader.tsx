"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/ui/status-dot";
import type { DraftGating } from "@/lib/draft/logic";
import { seatOf, viewerCount } from "@/lib/draft/room-model";
import type { DraftBoard, DraftPresenceState } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";

import type { DraftOwner } from "./DraftBoard";

interface RoomHeaderProps {
  owner: DraftOwner;
  board: DraftBoard;
  gating: DraftGating;
  presence: DraftPresenceState;
  connectionState: RealtimeConnectionState;
}

type RoomStatus = "live" | "paused" | "completed" | "notStarted" | "cancelled" | "blocked";

const STATUS_COLOR: Record<RoomStatus, string> = {
  live: "var(--aqt-status-live)",
  paused: "var(--aqt-status-upcoming)",
  blocked: "var(--aqt-rose)",
  completed: "var(--aqt-status-finished)",
  notStarted: "var(--aqt-fg-muted)",
  cancelled: "var(--aqt-status-finished)"
};

function roomStatus(board: DraftBoard): RoomStatus {
  const { status, blocked_reason } = board.session;
  if (blocked_reason != null && (status === "paused" || status === "live")) return "blocked";
  if (status === "setup" || status === "ready") return "notStarted";
  return status;
}

/** Identification row: where am I, what is the draft doing, who am I in it, am I connected. */
export function RoomHeader({ owner, board, gating, presence, connectionState }: Readonly<RoomHeaderProps>) {
  const t = useTranslations("draftRedesign");
  const session = board.session;
  const status = roomStatus(board);
  const seat = seatOf(gating);
  const myTeam = board.teams.find((team) => team.id === gating.myTeamId) ?? null;

  return (
    <div className="mx-auto flex min-h-[52px] max-w-[1720px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 sm:px-6 xl:h-[52px] xl:flex-nowrap xl:py-0">
      <Link
        href={owner.href}
        title={t("room.back")}
        className="-ml-1 inline-flex min-h-11 min-w-0 items-center gap-1.5 rounded-md px-1 text-body text-[color:var(--aqt-fg-muted)] outline-hidden transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] sm:min-h-8"
      >
        <ChevronLeft className="h-4 w-4 shrink-0" aria-hidden />
        <span className="truncate">{owner.name}</span>
      </Link>
      <span aria-hidden className="hidden h-5 w-px bg-[color:var(--aqt-border-2)] sm:block" />
      <h1 className="font-onest text-heading font-semibold">{t("shell.title")}</h1>
      <Badge hue={STATUS_COLOR[status]} voice="label" shape="pill" className="shrink-0">
        <StatusDot />
        {t(`shell.status.${status}`)}
      </Badge>

      {/* No live region on the counters: they tick on their own. Only the
          connection state announces itself. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 sm:ml-auto xl:flex-nowrap">
        {/* Separate facts, separate spans — a middle-dot string is one unreadable
            run for a screen reader and truncates as one block. */}
        <span className="hidden whitespace-nowrap text-caption text-[color:var(--aqt-fg-dim)] md:inline">
          {t(`shell.formatName.${session.format}`)}
        </span>
        <span className="hidden whitespace-nowrap text-caption tabular-nums text-[color:var(--aqt-fg-dim)] md:inline">
          {t("shell.teamsCount", { teams: board.teams.length })}
        </span>
        <span className="hidden whitespace-nowrap text-caption tabular-nums text-[color:var(--aqt-fg-dim)] md:inline">
          {t("shell.pickTime", { seconds: session.pick_time_seconds })}
        </span>
        <span className="whitespace-nowrap text-caption tabular-nums text-[color:var(--aqt-fg-dim)]">
          {t("shell.viewers", { count: viewerCount(presence) })}
        </span>
        <Badge tone="neutral" shape="pill" className="max-w-full">
          <span className="truncate">
            {seat === "captain" || seat === "captain_admin"
              ? t(`shell.seat.${seat}`, { team: myTeam?.name ?? "" })
              : t(`shell.seat.${seat}`)}
          </span>
        </Badge>
        <ConnectionIndicator connectionState={connectionState} />
      </div>
    </div>
  );
}
