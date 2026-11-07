import type { FlowRead } from "@/types/flow.types";

export const port = (
  name: string,
  direction: "in" | "out",
  unit: "players" | "teams" | null,
  multi = false
) => ({
  name,
  direction,
  multi,
  unit
});

/** The flow `create_tournament` writes: registration 1 → formation 2 over edge 10. */
export const starterRead = (over: { regStatus?: string; formStatus?: string } = {}): FlowRead =>
  ({
    nodes: [
      {
        id: 1,
        kind: "registration",
        name: "Registration",
        status: over.regStatus ?? "draft",
        config: { check_in: false },
        stage_id: null,
        position_x: 0,
        position_y: 0,
        started_at: null,
        completed_at: null,
        ports: [port("participants", "out", "players")]
      },
      {
        id: 2,
        kind: "formation",
        name: "Teams",
        status: over.formStatus ?? "draft",
        config: { mode: "balancer" },
        stage_id: null,
        position_x: 260,
        position_y: 0,
        started_at: null,
        completed_at: null,
        ports: [port("players", "in", "players"), port("teams", "out", "teams")]
      }
    ],
    edges: [
      {
        id: 10,
        source_node_id: 1,
        source_port: "participants",
        target_node_id: 2,
        target_port: "players"
      }
    ],
    results: [],
    participants: []
  }) as unknown as FlowRead;

type Extra = Partial<{
  role: string | null;
  team_id: number | null;
  wins: number;
  draws: number;
  losses: number;
  buchholz: number;
}>;
type Row = {
  rank: number;
  member: number;
  score: number;
  /** The rated role the row ranks under (by-role aggregates and the leaderboard they feed). */
  role?: string | null;
  breakdown?: [node: number, place: number, score: number, counted: boolean, extra?: Extra][];
};

const resultRow = (node: number, state: string, r: Row, tieGroup: number | null = null) => ({
  node_id: node,
  port: "ranking",
  rank: r.rank,
  role: r.role ?? null,
  workspace_member_id: r.member,
  team_id: null,
  stage_item_id: null,
  item_rank: null,
  score: r.score,
  tie_group: tieGroup,
  breakdown:
    r.breakdown?.map(([node_id, place, score, counted, extra]) => ({
      node_id,
      place,
      score,
      counted,
      ...extra
    })) ?? null,
  state
});

const leagueNode = (
  id: number,
  kind: string,
  name: string,
  status: string,
  config: Record<string, unknown> = {},
  stageId: number | null = null
) => ({
  id,
  kind,
  name,
  status,
  config,
  stage_id: stageId,
  position_x: 0,
  position_y: 0,
  started_at: null,
  completed_at: null,
  ports: []
});

/**
 * Three played days → aggregate 20 (best 2 of 3) → leaderboard 21; members 1 Ann, 2 Bob, 3 Cid.
 * `feed` wires the leaderboard straight from that stage node; `ties` maps member id → leaderboard tie group.
 */
