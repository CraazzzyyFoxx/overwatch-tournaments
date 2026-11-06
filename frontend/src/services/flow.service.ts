import { apiFetch } from "@/lib/api/fetch";
import type { AdminFlowRead, FlowChanges, FlowRead, FlowValidationRead } from "@/types/flow.types";

const flowService = {
  /** The public flow graph with every node's ranked results. */
  async get(tournamentId: number): Promise<FlowRead> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/flow`);
    return response.json();
  },

  /** The admin graph: the flow plus the validator's issues, the port catalogue and the node config seeds. */
  async getAdmin(tournamentId: number): Promise<AdminFlowRead> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/flow`);
    return response.json();
  },

  /** Dry-runs a graph edit: the issues and resolved ports of every node, nothing written. */
  async validate(tournamentId: number, changes: FlowChanges): Promise<FlowValidationRead> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/flow/validate`, {
      method: "POST",
      body: changes
    });
    return response.json();
  },

  /** Applies a partial graph edit (node/edge upserts and deletes) and returns the whole graph. */
  async applyChanges(tournamentId: number, changes: FlowChanges): Promise<AdminFlowRead> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/flow`, {
      method: "PUT",
      body: changes
    });
    return response.json();
  }
};

export default flowService;
