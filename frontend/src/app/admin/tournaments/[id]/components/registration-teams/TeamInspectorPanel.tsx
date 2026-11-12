"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { InspectorField } from "@/components/kit/InspectorField";
import { Button } from "@/components/ui/button";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { REGISTRATION_TEAM_ERROR_CODES } from "@/lib/registration/team-errors";
import type { RegistrationTeam } from "@/types/registration-team.types";

import { isTeamLive } from "./model";
import type { RoleOntology } from "@/lib/roster/ontology";
import { TeamInviteHistory } from "./TeamInviteHistory";
import { TeamRosterStrip } from "./TeamRosterStrip";
import type { RegistrationTeamActions } from "./useRegistrationTeamActions";

/**
 * One team, in full: what the row cannot show (lock, cover, check-in, the
 * roster itself, eligibility), the fields an organizer may write to it, and
 * the invite ledger. Status, shortfall and rejection reason are on the row and
 * the inspector subtitle; they are not said again here. Renaming is the row
 * kebab's dialog.
 *
 * Everything here is an edit of a team the organizer does NOT own, so every
 * control is gated on the same two facts — the permission, and whether the team
 * is still live — rather than on whichever of the two the control remembered.
 */
export function TeamInspectorPanel({
  team,
  tournamentId,
  workspaceId,
  canManageTeams,
  disabled,
  inlineError,
  ontology,
  actions
}: Readonly<{
  team: RegistrationTeam;
  tournamentId: number;
  workspaceId: number;
  /** The tournament's own game's scoped ontology: slots are named and drawn in it. */
  ontology: RoleOntology | null;
  canManageTeams: boolean;
  /** A read or a write is in flight; nothing on the panel may be typed into. */
  disabled: boolean;
  inlineError: ReactNode;
  actions: RegistrationTeamActions;
}>) {
  const t = useTranslations("registrationTeams");
  const tErr = useTranslations("registrationTeams.errors");

  const editable = canManageTeams && team.exported_team_id == null && isTeamLive(team);
  const admission = team.admission ?? "pending";
  const meta = [
    team.roster_locked_at ? t("lock.locked") : null,
    team.subscription_covered ? t("cover.covered") : null,
    typeof team.checked_in_count === "number" && (team.check_in_total ?? 0) > 0
      ? t("checkIn.counts", { done: team.checked_in_count, total: team.check_in_total ?? 0 })
      : null
  ].filter(Boolean);

  return (
    <div className="space-y-4">
      {inlineError}
      {meta.length > 0 && (
        <p className="text-caption text-muted-foreground">{meta.join(" · ")}</p>
      )}

      <TeamRosterStrip
        team={team}
        canManage={canManageTeams}
        disabled={disabled}
        ontology={ontology}
        onRevokeInvite={(inviteId) => actions.revokeInvite({ teamId: team.id, inviteId })}
      />

      {editable ? (
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-caption text-muted-foreground" htmlFor={`admission-${team.id}`}>
            {t("admin.admission")}
          </Label>
          <Select
            value={admission}
            disabled={disabled}
            onValueChange={(value) =>
              actions.setAdmission({
                teamId: team.id,
                admission: value as "pending" | "accepted" | "waitlisted"
              })
            }
          >
            <SelectTrigger id={`admission-${team.id}`} size="sm" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(["pending", "accepted", "waitlisted"] as const).map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`admission.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : (
        <InspectorField label={t("admin.admission")}>{t(`admission.${admission}`)}</InspectorField>
      )}
      {canManageTeams && (
        <div className="grid gap-1">
          <Label htmlFor={`notes-${team.id}`} className="text-caption text-muted-foreground">
            {t("admin.notes")}
          </Label>
          <Textarea
            id={`notes-${team.id}`}
            rows={2}
            value={actions.notesDraft[team.id] ?? team.organizer_notes ?? ""}
            onChange={(event) =>
              actions.setNotesDraft((current) => ({ ...current, [team.id]: event.target.value }))
            }
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-fit"
            disabled={disabled}
            onClick={() =>
              actions.setNotes({
                teamId: team.id,
                notes:
                  (actions.notesDraft[team.id] ?? team.organizer_notes ?? "").trim() || null
              })
            }
          >
            {t("admin.notesSave")}
          </Button>
        </div>
      )}
      {(team.eligibility_issues?.length ?? 0) > 0 && (
        <ul className="text-caption text-warning">
          <li className="font-medium">{t("eligibility.title")}</li>
          {team.eligibility_issues!.map((issue, index) => {
            const code = REGISTRATION_TEAM_ERROR_CODES.find((known) => known === issue.code);
            return (
              <li key={`${issue.code}-${issue.registration_id ?? "team"}-${index}`}>
                {code ? tErr(code) : t("admin.actionFailed")}
              </li>
            );
          })}
        </ul>
      )}
      <TeamInviteHistory
        tournamentId={tournamentId}
        workspaceId={workspaceId}
        teamId={team.id}
        ontology={ontology}
      />
    </div>
  );
}
