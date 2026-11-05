import { apiFetch } from "@/lib/api/fetch";
import type { FlowChanges, FlowRead } from "@/types/flow.types";

const flowService = {
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
