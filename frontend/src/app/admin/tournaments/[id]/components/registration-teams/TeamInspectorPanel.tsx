"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { REGISTRATION_TEAM_ERROR_CODES } from "@/lib/registration/team-errors";
import { formatShortfall } from "@/lib/registration/team-shortfall";
import type { RegistrationTeam } from "@/types/registration-team.types";

import { ADMISSION_TONE, isTeamLive } from "./model";
import { TeamInviteHistory } from "./TeamInviteHistory";
import { TeamRosterStrip } from "./TeamRosterStrip";
import type { RegistrationTeamActions } from "./useRegistrationTeamActions";

/**
 * One team, in full: the badges that answer "what is this roster's state", the
 * three fields an organizer may write to it, and the invite ledger.
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
  actions
}: Readonly<{
  team: RegistrationTeam;
  tournamentId: number;
  workspaceId: number;
  canManageTeams: boolean;
  /** A read or a write is in flight; nothing on the panel may be typed into. */
  disabled: boolean;
  inlineError: ReactNode;
  actions: RegistrationTeamActions;
}>) {
  const t = useTranslations("registrationTeams");
  const tErr = useTranslations("registrationTeams.errors");
  const tSlot = useTranslations("rosterShape.slotCodes");

  const editable = canManageTeams && team.exported_team_id == null && isTeamLive(team);
  const name = actions.nameDraft[team.id] ?? team.name;

  return (
    <div className="space-y-4">
      {inlineError}
      {team.rejection_reason && (
        <Alert variant="destructive">
          <AlertDescription>
            {t("admin.rejectionReason", { reason: team.rejection_reason })}
          </AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusPill tone={ADMISSION_TONE[team.admission ?? "pending"] ?? "neutral"}>
          {t(`admission.${team.admission ?? "pending"}`)}
        </StatusPill>
        {team.roster_locked_at && <Badge variant="outline">{t("lock.locked")}</Badge>}
        {team.subscription_covered && <Badge variant="outline">{t("cover.covered")}</Badge>}
        {typeof team.checked_in_count === "number" && (team.check_in_total ?? 0) > 0 && (
          <span className="text-caption text-muted-foreground">
            {t("checkIn.counts", {
              done: team.checked_in_count,
              total: team.check_in_total ?? 0
            })}
          </span>
        )}
        {team.exported_team_id != null && <Badge variant="outline">{t("admin.inTournament")}</Badge>}
        {/* The whole point of the screen: what is still missing. A full roster
            already says so in its status pill, so only the shortfall gets words
            of its own. */}
        {team.status === "forming" && team.exported_team_id == null && (
          <span className="text-caption font-medium text-warning">
            {t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}
          </span>
        )}
      </div>

      <TeamRosterStrip
        team={team}
        canManage={canManageTeams}
        disabled={disabled}
        onRevokeInvite={(inviteId) => actions.revokeInvite({ teamId: team.id, inviteId })}
      />

      {editable && (
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-caption text-muted-foreground" htmlFor={`admission-${team.id}`}>
            {t("admin.admission")}
          </Label>
          <Select
            value={team.admission ?? "pending"}
            disabled={disabled}
            onValueChange={(value) =>
              actions.setAdmission({
                teamId: team.id,
                admission: value as "pending" | "accepted" | "waitlisted"
              })
            }
          >
            <SelectTrigger id={`admission-${team.id}`} className="h-8 w-44">
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
      )}
      {editable && (
        <div className="grid gap-1">
          <Label htmlFor={`name-${team.id}`} className="text-caption text-muted-foreground">
            {t("create.nameLabel")}
          </Label>
          <Input
            id={`name-${team.id}`}
            value={name}
            disabled={disabled}
            onChange={(event) =>
              actions.setNameDraft((current) => ({ ...current, [team.id]: event.target.value }))
            }
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-fit"
            disabled={disabled || !name.trim() || name.trim() === team.name}
            onClick={() => actions.rename({ teamId: team.id, name: name.trim() })}
          >
            {t("rename.save")}
          </Button>
        </div>
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
        meta={
          /* Only once someone is actually on the bench: "0 of 2 substitutes"
             under every team is a constant, not news. */
          team.substitutes_used > 0 ? (
            <span className="text-caption text-muted-foreground">
              {t("list.substitutes", {
                used: team.substitutes_used,
                max: team.max_substitutes
              })}
            </span>
          ) : null
        }
      />
    </div>
  );
}
