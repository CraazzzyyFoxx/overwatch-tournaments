import type { Tone } from "@/components/kit/tone";
import type { DivisionGridVersion } from "@/types/workspace.types";

/**
 * What a version is, as the user sees it.
 *
 * The backend stores three statuses — `draft`, `published`, `archived` — and
 * "active" is not one of them: it is the workspace pointing
 * `default_division_grid_version_id` at a published version. The strip has to
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

export const VERSION_STATE_TONE: Record<VersionState, Tone> = {
  archived: "neutral",
  published: "info",
  active: "success",
  draft: "warning"
};
