/**
 * Route guards for the tournament hub.
 *
 * Pure predicates: a tab the caller may not open is hidden from the tab bar
 * AND bounced to `overview` by the shell — a hidden tab that is still
 * reachable by URL is the bug this shape prevents.
 *
 * Tabs are the tournament's lifecycle, nothing else. Configuration used to
 * occupy three of them (`pickBan`, `links`, and the report form hidden under
 * `matches`); it is now sections of `settings`.
 */
export const TAB_KEYS = [
  "overview",
  "registration",
  "teams",
  "bracket",
  "matches",
  "settings"
] as const;

export type TabKey = (typeof TAB_KEYS)[number];

/**
 * Segments that are no longer tabs but whose routes still exist until the WU
 * that moves them lands (`logs` is already a matches sub-tab).
 *
 * Listed so the shell resolves such a path to "no tab" instead of silently
 * treating it as `overview` and rendering the wrong page under a highlighted
 * Overview tab. Each entry goes with the route it names.
 */
export const LEGACY_TAB_SEGMENTS = ["logs"] as const;

export type LegacyTabSegment = (typeof LEGACY_TAB_SEGMENTS)[number];

export function isTabKey(value: string): value is TabKey {
  return (TAB_KEYS as readonly string[]).includes(value);
}

export function isLegacyTabSegment(value: string): value is LegacyTabSegment {
  return (LEGACY_TAB_SEGMENTS as readonly string[]).includes(value);
}

/**
 * Sub-tabs of `registration`. `entries` is the landing segment.
 *
 * `teams` exists only on a tournament that forms its teams by registration —
 * it used to be a Radix `Tabs` switcher inside `entries`, which is neither the
 * admin's one tab implementation nor linkable. The layout hides it (and bounces
 * its URL) for every other formation mode.
 */
export const REGISTRATION_SUB_TABS = ["entries", "teams", "form", "feed", "rank-autofill"] as const;
export type RegistrationSubTab = (typeof REGISTRATION_SUB_TABS)[number];

/** Sub-tabs of `teams`. `draft` exists only when the tournament drafts. */
export const TEAMS_SUB_TABS = ["roster", "draft"] as const;
export type TeamsSubTab = (typeof TEAMS_SUB_TABS)[number];

/** Sub-tabs of `matches`. `results` split into `encounters` + `standings`. */
export const MATCHES_SUB_TABS = [
  "encounters",
  "standings",
  "reports",
  "parsed",
  "logs"
] as const;
export type MatchesSubTabKey = (typeof MATCHES_SUB_TABS)[number];

/** Sections of `settings`, in navigation order (F9 ·1). */
export const SETTINGS_SECTIONS = [
  "general",
  "rules",
  "schedule",
  "roster",
  "pre-game",
  "report-form",
  "links",
  "challonge",
  "discord",
  "preview",
  "danger"
] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];

export interface TabAccess {
  canUpdateTournament: boolean;
  canUpdateEncounter: boolean;
  canTeamRead: boolean;
  canReadTournamentLink: boolean;
  canDeleteTournament: boolean;
  teamFormation: "balancer" | "draft";
}

export function allowedTab(tab: TabKey, p: TabAccess): boolean {
  switch (tab) {
    case "settings":
      return p.canUpdateTournament;
    case "registration":
      return p.canTeamRead;
    default:
      return true;
  }
}

export function allowedTeamsSubTab(tab: TeamsSubTab, p: TabAccess): boolean {
  return tab === "draft" ? p.teamFormation === "draft" : true;
}

/**
 * The configuration sections keep the permission of the tab they came from:
 * pre-game was gated on `match.update`, links on `tournament_link.read`, and
 * deleting the tournament is its own grant. Everything else is the tab's own
 * `tournament.update`, which `allowedTab` already required to get here.
 */
export function allowedSettingsSection(section: SettingsSection, p: TabAccess): boolean {
  switch (section) {
    case "pre-game":
      return p.canUpdateEncounter;
    case "links":
      return p.canReadTournamentLink;
    case "danger":
      return p.canDeleteTournament;
    default:
      return p.canUpdateTournament;
  }
}
