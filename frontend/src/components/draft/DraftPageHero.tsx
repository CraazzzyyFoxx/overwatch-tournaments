"use client";

import { ArrowLeft, Eye, Pause, Radio, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftPresenceState } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { Tournament } from "@/types/tournament.types";

interface DraftPageHeroProps {
  tournament: Tournament;
  board: DraftBoard;
  presence: DraftPresenceState;
  connectionState: RealtimeConnectionState;
}

/**
 * Identification only: where am I, what is the draft doing, am I connected.
 * Everything about the current turn lives in `CurrentPick`, captain presence
 * in the `TeamRosters` cards, and pool size in the pool heading — repeating
 * any of it here is what made the old header 380px tall on a phone.
 */
export function DraftPageHero({
  tournament,
  board,
  presence,
  connectionState
}: Readonly<DraftPageHeroProps>) {
  const t = useTranslations("draftRedesign");
  const session = board.session;
  const isLive = session.status === "live";
  const StateIcon = session.blocked_reason
    ? ShieldAlert
    : session.status === "paused"
      ? Pause
      : Radio;

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-2 py-2 sm:px-3">
      <Link
        href={`/tournaments/${tournament.id}`}
        aria-label={t("room.back")}
        className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-card-2)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
      >
        <ArrowLeft className="h-4 w-4" />
      </Link>
      <h1 className="min-w-0 truncate font-onest text-lg font-semibold leading-tight tracking-[-0.01em] sm:text-xl">
        {tournament.name}
      </h1>
      <span
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-label font-bold uppercase tracking-label",
          isLive
            ? "border-[color:var(--aqt-teal)]/35 bg-[color:var(--aqt-teal)]/12 text-[color:var(--aqt-teal)]"
            : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-amber)]"
        )}
      >
        {isLive ? (
          <span
            aria-hidden
            className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-teal)] animate-pulse motion-reduce:animate-none"
          />
        ) : (
          <StateIcon className="h-3.5 w-3.5" aria-hidden />
        )}
        {t(`status.${session.status}`)}
      </span>

      {/* No live region: the viewer counter ticks on its own. Only the
          connection state below announces itself. */}
      <div className="ml-auto flex shrink-0 items-center gap-3">
        <span className="inline-flex items-center gap-1.5 text-xs text-[color:var(--aqt-fg-muted)]">
          <Eye className="h-3.5 w-3.5 text-[color:var(--aqt-teal)]" aria-hidden />
          {t("anonymousViewers", { count: presence.anonymous_viewer_count })}
        </span>
        <span aria-hidden className="h-4 w-px bg-[color:var(--aqt-border-2)]" />
        <ConnectionIndicator connectionState={connectionState} />
      </div>
    </header>
  );
}
