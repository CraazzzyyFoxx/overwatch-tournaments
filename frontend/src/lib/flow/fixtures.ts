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

type Row = {
  rank: number;
  member: number;
  score: number;
  breakdown?: [node: number, place: number, score: number, counted: boolean][];
};

const resultRow = (node: number, state: string, r: Row, tieGroup: number | null = null) => ({
  node_id: node,
  port: "ranking",
  rank: r.rank,
  workspace_member_id: r.member,
  team_id: null,
  stage_item_id: null,
  item_rank: null,
  score: r.score,
  tie_group: tieGroup,
  breakdown:
    r.breakdown?.map(([node_id, place, score, counted]) => ({ node_id, place, score, counted })) ??
    null,
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
