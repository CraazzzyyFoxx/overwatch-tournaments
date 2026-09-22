"use client";

import { Check, Clock3 } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { groupPicksByRound } from "@/lib/draft-workspace-model";

interface DraftOrderProps {
  picks: DraftPick[];
  teams: DraftTeam[];
  players: DraftPlayer[];
  compact?: boolean;
  divisionGrid: DivisionGrid;
  /** Unique per mounted instance: the mobile and desktop trees both render an order rail. */
  headingId?: string;
}

export function DraftOrder({
  picks,
  teams,
  players,
  compact = false,
  divisionGrid,
  headingId = "draft-order-heading"
}: Readonly<DraftOrderProps>) {
  const t = useTranslations("draftRedesign");
  const teamById = new Map(teams.map((team) => [team.id, team]));
  const playerById = new Map(players.map((player) => [player.id, player]));
  const groups = groupPicksByRound(picks);
  return (
    <section aria-labelledby={headingId}>
      <div className="flex items-end justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-3">
        <h2 id={headingId} className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{t("draftOrder")}</h2>
        <span className="text-xs text-[color:var(--aqt-fg-muted)]">{picks.length}</span>
      </div>
      <div className={cn("mt-2 space-y-4", compact && "max-h-[520px] overflow-y-auto pr-1")}>
        {groups.map((group) => (
          <div key={group.round}>
            <p className="text-label uppercase tracking-wide text-[color:var(--aqt-fg-faint)]">
              {t("round", { n: group.round })}
            </p>
            <ol className="mt-1 divide-y divide-[color:var(--aqt-border)]">
              {group.picks.map((pick) => {
                const team = teamById.get(pick.draft_team_id);
                const player = pick.picked_player_id == null ? null : playerById.get(pick.picked_player_id);
                const done = pick.status === "completed" || pick.status === "autopicked";
                // The rank the pick froze for the role it was made on, which is
                // what the roster shows too; `effective_rank` is the player's own
                // role and says nothing about an off-role pick.
                const rank = pick.target_rank_value ?? player?.effective_rank ?? null;
                const division = player ? resolveDivisionFromRank(divisionGrid, rank) : null;
                return (
                  <li
                    key={pick.id}
                    className={cn(
                      "grid min-h-12 grid-cols-[2rem_1fr_auto_auto] items-center gap-2 py-2",
                      pick.status === "on_clock" && "text-[color:var(--aqt-teal)]"
                    )}
                  >
                    <span className="text-xs tabular-nums text-[color:var(--aqt-fg-faint)]">{pick.overall_no}</span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium">{player?.battle_tag ?? team?.name ?? t("pending")}</span>
                        {pick.target_role && (
                          <span className="shrink-0">
                            <PlayerRoleIcon
                              role={getRoleIconName(pick.target_role)}
                              size={16}
                              color={ROLE_ACCENT[pick.target_role]}
                            />
                          </span>
                        )}
                      </span>
                      <span className="flex min-w-0 items-center gap-1">
                        <span className="truncate text-xs text-[color:var(--aqt-fg-muted)]">{team?.name ?? t("unknownTeam")}</span>
                        {/* How the pick was resolved, when it was not simply the
                            captain choosing in time. */}
                        {done && pick.is_autopick && <PickBadge>{t("badge.auto")}</PickBadge>}
                        {done && pick.is_admin_override && <PickBadge>{t("badge.override")}</PickBadge>}
                        {done && pick.overtime_started_at != null && <PickBadge>{t("badge.overtime")}</PickBadge>}
                      </span>
                    </span>
                    {division != null ? (
                      <DivisionIcon
                        division={division}
                        tournamentGrid={divisionGrid}
                        width={24}
                        height={24}
                        className="mx-auto h-6 w-6 object-contain"
                      />
                    ) : (
                      <span />
                    )}
                    {done ? (
                      <Check className="h-4 w-4 text-[color:var(--aqt-support)]" role="img" aria-label={t("pickDone")} />
                    ) : pick.status === "on_clock" ? (
                      <Clock3 className="h-4 w-4" role="img" aria-label={t("onTheClock")} />
                    ) : (
                      <span className="inline-flex items-center">
                        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-fg-faint)]" />
                        <span className="sr-only">{t("pending")}</span>
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}

/** How a completed pick was resolved: autopick, admin override, overtime. */
function PickBadge({ children }: Readonly<{ children: string }>) {
  return (
    <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
      {children}
    </span>
  );
}
