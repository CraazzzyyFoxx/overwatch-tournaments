"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Combobox, ComboboxCheck } from "@/components/kit/Combobox";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Checkbox } from "@/components/ui/checkbox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { ROSTER_SLOT_CODES } from "@/lib/roster/shape";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationTeamService from "@/services/registration-team.service";
import type { RegistrationTeam } from "@/types/registration-team.types";

import type { RegistrationTeamActions } from "./useRegistrationTeamActions";

/**
 * An organizer putting a player on someone else's roster.
 *
 * It asks for a PLAYER, not the registration id it used to demand — that field
 * could only be filled by someone reading the database, and a typo in it named
 * a different person's registration. The candidates are this tournament's free
 * agents, the same list the captain's invite picker reads, so a pick cannot be
 * refused for being on a team already.
 *
 * The BattleTag field below it is the other case: someone this tournament has
 * never seen, who has no registration to pick.
 */
export function PlaceMemberDialog({
  tournamentId,
  workspaceId,
  team,
  onClose,
  actions
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
  /** `null` closes the dialog; a team opens it on a blank form. */
  team: RegistrationTeam | null;
  onClose: () => void;
  actions: RegistrationTeamActions;
}>) {
  const t = useTranslations("registrationTeams");
  const tSlot = useTranslations("rosterShape.slotCodes");
  const fieldId = useId();

  const [registrationId, setRegistrationId] = useState<number | null>(null);
  const [battleTag, setBattleTag] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [slot, setSlot] = useState<string>(ROSTER_SLOT_CODES[0]);
  const [substitute, setSubstitute] = useState(false);

  // A different team is being filled, so the last one's answers are not this
  // one's. Synced during render, not in an effect: an effect would show one
  // render of the previous roster's pick against the new team's name.
  const [target, setTarget] = useState(team);
  if (target !== team) {
    setTarget(team);
    setRegistrationId(null);
    setBattleTag("");
    setSearch("");
    setSlot(ROSTER_SLOT_CODES[0]);
    setSubstitute(false);
  }

  const freeAgentsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId),
    queryFn: () => registrationTeamService.listFreeAgents(tournamentId),
    enabled: team != null
  });

  const selectedAgent = freeAgentsQuery.data?.items.find(
    (agent) => agent.registration_id === registrationId
  );

  return (
    <EntityFormDialog
      open={team != null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`${t("admin.place")} — ${team?.name ?? ""}`}
      description={t("admin.placeHint")}
      submitLabel={t("admin.place")}
      isSubmitting={actions.isPlacing}
      errorMessage={actions.actionError ?? undefined}
      guardNavigation={false}
      onSubmit={() => {
        if (!team) return;
        if (registrationId != null) {
          actions.placeMember({
            teamId: team.id,
            registrationId,
            slot_code: slot,
            is_substitute: substitute
          });
          return;
        }
        const tag = battleTag.trim();
        if (!tag) return;
        actions.attachMember({
          teamId: team.id,
          battle_tag: tag,
          slot_code: slot,
          is_substitute: substitute
        });
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor={fieldId}>{t("invite.accountLabel")}</Label>
        <Combobox
          id={fieldId}
          open={open}
          onOpenChange={setOpen}
          label={selectedAgent?.battle_tag ?? t("admin.placePlayerPick")}
          disabled={actions.isPlacing}
          searchValue={search}
          onSearchValueChange={setSearch}
          searchPlaceholder={t("picker.search")}
          emptyMessage={freeAgentsQuery.isError ? t("picker.loadError") : t("picker.empty")}
          clear={
            registrationId != null
              ? {
                  label: t("picker.clear"),
                  value: "clear-selected-player",
                  onSelect: () => {
                    setRegistrationId(null);
                    setOpen(false);
                  }
                }
              : undefined
          }
        >
          <CommandGroup>
            {(freeAgentsQuery.data?.items ?? []).map((agent) => (
              <CommandItem
                key={agent.registration_id}
                value={agent.battle_tag}
                onSelect={() => {
                  setRegistrationId(agent.registration_id);
                  setOpen(false);
                }}
              >
                <ComboboxCheck selected={agent.registration_id === registrationId} />
                <span className="truncate">{agent.battle_tag}</span>
                {/* The roles the player registered for, as glyphs: the
                    organizer is filling one specific slot. */}
                <span className="ml-auto flex items-center gap-1">
                  {agent.roles.map((role) => (
                    <RosterSlotGlyph key={role} code={role} size={14} />
                  ))}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        </Combobox>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${fieldId}-tag`}>{t("admin.placeBattleTag")}</Label>
        <Input
          id={`${fieldId}-tag`}
          value={battleTag}
          disabled={actions.isPlacing || registrationId != null}
          onChange={(event) => setBattleTag(event.target.value)}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${fieldId}-slot`}>{t("invite.slotLabel")}</Label>
        <Select value={slot} onValueChange={setSlot}>
          <SelectTrigger id={`${fieldId}-slot`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROSTER_SLOT_CODES.map((code) => (
              <SelectItem key={code} value={code}>
                <span className="flex items-center gap-1.5">
                  <RosterSlotGlyph code={code} size={14} decorative />
                  {tSlot(code)}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Label className="flex items-center gap-2 text-sm font-normal">
        <Checkbox
          checked={substitute}
          onCheckedChange={(checked) => setSubstitute(checked === true)}
        />
        {t("member.substitute")}
      </Label>
    </EntityFormDialog>
  );
}
