"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import type { Team } from "@/types/team.types";
import { Combobox, ComboboxCheck, ComboboxMeta } from "@/components/ui/combobox";
import TeamName from "@/components/TeamName";
import { CommandGroup, CommandItem } from "@/components/ui/command";

interface TeamComboboxProps {
  teams: Team[];
  value?: number | null;
  onSelect: (team: Team | undefined) => void;
  id?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
  /** Teams listed but not pickable, e.g. ones already seeded elsewhere. */
  isTeamDisabled?: (team: Team) => boolean;
  /** Accessible name when no visible `<Label htmlFor>` points at the trigger. */
  triggerAriaLabel?: string;
  triggerClassName?: string;
  size?: "sm" | "default";
}

export function TeamCombobox({
  teams,
  value,
  onSelect,
  id,
  placeholder,
  searchPlaceholder,
  disabled = false,
  allowClear = true,
  isTeamDisabled,
  triggerAriaLabel,
  triggerClassName,
  size
}: Readonly<TeamComboboxProps>) {
  const t = useTranslations("adminPeople.teamCombobox");
  const resolvedPlaceholder = placeholder ?? t("select");
  const resolvedSearchPlaceholder = searchPlaceholder ?? t("search");
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const selected = useMemo(() => teams.find((team) => team.id === value), [teams, value]);

  const handleSelect = useCallback(
    (team: Team | undefined) => {
      onSelect(team);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect]
  );

  return (
    <Combobox
      id={id}
      open={open}
      onOpenChange={setOpen}
      label={selected?.name}
      placeholder={resolvedPlaceholder}
      triggerAriaLabel={triggerAriaLabel}
      triggerClassName={triggerClassName}
      size={size}
      disabled={disabled}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder={resolvedSearchPlaceholder}
      emptyMessage={t("empty")}
      clear={
        allowClear && typeof value === "number"
          ? {
              label: t("tbd"),
              value: "clear-team-selection",
              onSelect: () => handleSelect(undefined)
            }
          : undefined
      }
    >
      <CommandGroup>
        {teams.map((team) => (
          <CommandItem
            key={team.id}
            value={`${team.name} ${team.id}`}
            onSelect={() => handleSelect(team)}
            disabled={isTeamDisabled?.(team)}
          >
            <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
              <TeamName team={team} size="xs" />
              <ComboboxMeta>#{team.id}</ComboboxMeta>
            </div>
            <ComboboxCheck selected={value === team.id} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}
