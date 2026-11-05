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
  /** One game's templates (`"all"`: every game's); prefixed by `registrationFormTemplates` for invalidation. */
  registrationFormTemplateList: (workspaceId: KeyPart, discipline: string | null) =>
    ["admin", "registration-form-templates", workspaceId, discipline ?? "all"] as const,
  registrations: (tournamentId: KeyPart) =>
    ["balancer-admin", "registrations", tournamentId] as const,
  sheetCatalog: (tournamentId: KeyPart) =>
    ["balancer-admin", "sheet-catalog", tournamentId] as const,
  sheet: (tournamentId: KeyPart) => ["balancer-admin", "sheet", tournamentId] as const,
  statusCatalog: (workspaceId: KeyPart) =>
    ["balancer-admin", "status-catalog", workspaceId] as const,
  /** One formation node's config; without the node, the prefix every node of the tournament sits under. */
  tournamentConfig: (tournamentId: KeyPart, formationNodeId?: KeyPart) =>
    formationNodeId === undefined
      ? (["balancer-admin", "tournament-config", tournamentId] as const)
      : (["balancer-admin", "tournament-config", tournamentId, formationNodeId] as const),
  /** One formation node's saved balance; without the node, the prefix every node of the tournament sits under. */
  publicBalance: (tournamentId: KeyPart, formationNodeId?: KeyPart) =>
    formationNodeId === undefined
      ? (["balancer-public", "balance", tournamentId] as const)
      : (["balancer-public", "balance", tournamentId, formationNodeId] as const),
  /** The public solver config of one game: its role weights are that game's. */
  publicConfig: (discipline: KeyPart) => ["balancer-public", "config", discipline] as const,
  draftSetupPool: (tournamentId: KeyPart) =>
    ["balancer", "draft-setup-pool", tournamentId] as const,
  tournamentSummary: (tournamentId: KeyPart) =>
    ["balancer", "tournament", tournamentId, "summary"] as const,
  workspaceConfig: (workspaceId: KeyPart) => ["workspace-balancer-config", workspaceId] as const,
  /** The workspace's ranker settings, saved and rebuilt apart from the config above. */
  workspaceRanker: (workspaceId: KeyPart) => ["workspace-balancer-ranker", workspaceId] as const,
};
