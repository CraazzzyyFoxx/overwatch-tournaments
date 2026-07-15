"use client";

import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { HeroCoord } from "@/components/site/PageHero";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPlayer, DraftRole, DraftTeam } from "@/types/draft.types";

import { buildRosterByTeam } from "../_lib/draft-workspace-model";

interface TeamRostersProps {
  teams: DraftTeam[];
  players: DraftPlayer[];
  myTeamId?: number | null;
  focusTeamOnly?: boolean;
}

export function TeamRosters({ teams, players, myTeamId = null, focusTeamOnly = false }: TeamRostersProps) {
  const t = useTranslations("draftRedesign");
  const rosters = buildRosterByTeam(players);
  const visibleTeams = focusTeamOnly && myTeamId != null
    ? teams.filter((team) => team.id === myTeamId)
    : [...teams].sort((left, right) => left.draft_position - right.draft_position);

  return (
    <section aria-labelledby="team-rosters-heading">
      <div className="border-b border-[color:var(--aqt-border)] pb-3">
        <HeroCoord>{t("rosterCoordinate")}</HeroCoord>
        <h2 id="team-rosters-heading" className="mt-1 font-onest text-lg font-semibold">
          {focusTeamOnly ? t("myTeam") : t("teamRosters")}
        </h2>
      </div>
      <div className="mt-4 grid gap-x-8 gap-y-6 md:grid-cols-2">
        {visibleTeams.map((team) => {
          const roster = rosters.get(team.id) ?? [];
          return (
            <article key={team.id} className={cn("min-w-0", team.id === myTeamId && "border-l-2 border-[color:var(--aqt-teal)] pl-4") }>
              <div className="flex items-center justify-between gap-3">
                <h3 className="truncate font-onest font-semibold">{team.name}</h3>
                <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">#{team.draft_position}</span>
              </div>
              <div className="mt-2 divide-y divide-[color:var(--aqt-border)]">
                {roster.map((player) => (
                  <div key={player.id} className="flex min-h-11 items-center gap-3 py-2 text-sm">
                    {player.is_captain ? <Crown className="h-4 w-4 text-[color:var(--aqt-warm)]" /> : <PlayerRoleIcon role={getRoleIconName(player.primary_role as DraftRole)} size={16} />}
                    <span className="min-w-0 flex-1 truncate">{player.battle_tag ?? `#${player.id}`}</span>
                    <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">{player.rank_value ?? "—"}</span>
                  </div>
                ))}
                {roster.length === 0 && <p className="py-4 text-sm text-[color:var(--aqt-fg-muted)]">{t("emptyRoster")}</p>}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

