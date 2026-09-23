"use client";

import { useTranslations } from "next-intl";

import { usePickCountdown } from "@/hooks/usePickCountdown";
import type { DraftGating } from "@/lib/draft/logic";
import { turnsUntil, type TeamView } from "@/lib/draft/room-model";
import type { DraftBoard } from "@/types/draft.types";

/** The acting team is the viewer's own and it is on the clock. */
export function isMyTurnFor(gating: DraftGating, actingTeam: TeamView | null): boolean {
  return gating.isMyPick && actingTeam != null && actingTeam.team.id === gating.myTeamId;
}

export function clockColor(board: DraftBoard, myTurn: boolean, overtime: boolean): string {
  if (board.session.status === "paused") return "var(--aqt-amber)";
  if (overtime) return "var(--aqt-rose)";
  return myTurn ? "var(--aqt-teal)" : "var(--aqt-fg)";
}

/** Teal while the viewer is on the clock, amber while an organizer is replacing a captain's pick. */
export function actionBorder(board: DraftBoard, myTurn: boolean, overrideMode: boolean): string {
  if (myTurn && board.session.status !== "paused") return "var(--aqt-teal)";
  if (overrideMode) return "color-mix(in srgb, var(--aqt-amber) 60%, transparent)";
  return "var(--aqt-border-2)";
}

interface PickPillProps {
  board: DraftBoard;
  gating: DraftGating;
  actingTeam: TeamView | null;
  overrideMode: boolean;
}

/** The collapsed floating layer: whose turn, the clock, and what a click on the pool does. */
export function PickPill({ board, gating, actingTeam, overrideMode }: Readonly<PickPillProps>) {
  const t = useTranslations("draftRedesign");
  const pick = board.current_pick;
  const countdown = usePickCountdown(pick, board.session.status === "paused");

  if (!actingTeam) return null;

  const myTurn = isMyTurnFor(gating, actingTeam);
  const clockTeam = board.teams.find((team) => team.id === pick?.draft_team_id) ?? null;
  const myIn = gating.myTeamId != null ? turnsUntil(board, gating.myTeamId) : null;
  const clockTeamName = clockTeam?.name ?? "—";

  const label = overrideMode
    ? t("island.pill.override", { team: actingTeam.team.name })
    : myTurn
      ? t("yourTurn")
      : myIn != null && myIn > 0
        ? t("island.pill.turnMineIn", { team: clockTeamName, n: myIn })
        : t("island.pill.turn", { team: clockTeamName });
  const hint = overrideMode
    ? t("island.pill.hintOverride")
    : myTurn
      ? t("island.pill.hintMine")
      : t("island.pill.hintPrepare");

  return (
    <div
      role="status"
      // Phones: the chat launcher owns the bottom-right corner, so the pill floats above it.
      className="mx-auto flex h-12 w-fit max-w-full items-center gap-3 whitespace-nowrap rounded-full border bg-[color:var(--aqt-card-2)] px-5 shadow-[0_18px_50px_rgb(0_0_0/0.45)] max-sm:mb-[4.5rem]"
      style={{ borderColor: actionBorder(board, myTurn, overrideMode) }}
    >
      {/* Ticks every second: kept out of the live region so it is not announced on each tick. */}
      <span
        aria-hidden
        className="font-onest text-[17px] font-bold tabular-nums"
        style={{ color: clockColor(board, myTurn, countdown.overtime) }}
      >
        {countdown.text ?? "—"}
      </span>
      <span aria-hidden className="h-[22px] w-px bg-[color:var(--aqt-border-2)]" />
      <span
        className="text-[15px] font-semibold"
        style={{
          color: overrideMode ? "var(--aqt-amber)" : myTurn ? "var(--aqt-teal)" : "var(--aqt-fg-muted)"
        }}
      >
        {label}
      </span>
      <span className="hidden min-w-0 truncate text-sm text-[color:var(--aqt-fg-muted)] sm:inline">{hint}</span>
    </div>
  );
}
