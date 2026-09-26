"use client";

import { Crown, LifeBuoy, X, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@/components/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { RegistrationTeam } from "@/types/registration-team.types";

import { EXPIRY_STAMP, inviteTone, isLiveInvite, isTeamLive, memberName } from "./model";

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
 * Roster and open invites in one wrapping strip: they fill the same slots, and
 * the dashed chip is what says "offered, not taken". Two separate lists left one
 * of them empty on most teams — and "No open invites." was a whole line spent on
 * the ordinary case.
 */
export function TeamRosterStrip({
  team,
  canManage,
  disabled,
  onRevokeInvite
}: Readonly<{
  team: RegistrationTeam;
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
    <ul className="flex flex-wrap items-center gap-1.5">
      {team.members.map((member) => (
        <li
          key={member.registration_id}
          className="flex items-center gap-1.5 rounded-md border border-border px-1.5 py-0.5 text-caption"
        >
          <RosterSlotGlyph code={member.slot_code} size={14} />
          <span className="font-medium">{memberName(member)}</span>
          {member.is_captain && (
            <RosterMark icon={Crown} label={t("member.captain")} className="text-warning" />
          )}
          {member.is_manager && !member.is_captain && (
            <span className="text-muted-foreground">{t("member.manager")}</span>
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
        <li
          key={invite.id}
          className="flex items-center gap-1.5 rounded-md border border-dashed border-border px-1.5 py-0.5 text-caption"
        >
          <StatusPill tone={inviteTone(invite.state)}>
            {t(`inviteState.${invite.state}`)}
          </StatusPill>
          <RosterSlotGlyph code={invite.slot_code} size={14} />
          <span className="text-muted-foreground">
            {invite.target_battle_tag ?? t("invite.linkLabel")}
          </span>
          {invite.is_substitute && (
            <RosterMark
              icon={LifeBuoy}
              label={t("member.substitute")}
              className="text-muted-foreground"
            />
          )}
          {invite.expires_at && (
            <span className="text-muted-foreground">
              {t("invite.expiresAt", {
                date: format.dateTime(new Date(invite.expires_at), EXPIRY_STAMP)
              })}
            </span>
          )}
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
