import { describe, expect, it } from "vitest";

import { summarizeFormat, summarizeStageWaves } from "@/lib/flow/formatSummary";
import type { FlowRead } from "@/types/flow.types";

type N = [id: number, kind: string, config?: Record<string, unknown>, status?: string];

/** A flow from `[id, kind, config, status]` nodes and `[from, to]` edges; a stage node `n` owns stage `n * 10`. */
const flow = (
  nodes: N[],
  edges: [number, number][],
  items: [node: number, item: number][] = []
): FlowRead =>
  ({
    nodes: nodes.map(([id, kind, config = {}, status = "draft"]) => ({
      id,
      kind,
      name: `${kind} ${id}`,
      status,
      config,
      stage_id: kind === "stage" ? id * 10 : null,
      ports: []
    })),
    edges: edges.map(([source_node_id, target_node_id], id) => ({
      id,
      source_node_id,
      source_port: "out",
      target_node_id,
      target_port: "in"
    })),
    results: items.map(([node_id, stage_item_id]) => ({ node_id, port: "ranking", stage_item_id })),
    participants: []
  }) as unknown as FlowRead;

const names = (summary: ReturnType<typeof summarizeFormat>) =>
  summary.steps.map((s) => s.stages.map((x) => x.name));

describe("summarizeFormat", () => {
  it("reads a single stage as one step with the sign-up line", () => {
    const summary = summarizeFormat(
      flow(
        [
          [1, "registration", { intake: "solo" }],
          [2, "formation", { mode: "balancer" }],
          [3, "stage"]
        ],
        [
          [1, 2],
          [2, 3]
        ]
      )
    );

    expect(summary.intro).toEqual({ intake: "solo", formation: "balancer" });
    expect(summary.steps).toHaveLength(1);
    expect(summary.steps[0]).toMatchObject({ transitions: [], league: null, state: "upcoming" });
  });

  it("puts groups -> per-group filter -> playoff in two steps with the filter between", () => {
    const summary = summarizeFormat(
      flow(
        [
          [1, "registration"],
          [2, "formation", { mode: "registered" }],
          [3, "stage", {}, "completed"],
          [4, "filter", { mode: "per_item_top", n: 2, upper: 1 }],
          [5, "stage", {}, "live"]
        ],
        [
          [1, 2],
          [2, 3],
          [3, 4],
          [4, 5]
        ],
        [
          [3, 100],
          [3, 101]
        ]
      )
    );

    expect(names(summary)).toEqual([["stage 3"], ["stage 5"]]);
    expect(summary.steps[1]!.transitions).toEqual([
      { kind: "perItemTop", n: 2, upper: 1, grouped: true }
    ]);
    expect(summary.steps.map((s) => s.state)).toEqual(["done", "current"]);
  });

  it("does not say per group for a per-item filter on a stage with one item", () => {
    const nodes: N[] = [
      [1, "stage"],
      [2, "filter", { mode: "per_item_top", n: 4 }],
      [3, "stage"]
    ];
    const edges: [number, number][] = [
      [1, 2],
      [2, 3]
    ];
    const one = summarizeFormat(
      flow(nodes, edges, [
        [1, 100],
        [1, 100]
      ])
    );
    const unknown = summarizeFormat(flow(nodes, edges));

    expect(one.steps[1]!.transitions).toEqual([
      { kind: "perItemTop", n: 4, upper: null, grouped: false }
    ]);
    expect(unknown.steps[1]!.transitions).toEqual([
      { kind: "perItemTop", n: 4, upper: null, grouped: false }
    ]);
  });

  it("reads individual swiss -> top 20 -> draft formation -> playoff as a filter then a re-formation", () => {
    const summary = summarizeFormat(
      flow(
        [
          [1, "registration", { intake: "solo" }],
          [2, "formation", { mode: "balancer" }],
          [3, "stage"],
          [4, "filter", { mode: "top", n: 20 }],
          [5, "formation", { mode: "draft" }],
          [6, "stage"]
        ],
        [
          [1, 2],
          [2, 3],
          [3, 4],
          [4, 5],
          [5, 6]
        ]
      )
    );

    // The formation before the swiss belongs to the intro line, not to a transition.
    expect(summary.intro).toEqual({ intake: "solo", formation: "balancer" });
    expect(summary.steps[1]!.transitions).toEqual([
      { kind: "top", n: 20 },
      { kind: "reform", mode: "draft" }
    ]);
  });

  it("collapses an 8-day league into one step with its rule, then the stages after the leaderboard", () => {
    const days = [1, 2, 3, 4, 5, 6, 7, 8];
    const summary = summarizeFormat(
      flow(
        [
          ...days.map((d): N => [d, "stage", {}, "completed"]),
          [
            20,
            "aggregate",
            {
              unit: "players",
              score: { preset: "formula", formula: "wins" },
              mode: "sum_best_n",
              n: 3
            }
          ],
          [21, "leaderboard"],
          [22, "filter", { mode: "top", n: 8 }],
          [23, "stage", {}, "live"]
        ],
        [...days.map((d): [number, number] => [d, 20]), [20, 21], [21, 22], [22, 23]]
      )
    );

    expect(summary.steps).toHaveLength(2);
    expect(summary.steps[0]!.stages).toHaveLength(8);
    expect(summary.steps[0]!.league!.rule.mode).toEqual({ key: "sumBestN", n: 3 });
    expect(summary.steps[0]!.league!.rule.score.formula).toBe("wins");
    expect(summary.steps[0]!.state).toBe("done");
    expect(summary.steps[1]).toMatchObject({
      state: "current",
      transitions: [{ kind: "top", n: 8 }]
    });
  });

  it("puts the divisions of a split in one step under a split line", () => {
    const summary = summarizeFormat(
      flow(
        [
          [1, "stage"],
          [2, "split", { buckets: [{ name: "High" }, { name: "Low" }] }],
          [3, "stage"],
          [4, "stage"]
        ],
        [
          [1, 2],
          [2, 3],
          [2, 4]
        ]
      )
    );

    expect(summary.steps).toHaveLength(2);
    expect(summary.steps[1]!.stages).toHaveLength(2);
    expect(summary.steps[1]!.transitions).toEqual([{ kind: "split", buckets: ["High", "Low"] }]);
  });

  it("has no intro without a registration node, and shows no team intake word for registered teams", () => {
    expect(summarizeFormat(flow([[1, "stage"]], [])).intro).toBeNull();
    expect(
      summarizeFormat(
        flow(
          [
            [1, "registration", { intake: "team" }],
            [2, "formation", { mode: "registered" }]
          ],
          [[1, 2]]
        )
      ).intro
    ).toEqual({ intake: "team", formation: null });
  });
});

describe("summarizeStageWaves", () => {
  it("keeps the stage waves and marks the first unfinished one as current", () => {
    const summary = summarizeStageWaves([
      [{ id: 1, name: "A", status: "completed" }],
      [
        { id: 2, name: "B", status: "draft" },
        { id: 3, name: "C", status: "draft" }
      ]
    ]);

    expect(summary.intro).toBeNull();
    expect(summary.steps.map((s) => [s.stages.length, s.state])).toEqual([
      [1, "done"],
      [2, "current"]
    ]);
  });
});
