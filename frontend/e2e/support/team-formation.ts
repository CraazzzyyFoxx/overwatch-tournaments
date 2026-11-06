import { randomUUID } from "node:crypto";
import type { Api } from "./api";
import { battleTag, OW_FORM, type Registration, type RoleRef } from "./flows";
import { createTournament, createWorkspace, nodeOf, transitionNode, uniq, type Tournament, type Workspace } from "./seed";
import type { TestUser } from "./users";

// Live-draft and mix seeding for the team-formation specs. The plain balancer
// pool comes from flows.ts (`seedPlayers`); what is here needs more than it
// offers: captains linked to real accounts, and workspace members for mixes.

export type RoleRank = readonly [role: string, rank: number];

/** Overwatch 5v5 seat order; 5·n members fill n teams. */
export const OW_SEATS = ["tank", "damage", "damage", "support", "support"] as const;

export const owRole = (role: string): RoleRef => ({ dimension: "player_role", role });

/** Admin-created, approved registration; `userId` links it to a real account (a captain). */
export async function addRegistration(
  api: Api,
  tournamentId: number,
  registrationNodeId: number,
  opts: { tag: string; userId?: number; roles: readonly RoleRank[] }
): Promise<Registration> {
  return api.call<Registration>("POST", `/api/v1/admin/balancer/tournaments/${tournamentId}/registrations`, {
    query: { registration_node_id: registrationNodeId },
    body: {
      answers: { identity_battlenet: [opts.tag] },
      status: "approved",
      auth_user_id: opts.userId ?? null,
      roles: opts.roles.map(([role, rank], i) => ({ role: owRole(role), rank_value: rank, is_primary: i === 0, priority: i })),
    },
    expectStatus: 201,
  });
}

// ---------------------------------------------------------------- draft

export type DraftStatus = "setup" | "ready" | "live" | "paused" | "completed" | "cancelled";
export type DraftSession = {
  id: number;
  tournament_id: number;
  status: DraftStatus;
  current_pick_id: number | null;
  pick_time_seconds: number;
  version: number;
  export_status: string | null;
};
export type DraftPick = {
  id: number;
  overall_no: number;
  draft_team_id: number;
  status: "upcoming" | "on_clock" | "completed" | "skipped" | "autopicked";
  picked_player_id: number | null;
  picked_by_user_id: number | null;
  is_autopick: boolean;
  is_admin_override: boolean;
  clock_expires_at: string | null;
  version: number;
};
export type DraftTeam = { id: number; name: string; captain_auth_user_id: number | null; draft_position: number };
export type DraftPlayer = {
  id: number;
  registration_id: number;
  identity: { handle: string } | null;
  status: string;
  is_captain: boolean;
  drafted_by_team_id: number | null;
  primary_role: RoleRef | null;
};
export type DraftBoard = {
  session: DraftSession;
  teams: DraftTeam[];
  picks: DraftPick[];
  players: DraftPlayer[];
  current_pick: DraftPick | null;
};
export type PickOptions = { pick_id: number; pick_version: number; options: { player_id: number; role: RoleRef; is_safe: boolean }[] };

export const draftBoard = (api: Api, sessionId: number) => api.get<DraftBoard>(`/api/v1/balancer/draft/sessions/${sessionId}/board`);

export type DraftSetup = {
  workspace: Workspace;
  tournament: Tournament;
  /** captains[i] owns draft position i + 1. */
  captains: [TestUser, TestUser];
  captainTags: [string, string];
  pool: Registration[];
  poolTags: string[];
  session: DraftSession;
  /** The draft formation node (`forming`): the draft board and session list are read through it. */
  formationNodeId: number;
  /** `/api/v1/balancer/draft/tournaments/{tid}/sessions/{sid}`: seed, patch, export, delete. */
  base: string;
  /** `/api/v1/balancer/draft/sessions/{sid}`: start, pause, resume, cancel, rollback. */
  lifecycle: string;
};

/**
 * A draft tournament whose registration is closed and whose formation node is `forming`, with two real captains (tank mains)
 * and eight pool players (four damage, four support): 2 teams × 4 picks, snake.
 * The session is seeded (`ready`) unless `start` makes it `live`.
 */
