import { DEFAULT_WORKSPACE_TIMEZONE } from "@/lib/workspace/timezone";
import { useWorkspaceStore } from "@/stores/workspace.store";

/** IANA zone of the workspace in scope (the hub syncs it to the tournament's); times are stored in UTC and edited in this zone. */
export function useWorkspaceTimezone(): string {
  return useWorkspaceStore((state) => state.getCurrentWorkspace()?.timezone) ?? DEFAULT_WORKSPACE_TIMEZONE;
}
