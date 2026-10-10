"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { ChevronDown, Crown, Medal, Trophy } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { STATUS_CHIP_CLASS } from "@/components/status/StatusIconBadge";
import { placementClass, TournamentTeamTable } from "@/components/TournamentTeamCard";
import TeamName from "@/components/TeamName";
import { sortTeamPlayers } from "@/lib/player";
import { groupDisplayName, groupHue } from "@/lib/tournament/group";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import type { Registration } from "@/types/registration.types";
import type { Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";

import { declaredHeroes, MARK_CLASS, type TeamRecord } from "../tournamentTeams.model";
import { overviewVariant } from "../tournamentOverview.model";

type MedalPlace = 1 | 2 | 3;

/** The podium chip, drawn like every other status pill but in the placement
 *  medal hues (`--aqt-medal-*`, the site's one source for gold/silver/bronze). */
const MEDAL_PILL: Record<MedalPlace, string> = {
  1: "border-[color:color-mix(in_srgb,var(--aqt-medal-gold)_26%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-medal-gold)_12%,transparent)] text-[color:var(--aqt-medal-gold)]",
  2: "border-[color:color-mix(in_srgb,var(--aqt-medal-silver)_26%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-medal-silver)_12%,transparent)] text-[color:var(--aqt-medal-silver)]",
  3: "border-[color:color-mix(in_srgb,var(--aqt-medal-bronze)_26%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-medal-bronze)_12%,transparent)] text-[color:var(--aqt-medal-bronze)]"
};

/**
 * One team as a collapsed team card that unfolds the card's own roster table.
 * `<details>` and not per-row state, so several teams stay open at once and the
 * browser keeps them open across a re-render.
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
  // A live leader is not on the podium yet: `placement` moves with every result.
  const medal =
    team.placement != null &&
    team.placement <= 3 &&
    overviewVariant(tournament.status) === "completed"
      ? (team.placement as MedalPlace)
      : null;
  const players = sortTeamPlayers(team.players);
  const roster = team.players.map((player) => ({
    ...player,
    heroes: declaredHeroes(player, registrationsByUser.get(player.user_id), heroesMap)
  }));

  return (
    <details className="team-card group">
      <summary className="cursor-pointer list-none rounded-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] [&::-webkit-details-marker]:hidden">
        <div className="tc-header grid grid-cols-[2.75rem_minmax(0,1fr)_auto_auto_1rem] items-center gap-2.5 sm:gap-5">
          <span>
            {team.placement != null ? (
              <span
                className={cn(
                  "placement tabular-nums",
                  medal !== null ? placementClass(medal) : "def"
                )}
              >
                #{team.placement}
              </span>
            ) : null}
          </span>
          <span className="flex min-w-0 flex-col gap-1">
            <span className="flex min-w-0 items-center gap-2">
              <span className="tc-name">
                <TeamName team={team} size="sm" />
              </span>
              {/* Wrapped: `.group-chip` sets its own display, which would
                  outrank a `hidden` utility on the chip itself. */}
              <span className="hidden shrink-0 items-center gap-2 sm:inline-flex">
                {medal !== null ? (
                  <span className={cn(STATUS_CHIP_CLASS, MEDAL_PILL[medal])}>
                    {medal === 1 ? (
                      <Trophy className="size-3 shrink-0" aria-hidden />
                    ) : (
                      <Medal className="size-3 shrink-0" aria-hidden />
                    )}
                    {t(`tournamentDetail.podium.place${medal}`)}
                  </span>
                ) : null}
                {team.group?.name ? (
                  <span
                    className="group-chip"
                    style={{ "--group-hue": groupHue(team.group.name) } as CSSProperties}
                  >
                    {groupDisplayName(team.group.name, t("common.group"))}
                  </span>
                ) : null}
              </span>
            </span>
            {/* The roster at a glance: role glyph + nick, captain crowned. A
                searched battletag shows in full, marked. */}
            <span className="truncate text-caption text-[color:var(--aqt-fg-muted)]">
              {players.map((player) => {
                const matched = needle !== "" && player.name.toLowerCase().includes(needle);
                return (
                  <span
                    key={player.id}
                    className={cn("mr-3 last:mr-0", player.is_substitution && "opacity-60")}
                  >
                    {/* Inline, not flex: an atomic box is clipped whole, so
                        `truncate` could only ellipsize plain text runs. */}
                    <span className="mr-1 inline-block align-[-2px]">
                      <PlayerRoleIcon role={player.role} size={13} decorative />
                    </span>
                    {matched ? (
                      <mark className={MARK_CLASS}>{player.name}</mark>
                    ) : (
                      player.name.split("#")[0]
                    )}
                    {player.user_id === team.captain_id ? (
                      <Crown
                        aria-hidden
                        className="ml-1 inline-block size-3 align-[-1px] text-[color:var(--aqt-amber)]"
                      />
                    ) : null}
                  </span>
                );
              })}
            </span>
          </span>
          <span className="tc-sr">
            <span className="l block">{t("teams.roster.avgSr")}</span>
            <span className="v block">{team.avg_sr.toFixed(0)}</span>
          </span>
          <span className="tc-sr min-w-[2.5rem]">
            <span className="l block">{t("tournamentDetail.teams.record")}</span>
            <span className="v block">{record ? `${record.won}–${record.lost}` : "—"}</span>
          </span>
          <ChevronDown
            className="size-4 text-[color:var(--aqt-fg-faint)] transition-transform group-open:rotate-180"
            aria-hidden
          />
        </div>
      </summary>
      <div className="tc-divider" />
      <TournamentTeamTable
        players={roster}
        tournamentGrid={tournament.division_grid_version}
        captainUserId={team.captain_id}
      />
      <div className="tc-divider" />
      <div className="px-3.5 py-2.5 text-label">
        <Link
          href={`/tournaments/${slug}/matches?team=${team.id}`}
          className="text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]"
        >
          {t("tournamentDetail.teams.teamMatches")}
        </Link>
      </div>
    </details>
  );
};
