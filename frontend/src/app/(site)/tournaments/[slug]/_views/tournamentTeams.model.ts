import { duelSeats } from "@/lib/encounter/seats";
import { getEncounterWinner } from "@/lib/encounter/status";
import { roleOf } from "@/lib/roster/role-ref";
import type { Encounter } from "@/types/encounter.types";
import type { CatalogEntityChip } from "@/types/catalog.types";
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

/** Whether the search names this person: by the name shown, or the canonical / event-time one they may be known by. */
export function playerMatches(player: Player, needle: string): boolean {
  const { name, tag, canonical, snapshot } = player.display;
  return [name + (tag ?? ""), canonical, snapshot].some((text) => text?.toLowerCase().includes(needle));
}

/** Player names and the team name, lowercased once per team for the search. */
export function matchesSearch(team: Team, needle: string): boolean {
  if (needle === "") return true;
  if (team.name.toLowerCase().includes(needle)) return true;
  return team.players.some((player) => playerMatches(player, needle));
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
    const winner = getEncounterWinner(encounter);
    if (winner === null) continue;
    const [one, two] = duelSeats(encounter.teams);
    bump(one?.team_id, winner === 1);
    bump(two?.team_id, winner === 2);
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
  heroesMap: Map<string, CatalogEntityChip>
): CatalogEntityChip[] {
  if (!registration) return [];
  const roles = registration.roles ?? [];
  // The pick list of the role the player was drafted into; a flex slot (no role) reads the primary one.
  const wanted = player.role ? roleOf(player.role) : null;
  const role =
    (wanted ? roles.find((entry) => roleOf(entry.role) === wanted) : undefined) ??
    roles.find((entry) => entry.is_primary) ??
    roles[0];
  return (role?.top_characters ?? [])
    .slice(0, 3)
    .map(
      (slug) => heroesMap.get(slug) ?? { name: slug, slug, image_path: null, attrs: {} }
    );
}
