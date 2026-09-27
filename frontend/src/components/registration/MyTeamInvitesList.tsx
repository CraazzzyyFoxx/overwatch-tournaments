"use client";

import { useTranslations } from "next-intl";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@/components/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import type { RegistrationTeam } from "@/types/registration-team.types";

interface MyTeamInvitesListProps {
  /** Live offers only — the card filters them, so the empty copy is honest. */
  pendingInvites: RegistrationTeam["invites"];
  canEditRoster: boolean;
  busy: boolean;
  onExtend: (input: { inviteId: number; rotate: boolean }) => void;
  onRevoke: (inviteId: number) => void;
}

/** The offers this roster has out: who they address, when they lapse, and the
 *  three things staff can still do to one. */
export default function MyTeamInvitesList({
  pendingInvites,
  canEditRoster,
  busy,
  onExtend,
  onRevoke,
}: Readonly<MyTeamInvitesListProps>) {
  const format = useFormatter();
  const t = useTranslations("registrationTeams");

  return (
    <div className="grid gap-2">
      <span className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
        {t("invite.title")}
      </span>
      {pendingInvites.length === 0 ? (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("invite.pendingEmpty")}</p>
      ) : (
        <ul className="divide-y divide-[color:var(--aqt-border)]">
          {pendingInvites.map((invite) => (
            <li
              key={invite.id}
              className="flex flex-wrap items-center gap-2 border-l-2 border-[color:var(--aqt-amber)]/50 py-2.5 pl-3 text-sm first:pt-0 last:pb-0"
            >
              <RosterSlotGlyph code={invite.slot_code} />
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {invite.target_battle_tag
                  ? t("invite.targetLabel", { name: invite.target_battle_tag })
                  : t("invite.linkLabel")}
              </span>
              {invite.is_substitute && (
                <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                  {t("member.substitute")}
                </span>
              )}
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t(`inviteState.${invite.state}`)}
              </span>
              {invite.expires_at && (
                <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                  {t("invite.expiresAt", {
                    date: format.dateTime(new Date(invite.expires_at), { dateStyle: "medium" }),
                  })}
                </span>
              )}
              <span className="ml-auto flex flex-wrap gap-1">
                {canEditRoster && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onExtend({ inviteId: invite.id, rotate: false })}
                  >
                    {t("invite.extend")}
                  </Button>
                )}
                {canEditRoster && invite.is_link && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onExtend({ inviteId: invite.id, rotate: true })}
                  >
                    {t("invite.rotate")}
                  </Button>
                )}
                {canEditRoster && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onRevoke(invite.id)}
                  >
                    {t("invite.revoke")}
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
