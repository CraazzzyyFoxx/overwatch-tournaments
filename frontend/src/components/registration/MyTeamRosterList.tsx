"use client";

import { Crown, UserMinus, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PersonLabel } from "@/components/PlayerName";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@craazzzyyfoxx/admin-kit/ui/select";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { SlotCode } from "@/lib/roster/shape";
import type { RegistrationTeam, RegistrationTeamMember } from "@/types/registration-team.types";

interface MyTeamRosterListProps {
  team: RegistrationTeam;
  /** One entry per unfilled, unoffered starter place. */
  freeSlots: SlotCode[];
  benchSlots: SlotCode[];
  benchOpen: boolean;
  isCaptain: boolean;
  canEditRoster: boolean;
  busy: boolean;
  /** The owner game's scoped ontology, for slot glyphs; `null` while it loads. */
  ontology: RoleOntology | null;
  slotLabel: (code: string) => string;
  /** `false` in a one-role game: every place is that role, so no slot is named, picked or invited to by name. */
  showsSlots: boolean;
  onPlace: (input: {
    registrationId: number;
    slot_code: string;
    is_substitute?: boolean;
  }) => void;
  onSetManager: (input: { registrationId: number; isManager: boolean }) => void;
  onTransferCaptaincy: (member: RegistrationTeamMember) => void;
  onKick: (member: RegistrationTeamMember) => void;
  onInvite: (code: SlotCode | null, substitute?: boolean) => void;
}

/** The roster itself: who holds which slot, the gaps nobody holds, and the bench. */
export default function MyTeamRosterList({
  team,
  freeSlots,
  benchSlots,
  benchOpen,
  isCaptain,
  canEditRoster,
  busy,
  ontology,
  slotLabel,
  showsSlots,
  onPlace,
  onSetManager,
  onTransferCaptaincy,
  onKick,
  onInvite,
}: Readonly<MyTeamRosterListProps>) {
  const t = useTranslations("registrationTeams");

  return (
    <ul className="divide-y divide-[color:var(--aqt-border)]">
      {team.members.map((member) => (
        <li
          key={member.registration_id}
          className="flex flex-wrap items-center gap-2 py-2.5 text-sm first:pt-0 last:pb-0"
        >
          <RosterSlotGlyph code={member.slot_code} ontology={ontology} />
          <PersonLabel display={member.display} className="font-medium" />
          {member.is_captain && (
            <span className="inline-flex items-center gap-1 text-xs text-[color:var(--aqt-amber)]">
              <Crown className="size-3.5" aria-hidden />
              {t("member.captain")}
            </span>
          )}
          {member.is_manager && !member.is_captain && (
            <span className="text-xs text-[color:var(--aqt-fg-muted)]">{t("member.manager")}</span>
          )}
          {member.is_substitute && (
            <span className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("member.substitute")}
            </span>
          )}
          {canEditRoster && !member.is_captain && (
            <span className="ml-auto flex flex-wrap gap-1">
              {canEditRoster && member.slot_code && showsSlots && (
                <Select
                  value={member.slot_code}
                  disabled={busy}
                  onValueChange={(slot_code) =>
                    onPlace({
                      registrationId: member.registration_id,
                      slot_code,
                      is_substitute: member.is_substitute,
                    })
                  }
                >
                  <SelectTrigger size="sm" aria-label={t("invite.slotLabel")} className="w-auto">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {benchSlots.map((code) => (
                      <SelectItem key={code} value={code}>
                        {slotLabel(code)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {canEditRoster && member.slot_code && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    onPlace({
                      registrationId: member.registration_id,
                      slot_code: member.slot_code as string,
                      is_substitute: !member.is_substitute,
                    })
                  }
                >
                  {member.is_substitute ? t("member.toStart") : t("member.toBench")}
                </Button>
              )}
              {isCaptain && canEditRoster && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    onSetManager({
                      registrationId: member.registration_id,
                      isManager: !member.is_manager,
                    })
                  }
                >
                  {member.is_manager ? t("member.removeManager") : t("member.makeManager")}
                </Button>
              )}
              {isCaptain && canEditRoster && !member.is_substitute && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => onTransferCaptaincy(member)}
                >
                  <Crown className="size-3.5" aria-hidden />
                  {t("member.makeCaptain")}
                </Button>
              )}
              {canEditRoster && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => onKick(member)}
                >
                  <UserMinus className="size-3.5" aria-hidden />
                  {t("member.kick")}
                </Button>
              )}
            </span>
          )}
        </li>
      ))}
      {/* A slot nobody holds and nobody was offered: the roster's own gap, with
          the action that fills it on the row rather than behind one generic
          "invite" button that then asks which slot. */}
      {freeSlots.map((code, index) => (
        <li
          key={`free-${code}-${index}`}
          className="flex flex-wrap items-center gap-2 py-2.5 text-sm first:pt-0 last:pb-0"
        >
          <RosterSlotGlyph code={code} ontology={ontology} />
          <span className="text-[color:var(--aqt-fg-muted)]">{t("list.openSlot")}</span>
          {showsSlots && (
            <span className="text-xs text-[color:var(--aqt-fg-muted)]">{slotLabel(code)}</span>
          )}
          {canEditRoster && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto"
              disabled={busy}
              onClick={() => onInvite(code)}
            >
              <UserPlus className="size-3.5" aria-hidden />
              {showsSlots ? t("invite.actionSlot", { slot: slotLabel(code) }) : t("invite.action")}
            </Button>
          )}
        </li>
      ))}
      {benchOpen && (
        <li className="flex flex-wrap items-center gap-2 py-2.5 text-sm first:pt-0 last:pb-0">
          <span className="text-[color:var(--aqt-fg-muted)]">
            {t("list.substitutes", { used: team.substitutes_used, max: team.max_substitutes })}
          </span>
          {canEditRoster && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto"
              disabled={busy}
              onClick={() => onInvite(benchSlots[0] ?? null, true)}
            >
              <UserPlus className="size-3.5" aria-hidden />
              {t("invite.actionBench")}
            </Button>
          )}
        </li>
      )}
    </ul>
  );
}