export async function seedDraft(
  api: Api,
  makeUser: (prefix?: string) => Promise<TestUser>,
  opts: { pickTimeSeconds?: number; start?: boolean } = {}
): Promise<DraftSetup> {
  const workspace = await createWorkspace(api);
  const tournament = await createTournament(api, workspace.id, { team_formation: "draft" });
  // The pool is registered while the intake is open; the draft starts once it is closed and the formation is forming.
  const registration = await nodeOf(api, tournament.id, "registration");
  const formation = await nodeOf(api, tournament.id, "formation");
  await api.put(`/api/v1/admin/balancer/tournaments/${tournament.id}/registration-form`, { form_schema: OW_FORM });
  await transitionNode(api, registration.id, "open");
  const captains: [TestUser, TestUser] = [await makeUser("capa"), await makeUser("capb")];
  const captainTags: [string, string] = [battleTag(uniq("CapA")), battleTag(uniq("CapB"))];
  const captainRegs = [
    await addRegistration(api, tournament.id, registration.id, { tag: captainTags[0], userId: captains[0].id, roles: [["tank", 3000], ["damage", 2900]] }),
    await addRegistration(api, tournament.id, registration.id, { tag: captainTags[1], userId: captains[1].id, roles: [["tank", 2950], ["support", 2850]] }),
  ];
  const poolTags: string[] = [];
  const pool: Registration[] = [];
  for (const [i, role] of ["damage", "damage", "damage", "damage", "support", "support", "support", "support"].entries()) {
    const tag = battleTag(uniq("Dr"));
    poolTags.push(tag);
    pool.push(await addRegistration(api, tournament.id, registration.id, { tag, roles: [[role, 2500 + i * 60]] }));
  }
  await transitionNode(api, registration.id, "closed");
  await transitionNode(api, formation.id, "forming");
  const sessions = `/api/v1/balancer/draft/tournaments/${tournament.id}/sessions`;
  const created = await api.post<DraftSession>(sessions, {
    pool_source: "manual",
    pick_time_seconds: opts.pickTimeSeconds ?? 300,
    formation_node_id: formation.id,
  });
  const base = `${sessions}/${created.id}`;
  const lifecycle = `/api/v1/balancer/draft/sessions/${created.id}`;
  const seeded = await api.post<{ session: DraftSession }>(`${base}/seed`, {
    pool_captains: captainRegs.map((reg) => ({ registration_id: reg.id })),
    captain_order: "manual",
  });
  const session = opts.start ? await api.post<DraftSession>(`${lifecycle}/start`) : seeded.session;
  return { workspace, tournament, captains, captainTags, pool, poolTags, session, formationNodeId: formation.id, base, lifecycle };
}

/** The first feasibility-safe option of the on-clock pick, picked by `as` (its captain or an admin). */
export async function pickFirstSafe(as: Api, pickId: number) {
  const options = await as.get<PickOptions>(`/api/v1/balancer/draft/picks/${pickId}/options`);
  const safe = options.options.find((option) => option.is_safe);
  if (!safe) throw new Error(`pick ${pickId} has no safe option`);
  await as.post(`/api/v1/balancer/draft/picks/${pickId}/select`, {
    expected_version: options.pick_version,
    player_id: safe.player_id,
    target_role: safe.role,
  });
  return safe;
}

// ---------------------------------------------------------------- mix

export type MixMember = { member_id: number; display_name: string | null; identity: { provider: string; handle: string } | null };

/** Unlinked workspace members (BattleTag only) with canon ranks on two roles each, seat roles cycling OW_SEATS. */
export async function seedMembers(api: Api, workspaceId: number, count: number, baseRank = 2000): Promise<MixMember[]> {
  const members: MixMember[] = [];
  for (let i = 0; i < count; i++) {
    const member = await api.post<MixMember>(`/api/v1/balancer/workspaces/${workspaceId}/players`, {
      discipline: "overwatch",
      identity: { provider: "battlenet", handle: battleTag(uniq("Mx")) },
    });
    const main = OW_SEATS[i % OW_SEATS.length];
    const off = main === "support" ? "damage" : "support";
    await api.put(`/api/v1/balancer/workspaces/${workspaceId}/players/${member.member_id}/ranks`, {
      discipline: "overwatch",
      scope: "workspace",
      ranks: { [main]: baseRank + i * 60, [off]: baseRank + i * 60 - 200 },
    });
    members.push(member);
  }
  return members;
}

export type MixVariant = { teams: { id: number; roster: Record<string, string[]> }[]; benched: string[] };
export type MixLobby = {
  lobby_index: number;
  selected_variant_index: number;
  next_map_id: number | null;
  balanced_at: string | null;
  balance_result: { variants: MixVariant[] } | null;
};
export type MixPlayer = {
  workspace_member_id: number;
  display_name: string;
  participation: "must_play" | "pool" | "benched";
  is_flex: boolean;
  lobby_pin: number | null;
  current_lobby: number | null;
  ranks: Record<string, number | null>;
};
export type Mix = {
  id: number;
  workspace_id: number;
  host_user_id: number;
  name: string;
  status: "draft" | "balanced" | "completed" | "cancelled";
  lobby_count: number;
  lobbies: MixLobby[];
  co_hosts: { user_id: number }[];
  self_signup: "closed" | "pool" | "benched";
  self_role_edit: boolean;
  matches_count: number;
  settings: { team_names: Record<string, string>; points_per_win: number };
  players: MixPlayer[];
};

export async function createMix(api: Api, workspaceId: number, memberIds: number[], name = uniq("Mix")) {
  return api.post<Mix>(`/api/v1/balancer/workspaces/${workspaceId}/custom-games`, { name, discipline: "overwatch", member_ids: memberIds });
}

/** A catalog map under a fresh mode, so a mix can roll a next map without depending on other specs' catalog rows. */
export async function createMap(api: Api) {
  const tag = randomUUID().slice(0, 8);
  const mode = await api.post<{ id: number }>("/api/v1/admin/catalog/overwatch/mode", { slug: `tf-mode-${tag}`, name: `TF Mode ${tag}` });
  return api.post<{ id: number; name: string }>("/api/v1/admin/catalog/overwatch/map", {
    slug: `tf-map-${tag}`,
    name: `TF Map ${tag}`,
    parent_id: mode.id,
  });
}
