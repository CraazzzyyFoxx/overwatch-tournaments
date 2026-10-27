"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Combobox, ComboboxCheck, ComboboxMeta } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import type {
  ChallongeTeamPreviewParticipant,
  ChallongeTeamPreviewTeam
} from "@/types/admin.types";
import { UNMAPPED_TEAM_VALUE } from "./model";

/**
 * Searchable internal-team picker for one Challonge participant.
 *
 * A plain `<Select>` listed every team in creation order with no way to type:
 * a mix roster runs to dozens of teams whose Challonge participant name
 * ("litnik team") differs from the internal one ("litnik"), which is precisely
 * the case that lands here — auto-mapping only matches on an exact normalized
 * name, so whatever it could resolve is already mapped before this dialog opens.
 *
 * Search covers the internal name, the balancer name and the numeric id, because
 * all three are what an admin actually has in hand while reading the Challonge
 * side. Own `open`/`searchValue` state per row: the shell is controlled, and one
 * row's popover must not know about another's.
 */
export function ChallongeTeamPicker({
  participant,
  teams,
  value,
  onChange
}: Readonly<{
  participant: ChallongeTeamPreviewParticipant;
  teams: ChallongeTeamPreviewTeam[];
  value: string;
  onChange: (next: string) => void;
}>) {
  const t = useTranslations("adminTournament.teams");
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const selected = teams.find((team) => String(team.id) === value);

  const select = (next: string) => {
    onChange(next);
    setOpen(false);
    setSearchValue("");
  };

  return (
    <Combobox
      open={open}
      onOpenChange={setOpen}
      label={selected?.name}
      placeholder={t("unmapped")}
      // The visible label repeats down the column, so it cannot name the control.
      triggerAriaLabel={t("internalTeamFor", { name: participant.name })}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder={t("search")}
      searchLabel={t("searchInternalTeamFor", { name: participant.name })}
      emptyMessage={t("noMatch")}
      clear={{
        label: t("unmapped"),
        value: "challonge-unmap-participant",
        onSelect: () => select(UNMAPPED_TEAM_VALUE)
      }}
    >
      <CommandGroup>
        {teams.map((team) => (
          <CommandItem
            key={team.id}
            value={`${team.name} ${team.balancer_name} ${team.id}`}
            onSelect={() => select(String(team.id))}
          >
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate">{team.name}</span>
              {team.balancer_name && team.balancer_name !== team.name ? (
                <ComboboxMeta className="truncate">{team.balancer_name}</ComboboxMeta>
              ) : null}
            </div>
            <ComboboxMeta>#{team.id}</ComboboxMeta>
            <ComboboxCheck selected={String(team.id) === value} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}
