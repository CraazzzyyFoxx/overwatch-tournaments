"use client";

import { Check, Clock3 } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPick, DraftPlayer, DraftRole, DraftTeam } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { groupPicksByRound } from "../_lib/draft-workspace-model";

const ROLE_ACCENT: Record<DraftRole, string> = {
  tank: "var(--aqt-tank)",
  dps: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

interface DraftOrderProps {
  picks: DraftPick[];
  teams: DraftTeam[];
  players: DraftPlayer[];
  compact?: boolean;
  divisionGrid: DivisionGrid;
}

export function DraftOrder({ picks, teams, players, compact = false, divisionGrid }: DraftOrderProps) {
  const t = useTranslations("draftRedesign");
  const teamById = new Map(teams.map((team) => [team.id, team]));
  const playerById = new Map(players.map((player) => [player.id, player]));
  const groups = groupPicksByRound(picks);
  return (
    <section aria-labelledby="draft-order-heading">
      <div className="flex items-end justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-3">
        <h2 id="draft-order-heading" className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{t("draftOrder")}</h2>
        <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">{picks.length}</span>
      </div>
      <div className={cn("mt-2 space-y-4", compact && "max-h-[520px] overflow-y-auto pr-1")}>
        {groups.map((group) => (
          <div key={group.round}>
            <p className="font-mono text-[11px] uppercase tracking-wide text-[color:var(--aqt-fg-faint)]">
              {t("round", { n: group.round })}
            </p>
            <ol className="mt-1 divide-y divide-[color:var(--aqt-border)]">
              {group.picks.map((pick) => {
                const team = teamById.get(pick.draft_team_id);
                const player = pick.picked_player_id == null ? null : playerById.get(pick.picked_player_id);
                const done = pick.status === "completed" || pick.status === "autopicked";
                const division = player ? resolveDivisionFromRank(divisionGrid, player.rank_value) : null;
                return (
                  <li
                    key={pick.id}
                    className={cn(
                      "grid min-h-12 grid-cols-[2rem_1fr_auto_auto] items-center gap-2 py-2",
                      pick.status === "on_clock" && "text-[color:var(--aqt-teal)]"
                    )}
                  >
                    <span className="font-mono text-xs tabular-nums text-[color:var(--aqt-fg-faint)]">{pick.overall_no}</span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium">{player?.battle_tag ?? team?.name ?? t("pending")}</span>
                        {pick.target_role && (
                          <span
                            className="inline-flex shrink-0 items-center gap-1 rounded border border-[color:var(--aqt-border-2)] px-1 py-0.5 text-[10px] uppercase tracking-wide"
                            style={{ color: ROLE_ACCENT[pick.target_role] }}
                          >
                            <PlayerRoleIcon role={getRoleIconName(pick.target_role)} size={10} color={ROLE_ACCENT[pick.target_role]} />
                            {t(`roles.${pick.target_role}`)}
                          </span>
                        )}
                      </span>
                      <span className="block truncate text-xs text-[color:var(--aqt-fg-muted)]">{team?.name ?? t("unknownTeam")}</span>
                    </span>
                    {division != null ? (
                      <PlayerDivisionIcon
                        division={division}
                        tournamentGrid={divisionGrid}
                        width={18}
                        height={18}
                        className="h-[18px] w-[18px] object-contain"
                      />
                    ) : (
                      <span />
                    )}
                    {done ? (
                      <Check className="h-4 w-4 text-[color:var(--aqt-support)]" />
                    ) : pick.status === "on_clock" ? (
                      <Clock3 className="h-4 w-4" />
                    ) : (
                      <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-fg-faint)]" aria-label={t("pending")} />
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
