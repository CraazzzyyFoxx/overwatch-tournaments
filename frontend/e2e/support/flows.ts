import { expect } from "@playwright/test";
import { type Api, poll, rememberNodes } from "./api";
import { createTournament, createWorkspace, flowNodes, nodeOf, transitionNode, uniq, type Discipline, type Tournament, type Workspace } from "./seed";
import type { TestUser } from "./users";

/**
 * Reusable lifecycle builders over the real admin/public API. Every helper
 * goes through the same endpoints the product uses; nothing writes SQL.
 */

export type StageType = "round_robin" | "single_elimination" | "double_elimination" | "swiss" | "ffa_league";
export type RoleRef = { dimension: string; role: string; parent?: string | null };

// ---------------------------------------------------------------- registration

export type FormField = {
  key: string;
  kind: string;
  label?: string | null;
  required?: boolean;
  editable?: boolean;
  options?: string[] | null;
  params?: Record<string, unknown>;
};
export type FormSchema = { schema_version?: number; sections: { key: string; title?: string | null; fields: FormField[] }[] };

/** BattleTag + roles + stream POV, all player-editable: the common Overwatch sign-up. */
export const OW_FORM: FormSchema = {
  schema_version: 1,
  sections: [
    {
      key: "main",
      title: "Player",
      fields: [
        { key: "identity_battlenet", kind: "builtin", required: true, editable: true },
        { key: "roles", kind: "builtin", required: true, editable: true },
        { key: "stream_pov", kind: "builtin", editable: true },
      ],
    },
  ],
};

export type RegistrationForm = { id: number; version_id: number; form_schema: FormSchema };

export type FlowNodeScheduleEntry = { phase: string; starts_at: string; ends_at?: string | null };

const HOUR = 3_600_000;
const at = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

/** Sign-up and check-in windows both open right now (check-in starts after sign-up). */
export function openWindows(): FlowNodeScheduleEntry[] {
  return [
    { phase: "open", starts_at: at(-2 * HOUR), ends_at: at(24 * HOUR) },
    { phase: "check_in", starts_at: at(-HOUR), ends_at: at(36 * HOUR) },
  ];
}

/**
 * Saves the form, writes the registration node's `auto_approve` and sign-up windows, and moves the node `draft → open`.
 * `registrationNodeId` picks a node of a tournament with several; without it, the first one.
 * Returns the form version registrants submit against and the node they register into.
 */
export async function openRegistration(
  api: Api,
  tournamentId: number,
  opts: { form?: FormSchema; autoApprove?: boolean; schedule?: FlowNodeScheduleEntry[]; registrationNodeId?: number } = {}
): Promise<{ versionId: number; registrationNodeId: number }> {
  await api.put(`/api/v1/admin/balancer/tournaments/${tournamentId}/registration-form`, { form_schema: opts.form ?? OW_FORM });
  const node =
    opts.registrationNodeId === undefined
      ? await nodeOf(api, tournamentId, "registration")
      : (await flowNodes(api, tournamentId)).find((candidate) => candidate.id === opts.registrationNodeId)!;
  await api.put(`/api/v1/admin/tournaments/${tournamentId}/flow`, {
    nodes: [{ id: node.id, kind: node.kind, name: node.name, config: { ...node.config, auto_approve: opts.autoApprove ?? false } }],
  });
  await api.put(`/api/v1/admin/flow-nodes/${node.id}/schedule`, { schedule: opts.schedule ?? openWindows() });
  rememberNodes(tournamentId, { registration: node.id });
  await transitionNode(api, node.id, "open");
  const form = await api.get<RegistrationForm>(`/api/v1/tournaments/${tournamentId}/registration/form`);
  return { versionId: form.version_id, registrationNodeId: node.id };
}

export type RegistrationRole = { role: RoleRef; is_primary: boolean; priority: number; rank_value: number | null };
export type Registration = {
  id: number;
  tournament_id: number;
  user_id: number;
  display_name?: string | null;
  primary_handle: string | null;
  answers: Record<string, unknown>;
  roles: RegistrationRole[];
  status: string;
  balancer_status: string;
  checked_in: boolean;
  can_edit?: boolean;
  admission?: { decision: string };
};

