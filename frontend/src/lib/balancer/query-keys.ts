import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for the balancer tool and the organizer surfaces that read its output:
 * the registration feed, the sheet importer, the rank autofill preview and the
 * per-workspace balancer configuration.
 */
export const balancerQueryKeys = {
  rankAutofillPreview: (tournamentId: KeyPart, request: unknown) =>
    ["balancer-admin", "rank-autofill-preview", tournamentId, request] as const,
  registrationForm: (tournamentId: KeyPart) =>
    ["balancer-admin", "registration-form", tournamentId] as const,
  /** The workspace's saved form templates, offered by the tournament builder. */
  registrationFormTemplates: (workspaceId: KeyPart) =>
    ["admin", "registration-form-templates", workspaceId] as const,
  registrations: (tournamentId: KeyPart) =>
    ["balancer-admin", "registrations", tournamentId] as const,
  sheetCatalog: (tournamentId: KeyPart) =>
    ["balancer-admin", "sheet-catalog", tournamentId] as const,
  sheet: (tournamentId: KeyPart) => ["balancer-admin", "sheet", tournamentId] as const,
  statusCatalog: (workspaceId: KeyPart) =>
    ["balancer-admin", "status-catalog", workspaceId] as const,
  tournamentConfig: (tournamentId: KeyPart) =>
    ["balancer-admin", "tournament-config", tournamentId] as const,
  publicBalance: (tournamentId: KeyPart) => ["balancer-public", "balance", tournamentId] as const,
  publicConfig: () => ["balancer-public", "config"] as const,
  draftSetupPool: (tournamentId: KeyPart) =>
    ["balancer", "draft-setup-pool", tournamentId] as const,
  tournamentSummary: (tournamentId: KeyPart) =>
    ["balancer", "tournament", tournamentId, "summary"] as const,
  workspaceConfig: (workspaceId: KeyPart) => ["workspace-balancer-config", workspaceId] as const,
};
