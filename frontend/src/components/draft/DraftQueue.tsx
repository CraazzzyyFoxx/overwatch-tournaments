"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { usePickCountdown } from "@/hooks/usePickCountdown";
import { DRAFT_ROLES, pickHistory, type TeamView } from "@/lib/draft/room-model";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import type { DraftBoard, DraftPick } from "@/types/draft.types";

interface DraftQueueProps {
  board: DraftBoard;
  teamViews: ReadonlyMap<number, TeamView>;
  /** `remainingPicks(board)`, the one on the clock first. */
  remaining: readonly DraftPick[];
  myTeamId: number | null;
  clockColor: string;
}

const UPCOMING_COUNT = 10;
const HISTORY_COUNT = 12;

const headingClass =
  "m-0 flex items-center gap-2 px-[18px] pb-2 text-xs font-medium uppercase tracking-[0.08em] text-[color:var(--aqt-fg-faint)]";

export function DraftQueue({ board, teamViews, remaining, myTeamId, clockColor }: Readonly<DraftQueueProps>) {
  const t = useTranslations("draftRedesign");
  const [showAll, setShowAll] = useState(false);
  const countdown = usePickCountdown(board.current_pick, board.session.status === "paused");
  const history = useMemo(() => pickHistory(board), [board]);
  const playerById = useMemo(() => new Map(board.players.map((player) => [player.id, player])), [board.players]);
  const shownHistory = showAll ? history : history.slice(0, HISTORY_COUNT);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto border-t border-[color:var(--aqt-border)]">
      <h3 className={`${headingClass} pt-4`}>{t("teams.queue.upcoming")}</h3>
      {remaining.length === 0 && (
        <p className="px-[18px] py-3 text-sm text-[color:var(--aqt-fg-muted)]">{t("teams.queue.empty")}</p>
      )}
      <ol>
        {remaining.slice(0, UPCOMING_COUNT).map((pick, index) => {
          const view = teamViews.get(pick.draft_team_id);
          const mine = pick.draft_team_id === myTeamId;
          const isCur = pick.status === "on_clock";
          // A flex slot seats any role, so it reads as "any role" rather than a list of three.
          const needs = view
            ? [
                ...DRAFT_ROLES.filter((role) => (view.openRoles.get(role) ?? 0) > 0).map((role) => t(`roles.${role}`)),
                ...(view.openFlex > 0 ? [t("teams.anyRole")] : [])
              ]
            : [];
          const name = view?.team.name ?? t("unknownTeam");
          return (
            <li
              key={pick.id}
              className="grid grid-cols-[52px_minmax(0,1fr)_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-[18px] py-2.5"
              style={{
                background: isCur ? "color-mix(in srgb, var(--aqt-teal) 8%, transparent)" : "transparent",
                boxShadow: isCur
                  ? `inset 3px 0 0 ${clockColor}`
                  : mine
                    ? "inset 3px 0 0 color-mix(in srgb, var(--aqt-teal) 50%, transparent)"
                    : "none"
              }}
            >
              <span className="text-sm font-semibold tabular-nums text-[color:var(--aqt-fg-faint)]">
                {t("teams.pickNo", { n: pick.overall_no })}
              </span>
              <div className="min-w-0">
                <div className="truncate text-[15px] font-semibold" title={name}>
                  {mine ? t("teams.mineName", { name }) : name}
                </div>
                <div className="truncate text-[13px] text-[color:var(--aqt-fg-muted)]">
                  {t("teams.queue.sub", { round: pick.round_no, needs: needs.length > 0 ? needs.join(", ") : "—" })}
                </div>
              </div>
              <span
                className="whitespace-nowrap text-sm font-semibold tabular-nums"
                style={{
                  color: isCur ? clockColor : mine ? "var(--aqt-teal)" : "var(--aqt-fg-muted)"
                }}
              >
                {isCur ? (countdown.text ?? t("teams.queue.now")) : index === 0 ? t("teams.queue.first") : t("teams.queue.in", { n: index })}
              </span>
            </li>
          );
        })}
      </ol>

      <h3 className={`${headingClass} pt-5`}>
        {t("teams.history.title")}
        <span className="tabular-nums tracking-normal">{history.length}</span>
      </h3>
      {history.length === 0 && (
        <p className="px-[18px] py-3 text-sm text-[color:var(--aqt-fg-muted)]">{t("teams.history.empty")}</p>
      )}
      <ol>
        {shownHistory.map((pick) => {
          const player = pick.picked_player_id == null ? null : playerById.get(pick.picked_player_id);
          const tag = player?.battle_tag ?? (player ? `#${player.id}` : "—");
          return (
            <li
              key={pick.id}
              className="grid grid-cols-[52px_minmax(0,1fr)_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-[18px] py-[9px]"
            >
              <span className="text-sm tabular-nums text-[color:var(--aqt-fg-faint)]">
                {t("teams.pickNo", { n: pick.overall_no })}
              </span>
              <div className="flex min-w-0 items-center gap-[7px] text-sm">
                <span className="max-w-[45%] truncate text-[color:var(--aqt-fg-muted)]">
                  {teamViews.get(pick.draft_team_id)?.team.name ?? t("unknownTeam")}
                </span>
                <ArrowRight aria-hidden className="h-[13px] w-[13px] flex-none text-[color:var(--aqt-fg-faint)]" />
                <span className="truncate font-semibold">{tag}</span>
                {pick.target_role && (
                  <span className="flex-none" title={t(`roles.${pick.target_role}`)}>
                    <PlayerRoleIcon
                      role={getRoleIconName(pick.target_role)}
                      size={18}
                      color={ROLE_ACCENT[pick.target_role]}
                    />
                  </span>
                )}
              </div>
              <span className="flex gap-1">
                {pick.is_autopick && <PickBadge title={t("teams.history.autoTitle")}>{t("badge.auto")}</PickBadge>}
                {pick.is_admin_override && (
                  <PickBadge title={t("teams.history.overrideTitle")}>{t("badge.override")}</PickBadge>
                )}
                {pick.overtime_started_at != null && (
                  <PickBadge title={t("teams.history.overtimeTitle")}>{t("badge.overtime")}</PickBadge>
                )}
              </span>
            </li>
          );
        })}
      </ol>
      {history.length > HISTORY_COUNT && (
        <div className="px-[18px] py-3">
          <button
            type="button"
            aria-expanded={showAll}
            onClick={() => setShowAll((value) => !value)}
            className="rounded text-sm font-medium text-[color:var(--aqt-teal)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] max-sm:min-h-11"
          >
            {showAll ? t("teams.history.collapse") : t("teams.history.showAll", { count: history.length })}
          </button>
        </div>
      )}
    </div>
  );
}

/** How a resolved pick was made when it was not simply the captain choosing in time. */
function PickBadge({ title, children }: Readonly<{ title: string; children: string }>) {
  return (
    <span
      title={title}
      className="rounded px-1.5 py-px text-xs font-semibold uppercase tracking-[0.08em] text-[color:var(--aqt-amber)] [background:var(--aqt-overlay-3)]"
    >
      {children}
    </span>
  );
}