/** A real user signs up through the public endpoint. `roles[0]` is primary. */
export async function registerSelf(
  user: Pick<TestUser, "api" | "username">,
  tournamentId: number,
  registrationNodeId: number,
  versionId: number,
  opts: { roles: string[]; handle?: string; answers?: Record<string, unknown> }
): Promise<Registration> {
  return user.api.call<Registration>("POST", `/api/v1/tournaments/${tournamentId}/registration`, {
    query: { registration_node_id: registrationNodeId },
    body: {
      form_version_id: versionId,
      answers: {
        identity_battlenet: [opts.handle ?? battleTag(user.username)],
        roles: opts.roles.map((role, i) => ({ role, is_primary: i === 0 })),
        ...opts.answers,
      },
    },
    expectStatus: 201,
  });
}

/** A BattleTag the server's pattern accepts (2–12 chars before `#`, 4+ digits after). */
export function battleTag(seed: string) {
  const name = seed.replace(/[^A-Za-z0-9]/g, "").slice(0, 12).padEnd(2, "x");
  return `${name}#${1000 + Math.floor(Math.random() * 9000)}`;
}

/** Organizer sets the rank of a registration's roles (registration-layer rank, what the pool reads). */
export async function rankRegistration(api: Api, registrationId: number, roles: { role: RoleRef; rank: number }[]) {
  return api.patch<Registration>(`/api/v1/admin/balancer/registrations/${registrationId}`, {
    roles: roles.map((r, i) => ({ role: r.role, is_primary: i === 0, priority: i, rank_value: r.rank })),
  });
}

export type TeamFormat = {
  preset_code: string;
  starter_min: number;
  rules: { role: RoleRef; hard_min: number | null }[];
};

/** One role per roster slot, from the tournament's resolved team format (`null` = an unroled slot). */
export async function rosterSlots(api: Api, tournamentId: number): Promise<(RoleRef | null)[]> {
  const format = await api.get<TeamFormat>(`/api/v1/admin/tournaments/${tournamentId}/team-format`);
  const slots: (RoleRef | null)[] = format.rules.flatMap((r) =>
    Array.from({ length: r.hard_min ?? 0 }, () => ({ dimension: r.role.dimension, role: r.role.role }))
  );
  while (slots.length < format.starter_min) slots.push(null);
  return slots;
}

export type SeededRegistration = Registration & { role: RoleRef | null; rank: number };

/**
 * `n` registrations created by the organizer's manual-registration API (no
 * auth users), roles following the roster shape, ranked, and — unless
 * `pending` — approved and added to the balancer pool. `n = teams × teamSize`
 * balances into whole teams.
 */
export async function seedPlayers(
  api: Api,
  tournamentId: number,
  n: number,
  opts: { registrationNodeId: number; pending?: boolean; rankBase?: number }
): Promise<SeededRegistration[]> {
  const query = { registration_node_id: opts.registrationNodeId };
  const slots = await rosterSlots(api, tournamentId);
  const made: SeededRegistration[] = [];
  for (let i = 0; i < n; i++) {
    const role = slots[i % slots.length];
    const rank = (opts.rankBase ?? 2000) + ((i * 137) % 1500);
    const name = `Seed${uniq("p").slice(2, 8)}${i}`;
    const reg = await api.call<Registration>("POST", `/api/v1/admin/balancer/tournaments/${tournamentId}/registrations`, {
      query,
      body: {
        display_name: name,
        answers: { identity_battlenet: [battleTag(name)] },
        roles: role ? [{ role, is_primary: true, priority: 0, rank_value: rank }] : [],
      },
      expectStatus: 201,
    });
    made.push({ ...reg, role, rank });
  }
  if (!opts.pending) {
    const ids = made.map((r) => r.id);
    await api.call("POST", `/api/v1/admin/balancer/tournaments/${tournamentId}/registrations/bulk-approve`, {
      query,
      body: { registration_ids: ids },
    });
    await api.call("POST", `/api/v1/admin/balancer/tournaments/${tournamentId}/registrations/bulk-add-to-balancer`, {
      query,
      body: { registration_ids: ids },
    });
  }
  return made;
}

// ---------------------------------------------------------------- balancer

export type BalancerJob = { job_id: string; status: "queued" | "running" | "succeeded" | "failed"; error?: string | null };
export type BalanceVariant = {
  teams: { id: number; name: string; average_mmr: number; roster: Record<string, { uuid: string; name: string; is_captain: boolean }[]> }[];
  benched_players?: unknown[];
  statistics: Record<string, unknown>;
};
export type BalanceExport = { job: BalancerJob; variant: BalanceVariant; balanceId: number; teams: Team[] };

/**
 * Async balance (202 + job poll), first variant saved and exported into tournament teams. A `draft` formation node
 * moves to `forming` here (so the caller must have closed its input first); once the teams exist it moves to `completed`.
 */
