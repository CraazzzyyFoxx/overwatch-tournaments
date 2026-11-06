import type { FlowRead } from "@/types/flow.types";

export const port = (name: string, direction: "in" | "out", unit: "players" | "teams" | null, multi = false) => ({
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
    edges: [{ id: 10, source_node_id: 1, source_port: "participants", target_node_id: 2, target_port: "players" }],
    results: [],
    participants: []
  }) as unknown as FlowRead;
