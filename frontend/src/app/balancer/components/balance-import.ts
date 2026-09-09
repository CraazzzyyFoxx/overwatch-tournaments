import type {
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalancePlayer,
  InternalBalanceTeam
} from "@/types/balancer-admin.types";

import {
  BALANCE_ROSTER_KEYS,
  calculateTeamAverageValueFromPayload,
  calculateTeamDiscomfortFromPayload,
  calculateTeamVarianceFromPayload
} from "./balancer-page-helpers";
import { recalculateBalanceStatistics } from "@/components/balancer/balance-editor-helpers";

const FORMAT_HINT =
  'Expected the internal balance format written by "Download JSON": { "teams": [{ "name": …, "roster": { "Tank": [{ "uuid", "name", "assigned_rating" }] } }] }.';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parsePlayer(raw: unknown, where: string): InternalBalancePlayer {
  if (!isRecord(raw)) {
    throw new Error(`${where} is not an object. ${FORMAT_HINT}`);
  }
  const { uuid, name, assigned_rating: assignedRating } = raw;
  if (typeof uuid !== "string" && typeof uuid !== "number") {
    throw new Error(`${where} is missing "uuid".`);
  }
  if (typeof name !== "string" || name.length === 0) {
    throw new Error(`${where} is missing "name".`);
  }
  if (typeof assignedRating !== "number") {
    throw new Error(`${where} is missing a numeric "assigned_rating". ${FORMAT_HINT}`);
  }

  return {
    uuid: String(uuid),
    name,
    assigned_rating: assignedRating,
    role_discomfort: typeof raw.role_discomfort === "number" ? raw.role_discomfort : 0,
    is_captain: raw.is_captain === true,
    is_flex: raw.is_flex === true,
    role_preferences: Array.isArray(raw.role_preferences)
      ? raw.role_preferences.filter((role): role is string => typeof role === "string")
      : [],
    sub_role: typeof raw.sub_role === "string" ? raw.sub_role : null,
    all_ratings: isRecord(raw.all_ratings) ? (raw.all_ratings as Record<string, number>) : {},
    all_discomforts: isRecord(raw.all_discomforts)
      ? (raw.all_discomforts as Record<string, number>)
      : {}
  };
}

function parseTeam(raw: unknown, index: number): InternalBalanceTeam {
  if (!isRecord(raw)) {
    throw new Error(`Team #${index + 1} is not an object. ${FORMAT_HINT}`);
  }
  const name = typeof raw.name === "string" && raw.name.length > 0 ? raw.name : null;
  if (name === null) {
    throw new Error(`Team #${index + 1} is missing "name".`);
  }
  const roster = raw.roster;
  if (!isRecord(roster)) {
    throw new Error(`Team "${name}" is missing a "roster" object. ${FORMAT_HINT}`);
  }
  // Reject unknown buckets instead of silently dropping their players.
  const unknownRole = Object.keys(roster).find(
    (roleKey) => !BALANCE_ROSTER_KEYS.includes(roleKey as BalancerRosterKey)
  );
  if (unknownRole !== undefined) {
    throw new Error(
      `Team "${name}" has an unsupported roster role "${unknownRole}". Use Tank, Damage or Support.`
    );
  }

  const parsedRoster = { Tank: [], Damage: [], Support: [] } as Record<
    BalancerRosterKey,
    InternalBalancePlayer[]
  >;
  for (const roleKey of BALANCE_ROSTER_KEYS) {
    const players = roster[roleKey];
    if (players === undefined || players === null) {
      continue;
    }
    if (!Array.isArray(players)) {
      throw new Error(`Team "${name}" roster.${roleKey} is not an array.`);
    }
    parsedRoster[roleKey] = players.map((player, playerIndex) =>
      parsePlayer(player, `Team "${name}" ${roleKey} player #${playerIndex + 1}`)
    );
  }

  // Aggregates are derived, so recompute whatever the file omitted rather than
  // rendering undefined MMR in the editor.
  const team: InternalBalanceTeam = {
    id: typeof raw.id === "number" ? raw.id : index + 1,
    name,
    average_mmr: 0,
    roster: parsedRoster
  };
  const discomfort = calculateTeamDiscomfortFromPayload(team);

  return {
    ...team,
    average_mmr:
      typeof raw.average_mmr === "number"
        ? raw.average_mmr
        : calculateTeamAverageValueFromPayload(team),
    rating_variance:
      typeof raw.rating_variance === "number"
        ? raw.rating_variance
        : calculateTeamVarianceFromPayload(team),
    total_discomfort:
      typeof raw.total_discomfort === "number" ? raw.total_discomfort : discomfort.total,
    max_discomfort: typeof raw.max_discomfort === "number" ? raw.max_discomfort : discomfort.max
  };
}

/**
 * Parse a balance JSON file into a preview payload.
 *
 * Import only loads a variant into the editor — it never writes tournament
 * teams, so Save / Export to Tournament stay explicit follow-up actions.
 * Throws with a message naming the offending field; the import dialog shows it
 * verbatim.
 */
export function parseImportedBalancePayload(text: string): InternalBalancePayload {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error("Selected file is not valid JSON.");
  }

  if (!isRecord(raw) || !Array.isArray(raw.teams)) {
    throw new Error(`Balance JSON must contain a "teams" array. ${FORMAT_HINT}`);
  }
  if (raw.teams.length === 0) {
    throw new Error("Balance JSON contains no teams.");
  }

  const payload: InternalBalancePayload = {
    teams: raw.teams.map(parseTeam),
    statistics: isRecord(raw.statistics)
      ? (raw.statistics as InternalBalancePayload["statistics"])
      : undefined,
    benched_players: Array.isArray(raw.benched_players)
      ? raw.benched_players.map((player, index) =>
          parsePlayer(player, `Benched player #${index + 1}`)
        )
      : []
  };

  // `PUT .../balance` validates statistics against the solver's `Statistics`
  // schema, where average_mmr, mmr_std_dev, total_teams and players_per_team are
  // required. A file written by hand — or trimmed to the documented
  // `{ teams: [...] }` minimum — imports fine and then 422s on save, so the
  // derivable fields are filled in. Whatever the file states wins: only the
  // solver knows its own objective scores.
  return {
    ...payload,
    statistics: { ...recalculateBalanceStatistics(payload), ...payload.statistics }
  };
}