export async function balanceAndExport(api: Api, tournamentId: number, formationNodeId: number): Promise<BalanceExport> {
  const query = { formation_node_id: formationNodeId };
  const node = (await flowNodes(api, tournamentId)).find((candidate) => candidate.id === formationNodeId);
  if (node?.status === "draft") await transitionNode(api, formationNodeId, "forming");
  const queued = await api.call<BalancerJob>("POST", `/api/v1/balancer/tournaments/${tournamentId}/balance`, {
    body: {},
    query,
    expectStatus: 202,
  });
  const job = await poll(
    async () => {
      const j = await api.get<BalancerJob>(`/api/v1/balancer/jobs/${queued.job_id}`);
      return j.status === "succeeded" || j.status === "failed" ? j : undefined;
    },
    `balance job ${queued.job_id}`,
    120_000
  );
  expect(job.status, `balance job failed: ${job.error}`).toBe("succeeded");
  const { variants } = await api.get<{ variants: BalanceVariant[] }>(`/api/v1/balancer/jobs/${job.job_id}/result`);
  expect(variants.length, "balance job produced at least one variant").toBeGreaterThan(0);
  const saved = await api.call<{ id: number }>("PUT", `/api/v1/balancer/tournaments/${tournamentId}/balance`, {
    query,
    body: { config_json: null, result_json: variants[0] },
  });
  const exported = await api.post<{ success: boolean; imported_teams: number }>(`/api/v1/balancer/balances/${saved.id}/export`, {});
  expect(exported.imported_teams, "exported team count").toBe(variants[0].teams.length);
  await transitionNode(api, formationNodeId, "completed");
  return { job, variant: variants[0], balanceId: saved.id, teams: await listTeams(api, tournamentId) };
}

/**
 * For teams made by `seedTeams`: the registration node `draft → open → closed` (saving `OW_FORM` first when the
 * tournament has no form) and the formation node `draft → forming → completed`.
 */
export async function formTeams(api: Api, tournamentId: number): Promise<void> {
  const registration = await nodeOf(api, tournamentId, "registration");
  const formation = await nodeOf(api, tournamentId, "formation");
  if (!(await api.raw("GET", `/api/v1/tournaments/${tournamentId}/registration/form`)).ok()) {
    await api.put(`/api/v1/admin/balancer/tournaments/${tournamentId}/registration-form`, { form_schema: OW_FORM });
  }
  for (const status of ["open", "closed"]) await transitionNode(api, registration.id, status);
  for (const status of ["forming", "completed"]) await transitionNode(api, formation.id, status);
}

// ---------------------------------------------------------------- teams

export type TeamPlayer = { id: number; name: string; rank: number; role?: RoleRef | null; user_id: number; team_id: number };
export type Team = { id: number; name: string; captain_id: number | null; avg_sr: number; tournament_id: number; players: TeamPlayer[] };
export type SeededTeam = Team & { captain?: TestUser };

export async function listTeams(api: Api, tournamentId: number): Promise<Team[]> {
  const page = await api.get<{ results: Team[] }>("/api/v1/teams", { tournament_id: tournamentId, per_page: 100, entities: "players" });
  return page.results;
}

/** players.user id linked to an auth user: what `team.captain_id` and `player.user_id` reference. */
export async function playerIdOf(user: Pick<TestUser, "api">): Promise<number> {
  const me = await user.api.get<{ linked_players: { player_id: number; is_primary: boolean }[] }>("/api/v1/auth/me");
  const linked = me.linked_players.find((p) => p.is_primary) ?? me.linked_players[0];
  expect(linked, "auth user has a linked player").toBeTruthy();
  return linked.player_id;
}

/**
 * `count` teams through the admin teams/players API — the fastest real path.
 * Captains are the given users (by their linked player), else fresh player
 * users; each team gets a full roster from the tournament's team format unless
 * `players: false`. Team avg SR descends with the index, so team 0 is the top seed.
 */
