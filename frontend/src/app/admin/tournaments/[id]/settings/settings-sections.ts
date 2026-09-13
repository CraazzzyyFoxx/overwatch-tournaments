import type { SettingsSection } from "../tab-guards";

/**
 * Human name of every settings section, and the groups the rail shows them in
 * (F9 ·1).
 *
 * Pure data so the rail, the mobile `Select` and the section headings all read
 * one list: the pre-redesign hub had the same four concerns spelled out once in
 * the tab bar and again inside a 714-line form.
 */
export const SETTINGS_SECTION_LABELS: Record<SettingsSection, string> = {
  general: "General",
  rules: "Rules & scoring",
  schedule: "Schedule",
  roster: "Roster shape",
  registration: "Registration",
  admission: "Admission",
  "pre-game": "Pre-game phase",
  "report-form": "Match report form",
  links: "Links",
  challonge: "Challonge",
  discord: "Discord",
  preview: "Preview allowlist",
  danger: "Delete tournament"
};

/**
 * Sections in rail order. `undefined` label = the leading, unheaded group.
 *
 * Audit trail is deliberately absent: it is a drawer the whole admin shares
 * (`AuditTrailProvider`), not a page of its own.
 */
export const SETTINGS_SECTION_GROUPS: ReadonlyArray<{
  label?: string;
  sections: readonly SettingsSection[];
}> = [
  { sections: ["general", "rules", "schedule", "roster"] },
  // The registration form used to hold all of this INSIDE the questionnaire
  // builder, under six groups whose titles had to be written with "and".
  // Splitting it in two names the two questions being answered: how entries are
  // taken and what the public sees, versus who is allowed in.
  { label: "Registration", sections: ["registration", "admission"] },
  { label: "Play", sections: ["pre-game", "report-form", "links"] },
  { label: "Integrations", sections: ["challonge", "discord"] },
  { label: "Access", sections: ["preview"] },
  { label: "Danger", sections: ["danger"] }
];
