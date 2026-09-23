import type { RegistrationTeam, RegistrationTeamStatus } from "@/types/registration-team.types";

export function getRegistrationTeamStatus(
  team: Pick<RegistrationTeam, "status" | "exported_team_id">,
): RegistrationTeamStatus | "exported" {
  return team.exported_team_id != null && (team.status === "forming" || team.status === "complete")
    ? "exported"
    : team.status;
}

export const REGISTRATION_TEAM_STATUS_TONE: Record<RegistrationTeamStatus | "exported", string> = {
  forming:
    "border-[color:var(--aqt-amber)]/40 bg-[color:var(--aqt-amber)]/10 text-[color:var(--aqt-amber)]",
  complete:
    "border-[color:var(--aqt-teal)]/40 bg-[color:var(--aqt-teal)]/10 text-[color:var(--aqt-teal)]",
  exported:
    "border-[color:var(--aqt-emerald)]/40 bg-[color:var(--aqt-emerald)]/10 text-[color:var(--aqt-emerald)]",
  rejected:
    "border-[color:var(--aqt-rose)]/40 bg-[color:var(--aqt-rose)]/10 text-[color:var(--aqt-rose)]",
  disbanded:
    "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-dim)]"
};
