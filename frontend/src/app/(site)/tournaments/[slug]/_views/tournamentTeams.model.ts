import { isEncounterCompleted } from "@/lib/encounter/status";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { Hero } from "@/types/hero.types";
import type { Registration } from "@/types/registration.types";
import type { Player, Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";
import { sortTeamPlayers } from "@/utils/player";

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

/** Slot code -> the canonical role name `PlayerRoleIcon` maps to a glyph. */
const SLOT_ROLE: Record<RosterSlotCode, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex"
};

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
 * The roster slots of the tournament, one entry per player the shape asks for,
 * paired positionally with the team's roster. `sortTeamPlayers` orders players
 * tank -> damage -> support -> flex, the same canonical order the slot codes
 * come in, so index pairing lands each glyph on its own player.
 */
export function rosterSlots(
  tournament: Tournament,
  team: Team
): { role: string; player?: Player }[] {
  const players = sortTeamPlayers(team.players);
  const shape = tournament.roster_shape;

  if (!shape) {
    // No shape entity on this read: the team's own roster is the shape.
    return players.map((player) => ({ role: normalizePlayerRole(player.role), player }));
  }

  const slots: { role: string; player?: Player }[] = [];
  for (const code of ROSTER_SLOT_CODES) {
    for (let index = 0; index < (shape.slots[code] ?? 0); index += 1) {
      slots.push({ role: SLOT_ROLE[code] });
    }
  }
  return slots.map((slot, index) => {
    const player = players[index];
    // The player's own role is the truth when one fills the slot; the slot's
    // role only labels a seat nobody took.
    return player ? { role: normalizePlayerRole(player.role), player } : slot;
  });
}

/**
 * The list's column tracks: seed · logo slot · name · AVG SR · [role glyphs] ·
 * W–L · chevron. The logo track is always reserved so names align whether or
 * not a team uploaded an image (`TeamLogo` renders nothing without one). The
 * glyph track exists only for a shape with role slots — an all-flex roster
 * would show five identical glyphs, which says nothing.
 */
export function listGrid(withRoles: boolean): string {
  return cn(
    "grid items-center gap-2 text-ui sm:gap-3",
    "grid-cols-[2rem_1.25rem_minmax(0,1fr)_3.5rem_2.75rem_1.25rem]",
    withRoles
      ? "sm:grid-cols-[2.5rem_1.25rem_minmax(0,1fr)_4rem_auto_3.5rem_1.25rem]"
      : "sm:grid-cols-[2.5rem_1.25rem_minmax(0,1fr)_4rem_3.5rem_1.25rem]"
  );
}

/** Role · battletag · division+SR · [heroes] · notes. The name track is capped
 *  so the division does not drift to the far edge of a wide row. */
export function rosterGrid(withHeroes: boolean): string {
  return cn(
    "grid items-center gap-2",
    withHeroes
      ? "grid-cols-[3rem_minmax(0,16rem)_6rem_4.5rem_minmax(0,1fr)]"
      : "grid-cols-[3rem_minmax(0,16rem)_6rem_minmax(0,1fr)]"
  );
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
