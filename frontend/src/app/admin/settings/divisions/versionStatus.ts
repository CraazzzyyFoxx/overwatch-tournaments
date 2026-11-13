import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import type { DivisionGridVersion } from "@/types/workspace.types";

/**
 * What a version is, as the user sees it.
 *
 * The backend stores three statuses — `draft`, `published`, `archived` — and
 * "active" is not one of them: it is the workspace's explicit selection for the
 * grid's discipline in `default_division_grid_versions`. The strip has to
 * show four states, so the fourth is derived here, once, instead of at each
 * call site.
 */
export type VersionState = "draft" | "published" | "active" | "archived";

export function versionState(
  version: DivisionGridVersion,
  activeVersionId: number | null
): VersionState {
  if (version.id === activeVersionId) return "active";
  if (version.status === "draft") return "draft";
  if (version.status === "archived") return "archived";
  return "published";
}

/**
 * The pill a version state earns. Only the two that want attention get one:
 * published is the norm on a version list and archived is already dimmed.
 */
export const VERSION_PILL: Partial<
  Record<VersionState, { tone: Tone; key: "versionState.draft" | "versionState.active" }>
> = {
  draft: { tone: "warning", key: "versionState.draft" },
  active: { tone: "success", key: "versionState.active" }
};
