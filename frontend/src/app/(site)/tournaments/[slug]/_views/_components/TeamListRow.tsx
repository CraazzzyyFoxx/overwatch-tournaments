"use client";

import Link from "next/link";
import { ArrowRight, ChevronDown, Crown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { RoleOntology } from "@/lib/roster/ontology";
import { useFormatter } from "@/lib/datetime/client";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  TEAM_CARD_CLASS,
  TEAM_CARD_HEADER,
  TEAM_CARD_NAME,
  TeamCardDivider,
  TeamCardMetric,
  TeamPlacement,
  TournamentTeamTable
} from "@/components/TournamentTeamCard";
import TeamName from "@/components/TeamName";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { disclosureChevronClass } from "@/components/ui/chevron";
import { sortTeamPlayers, splitHandle } from "@/lib/player";
import { groupDisplayName, groupHue } from "@/lib/tournament/group";
import { cn } from "@/lib/utils";
import type { CatalogEntityChip } from "@/types/catalog.types";
import type { Registration } from "@/types/registration.types";
import type { Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";

import { declaredHeroes, MARK_CLASS, type TeamRecord } from "../tournamentTeams.model";
import { overviewVariant } from "../tournamentOverview.model";

/**
 * The header row's grid for each set of drawn columns — placement (`p`) and
 * record (`r`) — spelled out whole, because Tailwind only ships classes it
 * can read in the source.
 */
const ROW_COLUMNS = {
  pr: "grid-cols-[2.75rem_minmax(0,1fr)_auto_1rem] sm:grid-cols-[2.75rem_minmax(0,1fr)_auto_auto_1rem]",
  p: "grid-cols-[2.75rem_minmax(0,1fr)_1rem] sm:grid-cols-[2.75rem_minmax(0,1fr)_auto_1rem]",
  r: "grid-cols-[minmax(0,1fr)_auto_1rem] sm:grid-cols-[minmax(0,1fr)_auto_auto_1rem]",
  none: "grid-cols-[minmax(0,1fr)_1rem] sm:grid-cols-[minmax(0,1fr)_auto_1rem]"
} as const;

/**
 * One team as a collapsed team card that unfolds the card's own roster table.
 * `<details>` and not per-row state, so several teams stay open at once and the
 * browser keeps them open across a re-render.
 *
 * `showGroup`: the visible rows span several groups, so the group colour tells
 * them apart; otherwise the chip would repeat one value on every row.
 */
export const TeamListRow = ({
  team,
  tournament,
  slug,
  record,
  needle,
  showGroup,
  registrationsByUser,
  heroesMap,
  ontology
}: {
  team: Team;
  tournament: Tournament;
  slug: string;
  record: TeamRecord | null | undefined;
  needle: string;
  showGroup: boolean;
  registrationsByUser: Map<number, Registration>;
  heroesMap: Map<string, CatalogEntityChip>;
  /** The tournament's own game's scoped ontology; `null` while it loads. */
  ontology: RoleOntology | null;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  const variant = overviewVariant(tournament.status);
  // A live leader is not on the podium yet: `placement` moves with every result.
  const medal = variant === "completed";
  // Columns with nothing to say are not drawn. Before the first match no team
  // has a record or a placement, and an empty gutter plus a dash in every row
  // said nothing a dozen times over.
  const hasPlacement = team.placement != null;
  const showsRecord = variant !== "registration";
  const columns =
    ROW_COLUMNS[hasPlacement ? (showsRecord ? "pr" : "p") : showsRecord ? "r" : "none"];
  const players = sortTeamPlayers(team.players, ontology);
  const roster = team.players.map((player) => ({
    ...player,
    heroes: declaredHeroes(player, registrationsByUser.get(player.user_id), heroesMap)
  }));

  return (
    <Card asChild className={cn(TEAM_CARD_CLASS, "group/disclosure")}>
      <details>
        <summary className="cursor-pointer list-none rounded-xl focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] [&::-webkit-details-marker]:hidden">
          <div className={cn(TEAM_CARD_HEADER, "grid items-center gap-2.5 sm:gap-5", columns)}>
            {hasPlacement ? (
              <span>
                <TeamPlacement placement={team.placement as number} medal={medal} />
              </span>
            ) : null}
            <span className="flex min-w-0 flex-col gap-1">
              <span className="flex min-w-0 items-center gap-2">
                <span className={TEAM_CARD_NAME}>
                  <TeamName team={team} size="sm" />
                </span>
                {showGroup && team.group?.name ? (
                  <Badge
                    hue={groupHue(team.group.name)}
                    voice="label"
                    className="hidden shrink-0 sm:inline-flex"
                  >
                    {groupDisplayName(team.group.name, t("common.group"))}
                  </Badge>
                ) : null}
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
                        <PlayerRoleIcon role={player.role} ontology={ontology} size={13} decorative />
                      </span>
                      {matched ? (
                        <mark className={MARK_CLASS}>{player.name}</mark>
                      ) : (
                        splitHandle(player.name).name
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
            {/* Below `sm` the name needs the width; the expanded roster still
                carries every rank. */}
            <TeamCardMetric
              className="hidden sm:block"
              label={t("teams.roster.avgSr")}
              value={format.number(team.avg_sr, { maximumFractionDigits: 0 })}
            />
            {showsRecord ? (
              <TeamCardMetric
                className="min-w-[2.5rem]"
                label={t("tournamentDetail.teams.record")}
                value={record ? `${record.won}–${record.lost}` : "—"}
              />
            ) : null}
            <ChevronDown className={disclosureChevronClass} aria-hidden />
          </div>
        </summary>
        <TeamCardDivider />
        <TournamentTeamTable
          players={roster}
          tournamentGrid={tournament.division_grid_version}
          discipline={tournament.discipline}
          ontology={ontology}
          captainUserId={team.captain_id}
        />
        <TeamCardDivider />
        <div className="px-3.5 py-2.5 text-label">
          <Link
            href={`/tournaments/${slug}/matches?team=${team.id}`}
            className="inline-flex items-center gap-1 text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-teal)]"
          >
            {t("tournamentDetail.teams.teamMatches")}
            <ArrowRight aria-hidden className="size-3" />
          </Link>
        </div>
      </details>
    </Card>
  );
};