export async function seedTeams(
  api: Api,
  tournamentId: number,
  count: number,
  opts: { captains?: TestUser[]; players?: boolean; prefix?: string } = {}
): Promise<SeededTeam[]> {
  if (opts.captains) expect(opts.captains.length, "one captain per team").toBe(count);
  const slots = opts.players === false ? [] : await rosterSlots(api, tournamentId);
  const tag = uniq(opts.prefix ?? "Team").slice(-4);
  const teams: SeededTeam[] = [];
  for (let i = 0; i < count; i++) {
    const name = `${opts.prefix ?? "Team"} ${String.fromCharCode(65 + (i % 26))}${i >= 26 ? i : ""} ${tag}`;
    const captain = opts.captains?.[i];
    const captainId = captain ? await playerIdOf(captain) : (await createPlayerUser(api, `${name} cap`)).id;
    const team = await api.post<Team>("/api/v1/admin/teams", { name, tournament_id: tournamentId, captain_id: captainId }, 201);
    for (const [s, role] of slots.entries()) {
      const userId = s === 0 ? captainId : (await createPlayerUser(api, `${name} p${s}`)).id;
      await api.post(
        "/api/v1/admin/players",
        { name: s === 0 ? `${name} cap` : `${name} p${s}`, team_id: team.id, tournament_id: tournamentId, user_id: userId, role, rank: 3500 - i * 100 - s * 10 },
        201
      );
    }
    teams.push({ ...(await api.get<Team>(`/api/v1/teams/${team.id}`, { entities: "players" })), captain });
  }
  return teams;
}

export async function createPlayerUser(api: Api, name: string): Promise<{ id: number; name: string }> {
  return api.post("/api/v1/admin/users", { name: `${name} ${uniq("u").slice(2, 6)}` });
}

// ---------------------------------------------------------------- stages & bracket

export type StageItemInput = { id: number; slot: number; input_type: string; team_id: number | null };
export type StageItem = { id: number; name: string; type: string; inputs: StageItemInput[] };
export type Stage = {
  id: number;
  tournament_id: number;
  name: string;
  stage_type: StageType;
  node_id: number;
  status: "draft" | "ready" | "live" | "completed";
  is_published: boolean;
  items: StageItem[];
};
export type TournamentJob = {
  id: number;
  kind: "bracket" | "standings";
  status: "pending" | "running" | "succeeded" | "failed" | "superseded";
  error: string | null;
  result_json: Record<string, unknown> | null;
};
export type EncounterTeam = { id: number; slot: number; team_id: number | null; name: string; score: number; placement?: number | null };
export type Encounter = {
  id: number;
  name: string;
  round: number;
  status: "open" | "pending" | "completed";
  result_status: "none" | "pending_confirmation" | "confirmed" | "disputed";
  result_version: number;
  best_of: number;
  slot_count: number;
  stage_id: number;
  stage_item_id: number;
  teams: EncounterTeam[];
};

/**
 * A stage seeded with `teamIds`: one item (`groups` items for group stages),
 * bracket types on a `single_bracket`, the rest on `group` — what the admin
 * stage editor creates by default.
 */
export async function createStage(
  api: Api,
  tournamentId: number,
  teamIds: number[],
  opts: { stageType?: StageType; name?: string; bestOf?: number; groups?: number; order?: number; extra?: Record<string, unknown> } = {}
): Promise<Stage> {
  const stageType = opts.stageType ?? "round_robin";
  const stage = await api.post<Stage>(
    `/api/v1/admin/stages/tournament/${tournamentId}`,
    { name: opts.name ?? stageType, stage_type: stageType, best_of: { default: opts.bestOf ?? 3 }, order: opts.order ?? 0, ...opts.extra },
    201
  );
  const bracket = stageType === "single_elimination" || stageType === "double_elimination";
  const groups = bracket ? 1 : (opts.groups ?? 1);
  for (let g = 0; g < groups; g++) {
    await api.post(
      `/api/v1/admin/stages/${stage.id}/items`,
      { name: bracket ? "Bracket" : `Group ${String.fromCharCode(65 + g)}`, type: bracket ? "single_bracket" : "group", order: g },
      201
    );
  }
  return api.post<Stage>(`/api/v1/admin/stages/${stage.id}/seed-teams`, { team_ids: teamIds, mode: "snake_sr" });
}

/** Polls a tournament computation job (bracket generation, standings) to a terminal state; fails on `failed`. */
export async function waitForJob(api: Api, job: Pick<TournamentJob, "id">, timeoutMs = 60_000): Promise<TournamentJob> {
  const done = await poll(
    async () => {
      const j = await api.get<TournamentJob>(`/api/v1/admin/tournament-jobs/${job.id}`);
      return j.status === "pending" || j.status === "running" ? undefined : j;
    },
    `tournament job ${job.id}`,
    timeoutMs
  );
  expect(done.status, `tournament job ${job.id} ${done.kind}: ${done.error}`).toBe("succeeded");
  return done;
}

/** Moves a stage's node one step (`POST /admin/flow-nodes/{id}/transition`); `ready → live` generates the matches when there are none. */
export async function transitionStage(api: Api, stageId: number, status: "draft" | "ready" | "live" | "completed"): Promise<unknown> {
  const stage = await api.get<Stage>(`/api/v1/admin/stages/${stageId}`);
  return api.post(`/api/v1/admin/flow-nodes/${stage.node_id}/transition`, { status });
}

