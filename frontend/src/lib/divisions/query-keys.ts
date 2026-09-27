import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for division grids: the grid list, its versions, the readiness report and
 * the cross-workspace importer. The `*All` entries are the bare prefixes the
 * draft editor drops after a publish, when every scoped variant is stale.
 */
export const divisionGridQueryKeys = {
  importGrids: (workspaceId: KeyPart, sourceWorkspaceId: KeyPart) =>
    ["division-grid-import-grids", workspaceId, sourceWorkspaceId] as const,
  importJob: (workspaceId: KeyPart, jobId: KeyPart) =>
    ["division-grid-import-job", workspaceId, jobId] as const,
  importPreflight: (workspaceId: KeyPart, request: unknown) =>
    ["division-grid-import-preflight", workspaceId, request] as const,
  importWorkspaces: (workspaceId: KeyPart) =>
    ["division-grid-import-workspaces", workspaceId] as const,
  mapping: (sourceVersionId: KeyPart, versionId: KeyPart) =>
    ["division-grid-mapping", sourceVersionId, versionId] as const,
  mappingAll: () => ["division-grid-mapping"] as const,
  readiness: (workspaceId: KeyPart, versionId: KeyPart) =>
    ["division-grid-readiness", workspaceId, versionId] as const,
  readinessByWorkspace: (workspaceId: KeyPart) =>
    ["division-grid-readiness", workspaceId] as const,
  readinessAll: () => ["division-grid-readiness"] as const,
  version: (versionId: KeyPart) => ["division-grid-version", versionId] as const,
  versions: (workspaceId: KeyPart, gridId: KeyPart) =>
    ["division-grid-versions", workspaceId, gridId] as const,
  versionsByWorkspace: (workspaceId: KeyPart) => ["division-grid-versions", workspaceId] as const,
  versionsAll: () => ["division-grid-versions"] as const,
  grids: (workspaceId: KeyPart) => ["division-grids", workspaceId] as const,
  gridsAll: () => ["division-grids"] as const,
};
