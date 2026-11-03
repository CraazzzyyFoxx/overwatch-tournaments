import { expect } from "@playwright/test";
import { type Api, poll } from "./api";
import type { BracketSeed, Encounter, SeededTeam } from "./flows";
import { act, actingSeat, getState, readyBoth, type PickBanState, type Room } from "./pickban";
import type { TestUser } from "./users";

/**
 * Result-layer helpers (encounter layer V1): per-game claims, series reports,
 * the organizer's overrides and the bracket wiring they move. Seeding is
 * `seedBracket` (flows.ts); everything here reads or writes one encounter.
 */

export type GameState = "planned" | "awaiting_result" | "disputed" | "confirmed" | "cancelled";
export type GameLine = { encounter_team_id: number; score: number | null; placement: number | null };
export type Game = {
  id: number;
  position: number;
  map_id: number | null;
  state: GameState;
  result_source: string | null;
  result_version: number;
  /** Lines on the encounter read (`entities=matches`). */
  teams: GameLine[];
};
export type ClaimedGame = Omit<Game, "teams"> & {
  results: GameLine[];
  claims: { claimant_team_id: number; results: GameLine[] }[];
};
export type ClaimAnswer = { disputed: boolean; resolved: boolean; game: ClaimedGame };
export type SlotSource = { encounter_id: number; source_position: number; slot: number };
export type EncounterDetail = Encounter & {
  result_source: string | null;
  games: Game[];
  sources: SlotSource[];
};
export type ReportLine = { encounter_team_id: number; score: number; wins?: number | null; placement?: number | null };
export type SeriesReport = {
  basis_version?: number;
  games_played: number;
  results: ReportLine[];
  closeness?: number;
  comment?: string;
  custom_fields?: Record<string, string>;
};
export type TeamReport = {
  encounter_team_id: number;
  reporter_name: string | null;
  games_played: number;
  closeness: number | null;
  comment: string | null;
  custom_fields: Record<string, string>;
  results: ReportLine[];
};
export type ReportAnswer = { result_status: string; status: string; result_version: number; reports: TeamReport[] };
export type AuditRow = {
  action: string;
  from_result_status: string | null;
  to_result_status: string | null;
  actor_name: string | null;
  source: string | null;
  game_id: number | null;
  adopted_team_id: number | null;
  reason: string | null;
};

/** One duel seat, joined to the seeded team that sits in it. */
export type Side = { seat: number; team: SeededTeam; captain: TestUser };

/** The encounter's two seats in slot order, with their teams and captains. */
export function sides(seed: BracketSeed, encounter: Pick<Encounter, "teams">): [Side, Side] {
  const seats = [...encounter.teams].sort((a, b) => a.slot - b.slot);
  const [home, away] = seats.map((s) => {
    const team = seed.teams.find((t) => t.id === s.team_id);
    if (!team?.captain) throw new Error(`seat ${s.id} (team ${s.team_id}) has no seeded captain`);
    return { seat: s.id, team, captain: team.captain };
  });
  return [home, away];
}

export function readEncounter(api: Api, id: number) {
  return api.get<EncounterDetail>(`/api/v1/encounters/${id}`, { entities: "matches" });
}

/** A seat's line on an encounter read. */
export function seatOf(encounter: Pick<Encounter, "teams">, seat: number) {
  const line = encounter.teams.find((t) => t.id === seat);
  expect(line, `seat ${seat} on encounter`).toBeTruthy();
  return line!;
}

/** The open position the room offers next; games open asynchronously (room reconcile) after the previous one settles. */
export function openGame(api: Api, encounterId: number, position: number) {
  return poll(
    async () => {
      const e = await readEncounter(api, encounterId);
      return e.games.find((g) => g.position === position && (g.state === "planned" || g.state === "awaiting_result"));
    },
    `game ${position} of encounter ${encounterId} to open`,
    30_000
  );
}

export function claimGame(user: TestUser, encounterId: number, game: Pick<Game, "id" | "result_version">, scores: Record<number, number>) {
  return user.api.post<ClaimAnswer>(`/api/v1/encounters/${encounterId}/games/${game.id}/report`, {
    basis_version: game.result_version,
    results: Object.entries(scores).map(([seat, score]) => ({ encounter_team_id: Number(seat), score })),
  });
}

export function reportSeries(user: TestUser, encounterId: number, body: SeriesReport) {
  return user.api.post<ReportAnswer>(`/api/v1/encounters/${encounterId}/report`, body);
}

/** A won series as both `score` and `wins`, which a "wins" rule needs to tell where the card ended. */
export function series(winner: number, loser: number, won: number, lost: number, extra: Partial<SeriesReport> = {}): SeriesReport {
  return {
    games_played: won + lost,
    closeness: 7,
    results: [
      { encounter_team_id: winner, score: won, wins: won },
      { encounter_team_id: loser, score: lost, wins: lost },
    ],
    ...extra,
  };
}

/** The result journal, newest first. */
export function resultAudit(api: Api, encounterId: number) {
  return api.get<AuditRow[]>(`/api/v1/admin/encounters/${encounterId}/result-audit`);
}

/** The encounter fed by `fromId`'s `position` (1 = winner, 2 = loser) and the slot it lands in. */
export async function feed(api: Api, encounters: Encounter[], fromId: number, position: 1 | 2) {
  for (const e of encounters) {
    const detail = await readEncounter(api, e.id);
    const source = detail.sources.find((s) => s.encounter_id === fromId && s.source_position === position);
    if (source) return { encounter: detail, slot: source.slot };
  }
  throw new Error(`no encounter takes position ${position} of encounter ${fromId}`);
}

/** Polls until the team sits in `slot` of the encounter that `fromId`'s `position` feeds. */
export async function expectAdvanced(api: Api, encounters: Encounter[], fromId: number, position: 1 | 2, teamId: number) {
  const { encounter, slot } = await feed(api, encounters, fromId, position);
  await expect
    .poll(async () => (await readEncounter(api, encounter.id)).teams.find((t) => t.slot === slot)?.team_id ?? null, {
      message: `encounter ${encounter.id} slot ${slot} takes position ${position} of ${fromId}`,
    })
    .toBe(teamId);
  return encounter;
}

/** Replaces the stage's whole `scoring`: fine for the `wins`-preset stages the specs build. */
export function setPoints(api: Api, stageId: number, win: number, draw: number, loss: number) {
  return api.patch(`/api/v1/admin/stages/${stageId}`, { scoring: { win, draw, loss } });
}

/** Readies both captains and plays the map veto to its end over the API: each acting captain takes its step on the first available map. */
export async function finishVeto(admin: Api, room: Room): Promise<PickBanState> {
  await readyBoth(room);
  for (;;) {
    const state = await getState(admin, room.encounterId, "map");
    if (state.is_complete) return state;
    const item = state.pool.find((p) => p.status === "available");
    expect(item && state.expected_action, `veto step ${state.current_step_index} has a map and an action`).toBeTruthy();
    await act(actingSeat(room, state).captain, room.encounterId, "map", item!.item_id, state.expected_action!);
  }
}