/** `draft → ready → live`: the stage goes live/published with its encounters. */
export async function startStage(api: Api, stage: Pick<Stage, "node_id">): Promise<void> {
  for (const status of ["ready", "live"]) await transitionNode(api, stage.node_id, status);
}

/** Duels by default; the list answers `slot_count = 2` only, so an FFA lobby needs its seat count. */
export async function listEncounters(api: Api, tournamentId: number, stageId?: number, slotCount?: number): Promise<Encounter[]> {
  const page = await api.get<{ results: Encounter[] }>("/api/v1/encounters", {
    tournament_id: tournamentId,
    stage_id: stageId,
    slot_count: slotCount,
    per_page: 100,
  });
  return page.results.sort((a, b) => a.round - b.round || a.id - b.id);
}

export type EncounterResult = { id: number; status: string; result_status: string; teams: { encounter_team_id: number; score: number; placement?: number | null }[] };

/** Organizer result entry: scores in slot order (`[home, away]`). */
export async function setResult(api: Api, encounter: Pick<Encounter, "id" | "teams">, scores: number[], reason = "e2e result") {
  const seats = [...encounter.teams].sort((a, b) => a.slot - b.slot);
  return api.post<EncounterResult>(`/api/v1/admin/encounters/${encounter.id}/result`, {
    reason,
    results: seats.map((seat, i) => ({ encounter_team_id: seat.id, score: scores[i] ?? 0 })),
  });
}

export type StandingRow = {
  id: number;
  team_id: number;
  stage_id: number;
  stage_item_id: number;
  position: number;
  overall_position: number;
  matches: number;
  win: number;
  draw: number;
  lose: number;
  points: number;
};

/** Recalculate (202 + job) and read the public standings, ordered by position. */
export async function recalcStandings(api: Api, tournamentId: number): Promise<StandingRow[]> {
  await waitForJob(api, await api.post<TournamentJob>(`/api/v1/admin/standings/recalculate/${tournamentId}`, undefined, 202));
  const rows = await api.get<StandingRow[]>(`/api/v1/tournaments/${tournamentId}/standings`);
  return rows.sort((a, b) => a.stage_id - b.stage_id || a.stage_item_id - b.stage_item_id || a.position - b.position);
}

export type BracketSeed = {
  workspace: Workspace;
  tournament: Tournament;
  teams: SeededTeam[];
  stage: Stage;
  encounters: Encounter[];
};

/**
 * A tournament in a fresh workspace with a generated, published stage: the teams are formed (`formTeams`) and the
 * stage started, so the tournament derives `live`. `captains` (real users) become the team captains and fix the team count.
 */
export async function seedBracket(
  api: Api,
  opts: {
    discipline?: Discipline;
    teams?: number;
    stageType?: StageType;
    captains?: TestUser[];
    bestOf?: number;
    players?: boolean;
    tournament?: Partial<{ name: string; is_league: boolean; team_formation: string; is_hidden: boolean }>;
    stage?: Record<string, unknown>;
  } = {}
): Promise<BracketSeed> {
  const discipline = opts.discipline ?? "overwatch";
  const stageType = opts.stageType ?? "single_elimination";
  const count = opts.captains?.length ?? opts.teams ?? 4;
  const workspace = await createWorkspace(api);
  if (discipline !== "overwatch") {
    await api.patch(`/api/v1/workspaces/${workspace.id}`, { disciplines_enabled: ["overwatch", discipline] });
  }
  const tournament = await createTournament(api, workspace.id, { discipline, ...opts.tournament });
  const teams = await seedTeams(api, tournament.id, count, { captains: opts.captains, players: opts.players });
  await formTeams(api, tournament.id);
  const created = await createStage(
    api,
    tournament.id,
    teams.map((t) => t.id),
    { stageType, bestOf: opts.bestOf, extra: opts.stage }
  );
  await startStage(api, created);
  const stage = await api.get<Stage>(`/api/v1/admin/stages/${created.id}`);
  const encounters = await listEncounters(api, tournament.id, stage.id, stageType === "ffa_league" ? count : undefined);
  expect(encounters.length, `${stageType} generated encounters`).toBeGreaterThan(0);
  return {
    workspace,
    tournament: await api.get<Tournament>(`/api/v1/tournaments/${tournament.id}`),
    teams,
    stage,
    encounters,
  };
}
