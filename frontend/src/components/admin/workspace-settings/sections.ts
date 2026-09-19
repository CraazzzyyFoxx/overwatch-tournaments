import type { AdminSectionNavGroup } from "@/components/kit/AdminSectionNav";

/**
 * Every section of the workspace settings hub (T5), in rail order.
 *
 * One list, so the rail, the mobile `Select` and each section's own heading
 * cannot drift apart: before the redesign these nine concerns lived in five
 * unrelated routes (`/admin/workspaces/[id]`, `/admin/divisions`,
 * `/admin/balancer`, `/admin/sub-roles`, `/admin/subscriptions`) and nothing
 * told the reader they were the same settings surface.
 */
export const WORKSPACE_SETTINGS_SECTIONS = [
  "general",
  "branding",
  "visibility",
  "domain",
  "discord",
  "divisions",
  "statuses",
  "sub-roles",
  "subscriptions",
  "quota"
] as const;

export type WorkspaceSettingsSectionKey = (typeof WORKSPACE_SETTINGS_SECTIONS)[number];

export const WORKSPACE_SETTINGS_SECTION_LABELS: Record<WorkspaceSettingsSectionKey, string> = {
  general: "General",
  branding: "Branding",
  visibility: "Visibility",
  domain: "Domain",
  discord: "Discord",
  divisions: "Divisions",
  statuses: "Player statuses",
  "sub-roles": "Sub-roles",
  subscriptions: "Subscriptions",
  quota: "Rate limits"
};

/** One sentence under the hub heading, so a section says what it decides
 * before the reader has to infer it from the controls. */
export const WORKSPACE_SETTINGS_SECTION_DESCRIPTIONS: Record<
  WorkspaceSettingsSectionKey,
  string
> = {
  general: "How this workspace is named, described and scheduled.",
  branding: "The palette the public site paints this workspace in.",
  visibility: "Who can find this workspace, and who counts as a newcomer in it.",
  domain: "The subdomain, the custom domain and the text search engines show.",
  discord: "The Discord server this workspace runs in.",
  divisions: "Rank bands players are sorted into, and the version tournaments read.",
  statuses: "Player statuses the balancer takes into account.",
  "sub-roles": "Hero sub-roles used by rosters and reports.",
  subscriptions: "Subscription providers that grant entitlements here.",
  quota: "How much this workspace, one key and one session may spend."
};

/**
 * The five sections that are a form over the workspace record itself, and so
 * exist under both shells: `/admin/settings/*` for the workspace an admin is
 * currently in, and `/admin/workspaces/[id]/*` for a superuser looking at
 * someone else's. The remaining five are workspace-scoped screens of their
 * own and only ever mount under `/admin/settings`.
 */
export const WORKSPACE_RECORD_SECTIONS = [
  "general",
  "branding",
  "visibility",
  "domain",
  "discord"
] as const satisfies readonly WorkspaceSettingsSectionKey[];

export type WorkspaceRecordSectionKey = (typeof WORKSPACE_RECORD_SECTIONS)[number];

const GROUPS: ReadonlyArray<{ label: string; sections: readonly WorkspaceSettingsSectionKey[] }> = [
  { label: "Workspace", sections: ["general", "branding", "visibility", "domain", "discord"] },
  { label: "Competitive", sections: ["divisions", "statuses", "sub-roles"] },
  { label: "Entitlements", sections: ["subscriptions", "quota"] }
];

/**
 * Rail groups for `AdminSectionNav`, with `basePath` deciding which shell they
 * point at.
 *
 * `only` narrows the rail to the sections a shell actually routes: the
 * superuser's `/admin/workspaces/[id]` shell mounts the five workspace-record
 * sections, and a link to a Divisions page that does not exist there would be
 * a 404 dressed up as navigation.
 */
export function workspaceSettingsNavGroups(
  basePath: string,
  only?: readonly WorkspaceSettingsSectionKey[]
): AdminSectionNavGroup[] {
  const allowed = only ? new Set<string>(only) : null;
  return GROUPS.map((group) => ({
    label: group.label,
    items: group.sections.map((section) => ({
      key: section,
      label: WORKSPACE_SETTINGS_SECTION_LABELS[section],
      href: `${basePath}/${section}`,
      hidden: allowed ? !allowed.has(section) : false
    }))
  }));
}
