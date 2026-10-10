import { isEncounterCompleted } from "@/lib/encounter/status";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import type { Encounter } from "@/types/encounter.types";
import type { Hero } from "@/types/hero.types";
import type { Registration } from "@/types/registration.types";
import type { Player, Team } from "@/types/team.types";

export const TEAMS_VIEWS = ["list", "cards"] as const;
export type TeamsView = (typeof TEAMS_VIEWS)[number];

export const TEAMS_SORTS = ["placement", "group", "sr", "name"] as const;
export type TeamsSortBy = (typeof TEAMS_SORTS)[number];

/**
 * `<mark>` on its own is a yellow block from the user agent, unreadable on the
 * dark surface. The element stays — it is what "this is the match" means to
 * assistive tech — and only the colours come from the tokens.
 */
export const MARK_CLASS =
  "rounded-[3px] bg-[color:color-mix(in_srgb,var(--aqt-teal)_22%,transparent)] px-0.5 text-[color:var(--aqt-fg)]";

/** A team's settled series record. `null` when encounters are unavailable. */
export type TeamRecord = { won: number; lost: number };

/** Battletags and the team name, lowercased once per team for the search. */
export function matchesSearch(team: Team, needle: string): boolean {
  if (needle === "") return true;
  if (team.name.toLowerCase().includes(needle)) return true;
  return team.players.some((player) => player.name.toLowerCase().includes(needle));
}

export function compareTeams(a: Team, b: Team, sortBy: TeamsSortBy): number {
  switch (sortBy) {
    case "placement": {
      const ap = a.placement ?? Number.POSITIVE_INFINITY;
      const bp = b.placement ?? Number.POSITIVE_INFINITY;
      return ap - bp || a.name.localeCompare(b.name);
    }
    case "group": {
      const ag = a.group?.name ?? "";
      const bg = b.group?.name ?? "";
      // Ungrouped teams sort after every named group rather than before it.
      if (ag !== bg) return ag === "" ? 1 : bg === "" ? -1 : ag.localeCompare(bg);
      return compareTeams(a, b, "placement");
    }
    case "sr":
      return (b.avg_sr ?? 0) - (a.avg_sr ?? 0) || a.name.localeCompare(b.name);
    case "name":
      return a.name.localeCompare(b.name);
  }
}

/**
 * Settled series per team. A draw counts for neither side; unplayed and live
 * matches are not a record yet.
 */
export function buildRecords(encounters: Encounter[]): Map<number, TeamRecord> {
  const records = new Map<number, TeamRecord>();
  const bump = (teamId: number | null | undefined, won: boolean) => {
    if (teamId == null) return;
    const current = records.get(teamId) ?? { won: 0, lost: 0 };
    if (won) current.won += 1;
    else current.lost += 1;
    records.set(teamId, current);
  };

  for (const encounter of encounters) {
    if (!isEncounterCompleted(encounter)) continue;
    const home = encounter.score?.home ?? 0;
    const away = encounter.score?.away ?? 0;
    if (home === away) continue;
    bump(encounter.home_team_id, home > away);
    bump(encounter.away_team_id, away > home);
  }

  return records;
}

/**
 * The heroes a player declared for the role they were drafted into (§5 ③).
 * The public teams read carries no hero data, so the source is the same
 * registration list the participants pool shows — declared picks, not
 * playtime. A player without a registration (team-registration tournaments,
 * hand-added substitutes) has none.
 */
export function declaredHeroes(
  player: Player,
  registration: Registration | undefined,
  heroesMap: Map<string, Hero>
): Hero[] {
  if (!registration) return [];
  const roles = registration.roles ?? [];
  const wanted = normalizePlayerRole(player.role);
  const role =
    roles.find((entry) => normalizePlayerRole(entry.role) === wanted) ??
    roles.find((entry) => entry.is_primary) ??
    roles[0];
  return (role?.top_heroes ?? [])
    .slice(0, 3)
    .map(
      (slug) =>
        heroesMap.get(slug) ?? ({ name: slug, slug, image_path: "", role: wanted } as Hero)
    );
}
