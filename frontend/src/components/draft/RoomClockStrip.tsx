"use client";

import type { ReactNode } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import type { DraftGating } from "@/lib/draft/logic";
import {
  currentRound,
  lastResolvedPick,
  nextPicks,
  pickState,
  remainingPicks,
  roundDirection,
  roundPicks,
  turnsUntil
} from "@/lib/draft/room-model";
import type { DraftViewParams } from "@/lib/draft/workspace-model";
import { getRoleIconName } from "@/lib/roster/roles";
import type { DraftBoard, DraftPick, DraftTeam } from "@/types/draft.types";

import { DraftClockRing } from "./DraftClockRing";

interface RoomClockStripProps {
  board: DraftBoard;
  gating: DraftGating;
  followed: ReadonlySet<number>;
  onlineCaptainIds: ReadonlySet<number>;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
}

/** Who is picking, how far the draft is, what comes next — the room's one clock. */
export function RoomClockStrip({
  board,
  gating,
  followed,
  onlineCaptainIds,
  onViewParamsChange
}: Readonly<RoomClockStripProps>) {
  const t = useTranslations("draftRedesign");
  const tClock = useTranslations("draft.clock");
  const session = board.session;
  const current = board.current_pick;
  const done = session.status === "completed";
  const cancelled = session.status === "cancelled";
  const notStarted = session.status === "setup" || session.status === "ready";
  const paused = session.status === "paused";
  const teamById = new Map(board.teams.map((team) => [team.id, team]));
  const playerById = new Map(board.players.map((player) => [player.id, player]));
  const teamName = (id: number) => teamById.get(id)?.name ?? t("unknownTeam");

  // Before the start nobody is on the clock yet; the strip still names who opens.
  const headPick = current ?? (notStarted ? (remainingPicks(board)[0] ?? null) : null);
  const clockTeam: DraftTeam | null = headPick ? (teamById.get(headPick.draft_team_id) ?? null) : null;
  const myTeamId = gating.myTeamId;
  const isMyTurn = current != null && myTeamId != null && current.draft_team_id === myTeamId;
  const clockColor =
    done || cancelled ? "var(--aqt-status-finished)" : isMyTurn ? "var(--aqt-teal)" : "var(--aqt-fg)";

  const captain = clockTeam
    ? board.players.find((player) => player.is_captain && player.drafted_by_team_id === clockTeam.id)
    : undefined;
  const captainOnline =
    clockTeam?.captain_auth_user_id != null && onlineCaptainIds.has(clockTeam.captain_auth_user_id);

  const totalPicks = board.picks.length;
  const round = currentRound(board);
  const ticks = roundPicks(board, round);
  const doneInRound = ticks.filter((pick) => pickState(pick) === "done").length;
  const last = lastResolvedPick(board);
  const lastPlayer = last?.picked_player_id != null ? playerById.get(last.picked_player_id) : undefined;

  const myIn = myTeamId != null && !done && !cancelled ? turnsUntil(board, myTeamId) : null;
  const upcoming = nextPicks(board, 3).map((pick) =>
    pick.draft_team_id === myTeamId
      ? t("shell.strip.nextMine", { team: teamName(pick.draft_team_id) })
      : teamName(pick.draft_team_id)
  );
  // Separate facts, separate spans: "A · B" is one string a screen reader reads
  // as a sentence and a narrow viewport truncates in the middle of.
  const nextParts: ReactNode[] = [];
  if (!done && !cancelled) {
    if (myIn != null && myIn > 0)
      nextParts.push(
        <span key="mine" className="whitespace-nowrap tabular-nums">
          {t("shell.strip.myTurnIn", { count: myIn })}
        </span>
      );
    if (upcoming.length > 0)
      nextParts.push(
        <span key="next" className="min-w-0 truncate">
          {t("shell.strip.next", { teams: upcoming.join(", ") })}
        </span>
      );
    else if (current != null) nextParts.push(<span key="final">{t("shell.strip.finalPick")}</span>);
  }

  // One announcement per pick, not per tick: every part of this text is derived
  // from board state, so React only writes the region when the pick changes.
  const announceParts: string[] = [];
  if (last && lastPlayer)
    announceParts.push(
      t("shell.strip.announceLast", {
        team: teamName(last.draft_team_id),
        player: lastPlayer.battle_tag ?? `#${lastPlayer.id}`
      })
    );
  if (current != null)
    announceParts.push(
      isMyTurn
        ? t("shell.strip.announceMine", { pick: current.overall_no })
        : t("shell.strip.announce", { pick: current.overall_no, team: teamName(current.draft_team_id) })
    );

  const whoLabel = done
    ? t("shell.strip.completed")
    : cancelled
      ? t("shell.strip.cancelled")
      : isMyTurn
        ? t("shell.strip.myTurn")
        : notStarted
          ? t("shell.strip.firstPick")
          : t("shell.strip.picking");
  const whoName = done ? t("shell.strip.picksMade", { count: totalPicks }) : (clockTeam?.name ?? "—");
  // Teams are named after their captain by default: the tag next to the team
  // name only earns its place when it says something the name doesn't.
  const captainTag = captain ? (captain.battle_tag ?? `#${captain.id}`) : null;
  const showCaptainTag = captainTag != null && captainTag !== whoName;

  const tickTone = (pick: DraftPick) => {
    const state = pickState(pick);
    const ring =
      state === "current"
        ? "none"
        : pick.draft_team_id === myTeamId
          ? "inset 0 0 0 1.5px var(--aqt-teal)"
          : followed.has(pick.draft_team_id)
            ? "inset 0 0 0 1.5px var(--aqt-follow)"
            : "none";
    const background =
      state === "current"
        ? paused
          ? "var(--aqt-amber)"
          : pick.overtime_started_at != null
            ? "var(--aqt-live)"
            : clockColor
        : state === "done"
          ? "color-mix(in srgb, var(--aqt-fg-muted) 40%, transparent)"
          : "var(--aqt-overlay-3)";
    return { background, boxShadow: ring };
  };
  const tickTitle = (pick: DraftPick) => {
    const player = pick.picked_player_id != null ? playerById.get(pick.picked_player_id) : undefined;
    return player
      ? t("shell.strip.tickPlayer", {
          pick: pick.overall_no,
          team: teamName(pick.draft_team_id),
          player: player.battle_tag ?? `#${player.id}`
        })
      : t("shell.strip.tick", { pick: pick.overall_no, team: teamName(pick.draft_team_id) });
  };

  return (
    <div className="border-t border-[color:var(--aqt-border)]">
      <div className="mx-auto flex max-w-[1720px] flex-wrap items-center gap-x-[18px] gap-y-3 px-4 py-2.5 sm:px-6">
        {done || cancelled ? (
          // A finished draft has no clock left to run: an empty arc reads as
          // broken, a glyph reads as the state it is.
          <span
            role="img"
            aria-label={done ? tClock("finished") : t("shell.strip.cancelled")}
            className="grid h-[52px] w-[52px] shrink-0 place-items-center rounded-full text-[color:var(--aqt-status-finished)]"
            style={{ boxShadow: "inset 0 0 0 3.5px color-mix(in srgb, var(--aqt-status-finished) 45%, transparent)" }}
          >
            {done ? <Check className="h-6 w-6" aria-hidden /> : <X className="h-6 w-6" aria-hidden />}
          </span>
        ) : (
          <DraftClockRing
            pick={current}
            paused={paused}
            totalSeconds={session.pick_time_seconds}
            overtimeSeconds={session.overtime_seconds}
            color={clockColor}
            size="sm"
            announce={isMyTurn}
          />
        )}
        <div className="min-w-[150px]">
          <p
            className="text-caption font-medium"
            style={{ color: isMyTurn ? "var(--aqt-teal)" : "var(--aqt-fg-muted)" }}
          >
            {whoLabel}
          </p>
          <div className="mt-[3px] flex min-w-0 items-center gap-2.5">
            <span title={whoName} className="min-w-0 truncate font-onest text-title font-bold">
              {whoName}
            </span>
            {!done && !cancelled && captain && (
              <span
                title={captainOnline ? t("shell.strip.captainOnline") : t("shell.strip.captainOffline")}
                className="flex items-center gap-1.5 whitespace-nowrap text-body text-[color:var(--aqt-fg-muted)]"
              >
                <span
                  aria-hidden
                  className="h-[7px] w-[7px] rounded-full"
                  style={
                    captainOnline
                      ? { background: "var(--aqt-positive)" }
                      : { boxShadow: "inset 0 0 0 1.5px var(--aqt-border-3)" }
                  }
                />
                {showCaptainTag && captainTag}
                <span className="sr-only">
                  {captainOnline ? t("shell.strip.captainOnline") : t("shell.strip.captainOffline")}
                </span>
              </span>
            )}
          </div>
        </div>
        <span aria-hidden className="hidden w-px self-stretch bg-[color:var(--aqt-border)] sm:block" />

        <div className="flex min-w-[230px] flex-[1_1_300px] flex-col gap-2">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="whitespace-nowrap text-ui font-semibold tabular-nums">
              {t("shell.strip.pick", {
                pick: done ? totalPicks : (headPick?.overall_no ?? totalPicks),
                total: totalPicks
              })}
            </span>
            <span className="whitespace-nowrap text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
              {t("shell.strip.round", {
                round,
                rounds: session.rounds,
                direction: t(`shell.strip.direction.${roundDirection(board, round)}`)
              })}
            </span>
            <button
              type="button"
              onClick={() => onViewParamsChange({ teams: "order", view: "teams" })}
              className="min-h-11 whitespace-nowrap rounded-sm text-caption font-medium text-[color:var(--aqt-teal)] outline-hidden hover:underline focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] sm:min-h-0"
            >
              {t("shell.strip.allRounds")}
            </button>
            {nextParts.length > 0 && (
              <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-body text-[color:var(--aqt-fg-muted)] sm:ml-auto">
                {nextParts}
              </span>
            )}
          </div>
          {ticks.length > 0 && (
            <div
              role="img"
              aria-label={t("shell.strip.track", { round, done: doneInRound, total: ticks.length })}
              className="flex gap-[3px]"
            >
              {ticks.map((pick) => (
                <span
                  key={pick.id}
                  title={tickTitle(pick)}
                  className="h-2.5 min-w-1 flex-1 rounded-[3px]"
                  style={tickTone(pick)}
                />
              ))}
            </div>
          )}
          {last && lastPlayer && (
            <div className="flex min-w-0 items-center gap-[7px] whitespace-nowrap text-body text-[color:var(--aqt-fg-muted)]">
              <span>{t("shell.strip.lastPick")}</span>
              <span className="truncate">{teamName(last.draft_team_id)}</span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-fg-faint)]" aria-hidden />
              <span className="truncate font-semibold text-[color:var(--aqt-fg)]">
                {lastPlayer.battle_tag ?? `#${lastPlayer.id}`}
              </span>
              {last.target_role && (
                <span title={t(`roles.${last.target_role}`)} className="inline-flex shrink-0">
                  <PlayerRoleIcon role={getRoleIconName(last.target_role)} size={20} decorative />
                  <span className="sr-only">{t(`roles.${last.target_role}`)}</span>
                </span>
              )}
              {last.is_autopick && (
                <span
                  title={t("shell.strip.autoTitle")}
                  className="rounded bg-[color:var(--aqt-overlay-3)] px-1.5 py-px text-label font-medium text-[color:var(--aqt-fg-muted)]"
                >
                  {t("badge.auto")}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
      <p className="sr-only" role="status">
        {announceParts.join(" ")}
      </p>
    </div>
  );
}
