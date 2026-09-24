"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { formatClock, usePickCountdown } from "@/hooks/usePickCountdown";
import type { DraftGating } from "@/lib/draft/logic";
import type { DraftAutopickPreview, DraftBoard } from "@/types/draft.types";

interface RoomBannerProps {
  board: DraftBoard;
  gating: DraftGating;
  /** My team's autopick preview (queue response); null when I am not on the clock. */
  autopickPreview: DraftAutopickPreview | null;
}

const BLOCKED_REASONS = ["role_shortage", "order_recalculated"] as const;
type BlockedReason = (typeof BLOCKED_REASONS)[number];

function blockedReasonKey(reason: string): BlockedReason | "other" {
  return (BLOCKED_REASONS as readonly string[]).includes(reason) ? (reason as BlockedReason) : "other";
}

/** One line under the strip for the states that change what anyone in the room can do. */
export function RoomBanner({ board, gating, autopickPreview }: Readonly<RoomBannerProps>) {
  const t = useTranslations("draftRedesign");
  const { session, current_pick: current } = board;
  const paused = session.status === "paused";
  const { ms } = usePickCountdown(current, paused);
  // Plain m:ss here: the sentence already says it is overtime, "+0:12" would read as a sum.
  const time = ms == null ? "—" : formatClock(ms, false);
  const clockTeam = current ? board.teams.find((team) => team.id === current.draft_team_id) : undefined;
  const isMyTurn = current != null && gating.myTeamId != null && current.draft_team_id === gating.myTeamId;

  let color = "var(--aqt-amber)";
  let text: string | null = null;
  let adminLink = false;
  /** The overtime line re-renders every second; the ring already announces overtime and its thresholds. */
  let ticking = false;

  if (session.blocked_reason != null && (paused || session.status === "live")) {
    color = "var(--aqt-rose)";
    text = t(`shell.banner.blocked.${blockedReasonKey(session.blocked_reason)}`);
    adminLink = gating.isAdmin;
  } else if (paused) {
    text = gating.isCaptain ? t("shell.banner.pausedCaptain") : t("shell.banner.pausedSpectator");
  } else if (session.status === "live" && current?.overtime_started_at != null) {
    color = "var(--aqt-rose)";
    ticking = true;
    if (isMyTurn) {
      const player =
        autopickPreview != null ? board.players.find((entry) => entry.id === autopickPreview.player_id) : undefined;
      const tag = player ? (player.battle_tag ?? `#${player.id}`) : null;
      text =
        tag == null
          ? t("shell.banner.overtimeMine", { time })
          : autopickPreview?.source === "queue"
            ? t("shell.banner.overtimeQueue", { time, player: tag })
            : t("shell.banner.overtimeFit", { time, player: tag });
    } else {
      text = t("shell.banner.overtimeOther", { time, team: clockTeam?.name ?? t("unknownTeam") });
    }
  } else if (session.status === "completed") {
    color = "var(--aqt-teal)";
    text = t("shell.banner.finished", { picks: board.picks.length, teams: board.teams.length });
  } else if (session.status === "setup" || session.status === "ready") {
    color = "var(--aqt-fg-muted)";
    text = t("shell.banner.notStarted");
  } else if (session.status === "cancelled") {
    color = "var(--aqt-fg-faint)";
    text = t("shell.banner.cancelled");
  }

  // The region stays mounted so a state that appears later is announced.
  return (
    <div
      role="status"
      aria-live={ticking ? "off" : "polite"}
      className={text == null ? "contents" : "border-t"}
      style={
        text == null
          ? undefined
          : { borderColor: color, background: `color-mix(in srgb, ${color} 10%, transparent)` }
      }
    >
      {text != null && (
        <p
          className="mx-auto flex max-w-[1720px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm font-medium sm:px-6"
          style={{ color }}
        >
          <span>{text}</span>
          {adminLink && (
            <Link
              href={`/admin/tournaments/${session.tournament_id}/teams/draft`}
              className="inline-flex min-h-11 items-center rounded-sm underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] sm:min-h-0"
            >
              {t("shell.banner.blockedAdminLink")}
            </Link>
          )}
        </p>
      )}
    </div>
  );
}
