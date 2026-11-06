import { randomUUID } from "node:crypto";
import { rememberNodes, type Api } from "./api";

export type Discipline = "overwatch" | "lol" | "deadlock" | "valorant";

export function uniq(prefix: string) {
  return `${prefix}-${randomUUID().slice(0, 8)}`;
}

export function isoDate(offsetDays = 0) {
  return new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);
}

export type Workspace = { id: number; slug: string; name: string };

/** A fresh workspace owned by `api`'s user. Scoping every spec to its own keeps runs order-independent. */
export async function createWorkspace(api: Api, name = uniq("ws")): Promise<Workspace> {
  return api.post<Workspace>("/api/v1/workspaces", { slug: name.toLowerCase(), name }, 201);
}

export type Tournament = { id: number; slug: string; name: string; status: string; workspace_id: number; discipline: string };

export async function createTournament(
  api: Api,
  workspaceId: number,
  overrides: Partial<{ discipline: Discipline; name: string; team_formation: string; is_hidden: boolean }> = {}
): Promise<Tournament> {
  return api.post<Tournament>(
    "/api/v1/admin/tournaments",
    {
      workspace_id: workspaceId,
      discipline: "overwatch",
      name: uniq("Cup"),
      start_date: isoDate(7),
      end_date: isoDate(14),
      // Tests drive the nodes explicitly; the 30 s tick must not move them under them.
      auto_transitions_enabled: false,
      ...overrides,
    },
    201
  );
}

export type FlowNodeSchedule = { phase: string; starts_at: string; ends_at: string | null };
export type TournamentFlowNode = {
  id: number;
  kind: string;
  name: string;
  status: string;
  stage_id: number | null;
  config: Record<string, unknown>;
  schedule: FlowNodeSchedule[];
};

/** The tournament's registration, formation, stage and leaderboard nodes (`?entities=flow_nodes`). */
export async function flowNodes(api: Api, tournamentId: number): Promise<TournamentFlowNode[]> {
  const t = await api.get<{ flow_nodes?: TournamentFlowNode[] }>(`/api/v1/tournaments/${tournamentId}`, { entities: "flow_nodes" });
  return t.flow_nodes ?? [];
}

/** The first node of a kind: `create_tournament` writes one registration and one formation node. */
export async function nodeOf(api: Api, tournamentId: number, kind: "registration" | "formation"): Promise<TournamentFlowNode> {
  const node = (await flowNodes(api, tournamentId)).find((candidate) => candidate.kind === kind);
  if (!node) throw new Error(`tournament ${tournamentId} has no ${kind} node`);
  rememberNodes(tournamentId, { [kind]: node.id });
  return node;
}

/** One lifecycle move of a node (`POST /admin/flow-nodes/{id}/transition`); the server refuses an illegal one. */
export async function transitionNode(api: Api, nodeId: number, status: string) {
  return api.post<TournamentFlowNode>(`/api/v1/admin/flow-nodes/${nodeId}/transition`, { status });
}

/** Archive a completed tournament, or return an archived one to completed. */
export async function setArchived(api: Api, tournamentId: number, archived: boolean) {
  return api.post<Tournament>(`/api/v1/admin/tournaments/${tournamentId}/archive`, { archived });
}
