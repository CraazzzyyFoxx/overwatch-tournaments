"use client";

import { ArrowRight, Shuffle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { currentRound, orderGrid, pickState, picksAway, type RoundDirection } from "@/lib/draft/room-model";
import { cn } from "@/lib/utils";
import type { DraftBoard } from "@/types/draft.types";

import type { OrderKind } from "./TeamsPanel";

interface DraftOrderGridProps {
  board: DraftBoard;
  /** `roundNumbers(board)`. */
  rounds: readonly number[];
  /** `roundDirection` per entry of `rounds`. */
  directions: readonly RoundDirection[];
  kind: OrderKind;
  myTeamId: number | null;
  followed: ReadonlySet<number>;
  clockColor: string;
}

export function DraftOrderGrid({
  board,
  rounds,
  directions,
  kind,
  myTeamId,
  followed,
  clockColor
}: Readonly<DraftOrderGridProps>) {
  const t = useTranslations("draftRedesign");
  const rows = useMemo(() => orderGrid(board), [board]);
  const playerById = useMemo(() => new Map(board.players.map((player) => [player.id, player])), [board.players]);
  const liveRound = board.current_pick != null ? currentRound(board) : null;
  const onClockId = board.current_pick?.draft_team_id ?? null;
  const gridTemplateColumns = `24px minmax(0,1.1fr) repeat(${Math.max(rounds.length, 1)}, minmax(0,1fr))`;

  return (
    <div className="min-h-0 flex-1 overflow-auto border-t border-[color:var(--aqt-border)]">
      <p className="border-b border-[color:var(--aqt-border)] px-4 py-2.5 text-[13px] leading-[1.45] text-[color:var(--aqt-fg-muted)] [text-wrap:pretty]">
        {t(`teams.order.note.${kind}`)}
      </p>
      <div
        className="sticky top-0 z-[1] grid gap-1 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4 py-2 text-xs font-medium uppercase tracking-[0.08em] text-[color:var(--aqt-fg-faint)]"
        style={{ gridTemplateColumns }}
      >
        <span>#</span>
        <span>{t("teams.col.team")}</span>
        {rounds.map((round, index) => {
          const direction = directions[index];
          return (
            <span
              key={round}
              title={t("teams.order.roundTitle", { n: round, direction })}
              className="flex min-w-0 items-center gap-1 whitespace-nowrap"
              style={{ color: round === liveRound ? "var(--aqt-teal)" : undefined }}
            >
              {t("teams.order.roundShort", { n: round })}
              {direction === "custom" ? (
                <Shuffle aria-hidden className="h-[13px] w-[13px] flex-none" />
              ) : (
                <ArrowRight
                  aria-hidden
                  className={cn("h-[13px] w-[13px] flex-none", direction === "reverse" && "-scale-x-100")}
                />
              )}
              <span className="sr-only">{t("teams.order.roundTitle", { n: round, direction })}</span>
            </span>
          );
        })}
      </div>
      {rows.map(({ team, cells }) => {
        const isMe = team.id === myTeamId;
        return (
          <div
            key={team.id}
            className="grid items-center gap-1 border-b border-[color:var(--aqt-border)] px-4 py-1"
            style={{
              gridTemplateColumns,
              background: isMe ? "var(--aqt-overlay-2)" : "transparent",
              boxShadow:
                team.id === onClockId
                  ? `inset 3px 0 0 ${clockColor}`
                  : followed.has(team.id)
                    ? "inset 3px 0 0 var(--aqt-amber)"
                    : "none"
            }}
          >
            <span className="text-xs tabular-nums text-[color:var(--aqt-fg-faint)]">{team.draft_position}</span>
            <span
              title={team.name}
              className="truncate text-[13px] font-semibold"
              style={{ color: isMe ? "var(--aqt-teal)" : "var(--aqt-fg)" }}
            >
              {isMe ? t("teams.mineName", { name: team.name }) : team.name}
            </span>
            {cells.map((pick, index) => {
              if (pick == null) {
                return (
                  <span key={`none-${rounds[index]}`} className="px-[7px] text-xs text-[color:var(--aqt-fg-faint)]">
                    —
                  </span>
                );
              }
              const state = pickState(pick);
              const player =
                state === "done" && pick.picked_player_id != null ? playerById.get(pick.picked_player_id) : null;
              const tag = player ? (player.battle_tag ?? `#${player.id}`) : null;
              const away = picksAway(board, pick);
              const sub =
                state === "done"
                  ? (tag ?? "—")
                  : state === "current"
                    ? t("teams.order.now")
                    : state === "skipped"
                      ? t("teams.order.skipped")
                      : away != null
                        ? t("teams.order.in", { n: away })
                        : "—";
              const current = state === "current";
              const done = state === "done";
              return (
                <div
                  key={pick.id}
                  title={[
                    t("teams.order.cellTitle", { round: pick.round_no, n: pick.overall_no }),
                    tag,
                    done && pick.target_role ? t(`roles.${pick.target_role}`) : null
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  className="min-w-0 rounded-md px-[7px] py-[3px]"
                  style={{
                    background: current
                      ? "color-mix(in srgb, var(--aqt-teal) 16%, transparent)"
                      : done
                        ? "var(--aqt-overlay-2)"
                        : "transparent",
                    boxShadow: current
                      ? "inset 0 0 0 1px var(--aqt-teal)"
                      : done
                        ? "none"
                        : "inset 0 0 0 1px var(--aqt-border)"
                  }}
                >
                  <div
                    className="text-xs font-semibold tabular-nums"
                    style={{
                      color: current ? "var(--aqt-teal)" : done ? "var(--aqt-fg-muted)" : "var(--aqt-fg)"
                    }}
                  >
                    {t("teams.pickNo", { n: pick.overall_no })}
                  </div>
                  <div
                    className="truncate text-xs"
                    style={{ color: current ? "var(--aqt-teal)" : "var(--aqt-fg-muted)" }}
                  >
                    {sub}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
