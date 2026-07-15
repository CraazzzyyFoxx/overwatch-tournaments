"use client";

import { useTranslations } from "next-intl";

import type { DraftBoard } from "@/types/draft.types";

import { CurrentPick } from "./CurrentPick";
import { DraftEventFeed } from "./DraftEventFeed";
import { DraftOrder } from "./DraftOrder";
import { TeamRosters } from "./TeamRosters";

interface SpectatorDraftWorkspaceProps {
  board: DraftBoard;
}

export function SpectatorDraftWorkspace({ board }: SpectatorDraftWorkspaceProps) {
  const t = useTranslations("draftRedesign");
  const showCurrentPick =
    board.current_pick != null ||
    board.session.status === "live" ||
    board.session.status === "paused";
  return (
    <div className="space-y-6">
      {showCurrentPick ? <CurrentPick board={board} /> : null}
      <p className="max-w-3xl border-l-2 border-[color:var(--aqt-teal)] pl-4 text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
        {board.session.status === "completed" ? t("spectatorCompleted") : t("spectatorReadOnly")}
      </p>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <main className="min-w-0">
          <TeamRosters teams={board.teams} players={board.players} />
        </main>
        <aside className="space-y-8 border-t border-[color:var(--aqt-border)] pt-6 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
          <DraftOrder picks={board.picks} teams={board.teams} players={board.players} compact />
          <DraftEventFeed picks={board.picks} teams={board.teams} players={board.players} />
        </aside>
      </div>
    </div>
  );
}
