import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { WorkspaceListItem } from "@/types/workspace.types";

/** `label` names the chip; the options are the workspaces this account can issue keys in. */
export function apiKeyFilterDefs(workspaces: readonly WorkspaceListItem[], label: string): FilterDef[] {
  return [
    {
      key: "workspace",
      label,
      kind: "single",
      options: workspaces.map((workspace) => ({
        value: String(workspace.id),
        label: workspace.name
      }))
    }
  ];
}