export const leagueFlow = (
  over: { ties?: Record<number, number>; feed?: number; state?: "tentative" | "final" } = {}
): FlowRead => {
  const state = over.state ?? "final";
  const aggregate: Row[] = [
    {
      rank: 1,
      member: 1,
      score: 9,
      breakdown: [
        [11, 1, 3, true],
        [12, 1, 3, true],
        [13, 1, 3, false]
      ]
    },
    {
      rank: 2,
      member: 2,
      score: 6,
      breakdown: [
        [11, 2, 0, false],
        [12, 1, 3, true],
        [13, 1, 3, true]
      ]
    },
    { rank: 3, member: 3, score: 3, breakdown: [[11, 1, 3, true]] }
  ];
  const board: Row[] = over.feed
    ? [
        { rank: 1, member: 1, score: 3 },
        { rank: 2, member: 2, score: 3 },
        { rank: 3, member: 3, score: 0 }
      ]
    : aggregate.map((r) => ({ ...r, breakdown: undefined }));
  return {
    nodes: [
      leagueNode(11, "stage", "Day 1", "completed", {}, 31),
      leagueNode(12, "stage", "Day 2", "completed", {}, 32),
      leagueNode(13, "stage", "Day 3", "completed", {}, 33),
      leagueNode(20, "aggregate", "Season", state, {
        unit: "players",
        score: { preset: "stage_points" },
        mode: "sum_best_n",
        n: 2
      }),
      leagueNode(21, "leaderboard", "Season table", state, {})
    ],
    edges: [
      [31, 11, 20],
      [32, 12, 20],
      [33, 13, 20],
      [34, over.feed ?? 20, 21]
    ].map(([id, source, target]) => ({
      id,
      source_node_id: source,
      source_port: "ranking",
      target_node_id: target,
      target_port: target === 20 ? "inputs" : "ranking"
    })),
    results: [
      ...aggregate.map((r) => resultRow(20, state, r)),
      ...board.map((r) => resultRow(21, state, r, over.ties?.[r.member] ?? null))
    ],
    participants: [
      { workspace_member_id: 1, team_id: null, name: "Ann" },
      { workspace_member_id: 2, team_id: null, name: "Bob" },
      { workspace_member_id: 3, team_id: null, name: "Cid" }
    ]
  } as unknown as FlowRead;
};

/**
 * Two team-swiss days → by-role aggregate 20 → leaderboard 21. Ann played tank on day 1 and damage on day 2, so she
 * ranks in both roles; Ann and Bob tie for tank place 1; Cid has no role. Team 100 is "Rockets".
 */
export const roleFlow = (): FlowRead => {
  const tank = { role: "tank" };
  const rows: (Row & { tie?: number })[] = [
    {
      rank: 1,
      member: 1,
      score: 6,
      role: "tank",
      tie: 1,
      breakdown: [[11, 1, 6, true, { ...tank, team_id: 100, wins: 3, draws: 0, losses: 1, buchholz: 7 }]]
    },
    {
      rank: 2,
      member: 2,
      score: 6,
      role: "tank",
      tie: 1,
      breakdown: [[12, 2, 6, true, { ...tank, team_id: 100 }]]
    },
    {
      rank: 1,
      member: 1,
      score: 4,
      role: "damage",
      breakdown: [[12, 3, 4, true, { role: "damage", team_id: 100, wins: 2, draws: 1, losses: 1 }]]
    },
    { rank: 1, member: 3, score: 2, role: null, breakdown: [[11, 4, 2, true]] }
  ];
  return {
    nodes: [
      leagueNode(11, "stage", "Day 1", "completed", {}, 31),
      leagueNode(12, "stage", "Day 2", "completed", {}, 32),
      leagueNode(20, "aggregate", "Season", "final", {
        unit: "players",
        by_role: true,
        score: { preset: "stage_points" },
        mode: "sum_all",
        n: null
      }),
      leagueNode(21, "leaderboard", "Season table", "final", {})
    ],
    edges: [
      [31, 11, 20],
      [32, 12, 20],
      [33, 20, 21]
    ].map(([id, source, target]) => ({
      id,
      source_node_id: source,
      source_port: "ranking",
      target_node_id: target,
      target_port: target === 20 ? "inputs" : "ranking"
    })),
    results: [
      ...rows.map((r) => resultRow(20, "final", r)),
      ...rows.map((r) => resultRow(21, "final", { ...r, breakdown: undefined }, r.tie ?? null))
    ],
    participants: [
      { workspace_member_id: 1, team_id: null, name: "Ann" },
      { workspace_member_id: 2, team_id: null, name: "Bob" },
      { workspace_member_id: 3, team_id: null, name: "Cid" },
      { workspace_member_id: null, team_id: 100, name: "Rockets" }
    ]
  } as unknown as FlowRead;
};
