"use client";

import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TeamLogo } from "@/components/TeamName";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import type { Registration } from "@/types/registration.types";
import type { Player, Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";
import { formatSubRoleLabel, getPlayerSlug, sortTeamPlayers } from "@/lib/player";

import {
  declaredHeroes,
  listGrid,
  MARK_CLASS,
  rosterGrid,
  rosterSlots,
  type TeamRecord
} from "../tournamentTeams.model";

const TeamRosterRow = ({
  player,
  tournament,
  needle,
  heroes,
  withHeroes
}: {
  player: Player;
  tournament: Tournament;
  needle: string;
  heroes: Hero[];
  withHeroes: boolean;
}) => {
  const t = useTranslations();
  const workspaceGrid = useDivisionGrid();
  const grid = tournament.division_grid_version ?? workspaceGrid;
  const name = player.name;
  const role = normalizePlayerRole(player.role);
  const notes = [
    formatSubRoleLabel(player.sub_role),
    // "New role" is a fact about a role: a flex player has none to be new to,
    // and in a flex tournament the flag is set on everyone.
    player.is_newcomer_role && role !== "Flex" ? t("teams.roster.newcomerRole") : null,
    player.is_newcomer ? t("teams.roster.newcomer") : null
  ].filter(Boolean);

  return (
    <div className={cn(rosterGrid(withHeroes), "py-1")}>
      <span className="aqt-tnum text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
        {role}
      </span>
      <Link
        href={`/users/${getPlayerSlug(name)}`}
        className="truncate hover:text-[color:var(--aqt-teal)]"
        title={name}
      >
        {needle !== "" && name.toLowerCase().includes(needle) ? (
          <mark className={MARK_CLASS}>{name}</mark>
        ) : (
          name
        )}
      </Link>
      {/* Division as its icon (the tier name in `title`) beside the SR — one
          cell, so neither can run into the other. */}
      <span
        className="flex items-center gap-1.5"
        title={getDivisionLabel(grid, player.division) ?? undefined}
      >
        <DivisionIcon
          division={player.division}
          width={18}
          height={18}
          tournamentGrid={tournament.division_grid_version}
        />
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">{player.rank}</span>
      </span>
      {withHeroes ? (
        heroes.length > 0 ? (
          <HeroStrip
            heroes={heroes}
            size={18}
            limit={3}
            className="justify-self-start"
          />
        ) : (
          <span className="text-[color:var(--aqt-fg-dim)]">—</span>
        )
      ) : null}
      <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
        {notes.join(" · ")}
      </span>
    </div>
  );
};

/**
 * One team as a collapsed row that unfolds its roster. `<details>` and not
 * per-row state, so several teams stay open at once and the browser keeps them
 * open across a re-render.
 */
export const TeamListRow = ({
  team,
  tournament,
  slug,
  record,
  needle,
  registrationsByUser,
  heroesMap
}: {
  team: Team;
  tournament: Tournament;
  slug: string;
  record: TeamRecord | null | undefined;
  needle: string;
  registrationsByUser: Map<number, Registration>;
  heroesMap: Map<string, Hero>;
}) => {
  const t = useTranslations();
  const withRoles = tournament.roster_shape?.has_role_slots ?? true;
  const slots = withRoles ? rosterSlots(tournament, team) : [];
  const subtitle = [
    team.group?.name ? t("teams.groupLabel", { name: team.group.name }) : null,
    team.placement === 1 ? t("tournamentDetail.teams.champion") : null
  ].filter(Boolean);
  const roster = sortTeamPlayers(team.players).map((player) => ({
    player,
    heroes: declaredHeroes(player, registrationsByUser.get(player.user_id), heroesMap)
  }));
  // A column of dashes says nothing: it exists only when someone declared heroes.
  const withHeroes = roster.some((entry) => entry.heroes.length > 0);

  return (
    <details className="group border-b border-[color:var(--aqt-border)]/60">
      <summary className="cursor-pointer list-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] [&::-webkit-details-marker]:hidden">
        <div className={cn(listGrid(withRoles), "px-2 py-2.5")}>
          <span className="aqt-tnum tabular-nums text-label text-[color:var(--aqt-fg-faint)]">
            {team.placement != null ? `#${team.placement}` : ""}
          </span>
          <span className="inline-flex size-5 items-center justify-center">
            <TeamLogo team={team} size="sm" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-medium" title={team.name}>
              {team.name}
            </span>
            {subtitle.length > 0 ? (
              <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
                {subtitle.join(" · ")}
              </span>
            ) : null}
          </span>
          <span className="aqt-tnum text-[color:var(--aqt-fg-muted)]">{team.avg_sr.toFixed(0)}</span>
          {withRoles ? (
            <span className="hidden items-center gap-0.5 sm:flex">
              {slots.map((slot, index) => (
                <span
                  key={index}
                  title={slot.player?.name ?? undefined}
                  className={cn("inline-flex", slot.player == null && "opacity-40")}
                >
                  <PlayerRoleIcon role={slot.role} size={16} label={slot.player?.name ?? undefined} />
                </span>
              ))}
            </span>
          ) : null}
          <span className="aqt-tnum text-right text-[color:var(--aqt-fg-muted)]">
            {record ? `${record.won}–${record.lost}` : "—"}
          </span>
          <span className="flex justify-end">
            <ChevronDown
              className="size-3.5 text-[color:var(--aqt-fg-faint)] transition-transform group-open:rotate-180"
              aria-hidden
            />
          </span>
        </div>
      </summary>
      <div className="mb-2 ml-2 mr-2 border-l-2 border-[color:var(--aqt-border)] py-1 pl-3 text-caption sm:ml-[4.75rem]">
        <div className={cn(rosterGrid(withHeroes), "py-0.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]")}>
          <span>{t("teams.roster.role")}</span>
          <span>{t("teams.roster.battleTag")}</span>
          <span>
            {t("teams.roster.division")} · {t("tournamentDetail.teams.sr")}
          </span>
          {withHeroes ? <span>{t("common.heroes")}</span> : null}
          <span />
        </div>
        {roster.map(({ player, heroes }) => (
          <TeamRosterRow
            key={player.id}
            player={player}
            tournament={tournament}
            needle={needle}
            heroes={heroes}
            withHeroes={withHeroes}
          />
        ))}
        <div className="mt-1.5 flex flex-wrap gap-3 border-t border-[color:var(--aqt-border)]/60 pt-1.5 text-label">
          <Link
            href={`/tournaments/${slug}/matches?team=${team.id}`}
            className="text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]"
          >
            {t("tournamentDetail.teams.teamMatches")}
          </Link>
          {/* Wireframe §5 ④ offers "Team profile" only when a team route exists.
              The public site has no team page, so the button is absent rather
              than dead. */}
        </div>
      </div>
    </details>
  );
};
