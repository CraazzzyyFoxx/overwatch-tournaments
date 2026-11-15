"use client";

import { Crown, LifeBuoy, X, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { PersonLabel } from "@/components/PlayerName";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import type { RoleOntology } from "@/lib/roster/ontology";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { RegistrationTeam } from "@/types/registration-team.types";

import { EXPIRY_STAMP, isLiveInvite, isTeamLive } from "./model";

/**
 * Captain / substitute marker.
 *
 * The glyph replaces the word: on a table whose whole job is fitting every team
 * on one screen, "Captain" spelled out cost more width than the name beside it.
 * Same vocabulary as the public roster (`RegistrationTeamsList`), and the name
 * is still announced — hidden text, not a missing label.
 */
export function RosterMark({
  icon: Icon,
  label,
  className
}: Readonly<{ icon: LucideIcon; label: string; className?: string }>) {
  return (
    <span className={cn("inline-flex shrink-0", className)} title={label}>
      <Icon aria-hidden className="size-3.5" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

/**
 * Roster and open invites in one list: they fill the same slots, and an invite
 * row is what says "offered, not taken". Plain rows, not chips: a name is not a
 * status. Two separate lists left one of them empty on most teams.
 */
export function TeamRosterStrip({
  team,
  canManage,
  disabled,
  ontology,
  onRevokeInvite
}: Readonly<{
  team: RegistrationTeam;
  /** The tournament's own game's scoped ontology, for the slot glyphs. */
  ontology: RoleOntology | null;
  canManage: boolean;
  disabled: boolean;
  onRevokeInvite: (inviteId: number) => void;
}>) {
  const t = useTranslations("registrationTeams");
  const format = useFormatter();

  if (team.members.length === 0 && team.invites.length === 0) return null;

  const canWithdraw =
    canManage && !team.roster_locked_at && team.exported_team_id == null && isTeamLive(team);

  return (
    <ul className="divide-y divide-border/60 text-sm">
      {team.members.map((member) => (
        <li key={member.registration_id} className="flex items-center gap-2 py-1.5">
          <RosterSlotGlyph code={member.slot_code} ontology={ontology} size={14} />
          <PersonLabel display={member.display} showCanonical />
          {member.is_captain && (
            <RosterMark icon={Crown} label={t("member.captain")} className="text-warning" />
          )}
          {member.is_manager && !member.is_captain && (
            <span className="text-caption text-muted-foreground">{t("member.manager")}</span>
          )}
          {member.is_substitute && (
            <RosterMark
              icon={LifeBuoy}
              label={t("member.substitute")}
              className="text-muted-foreground"
            />
          )}
        </li>
      ))}
      {team.invites.map((invite) => (
        <li key={invite.id} className="flex items-center gap-2 py-1.5">
          <RosterSlotGlyph code={invite.slot_code} ontology={ontology} size={14} />
          <span className="min-w-0 truncate text-muted-foreground">
            {invite.target_handle ?? t("invite.linkLabel")}
          </span>
          {invite.is_substitute && (
            <RosterMark
              icon={LifeBuoy}
              label={t("member.substitute")}
              className="text-muted-foreground"
            />
          )}
          <span className="ml-auto shrink-0 text-caption text-muted-foreground">
            {t(`inviteState.${invite.state}`)}
            {invite.expires_at
              ? ` · ${t("invite.expiresAt", {
                  date: format.dateTime(new Date(invite.expires_at), EXPIRY_STAMP)
                })}`
              : null}
          </span>
          {/* An organizer reaching into someone else's roster. Its own label and
              the danger tone keep it from reading like the captain's own
              "Revoke" — the two are the same effect but not the same act, and
              the ledger records which one happened. */}
          {canWithdraw && isLiveInvite(invite) && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("admin.revokeInvite")}
              title={t("admin.revokeInvite")}
              className="size-6 text-danger [&_svg]:size-3.5"
              disabled={disabled}
              onClick={() => onRevokeInvite(invite.id)}
            >
              <X aria-hidden />
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
