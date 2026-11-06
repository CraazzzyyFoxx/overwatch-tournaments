import { apiFetch } from "@/lib/api/fetch";
import type { FlowChanges, FlowRead } from "@/types/flow.types";

const flowService = {
  /** The public flow graph with every node's ranked results. */
  async get(tournamentId: number): Promise<FlowRead> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/flow`);
    return response.json();
  },

  /** Applies a partial graph edit (node/edge upserts and deletes) and returns the whole graph. */
  async applyChanges(tournamentId: number, changes: FlowChanges): Promise<FlowRead> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/flow`, {
      method: "PUT",
      body: changes
    });
    return response.json();
  }
};

export default flowService;
