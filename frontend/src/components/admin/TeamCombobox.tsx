"use client";

import { useCallback, useMemo, useState } from "react";

import type { Team } from "@/types/team.types";
import { AdminCombobox, AdminComboboxCheck } from "@/components/kit/AdminCombobox";
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
}

export function TeamCombobox({
  teams,
  value,
  onSelect,
  id,
  placeholder = "Select team",
  searchPlaceholder = "Search team…",
  disabled = false,
  allowClear = true
}: Readonly<TeamComboboxProps>) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const selected = useMemo(() => teams.find((team) => team.id === value), [teams, value]);
  const selectedLabel = selected?.name ?? placeholder;

  const handleSelect = useCallback(
    (team: Team | undefined) => {
      onSelect(team);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect]
  );

  return (
    <AdminCombobox
      id={id}
      open={open}
      onOpenChange={setOpen}
      label={selectedLabel}
      disabled={disabled}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder={searchPlaceholder}
      emptyMessage="No teams match that search. Try a shorter name or the numeric id."
      clear={
        allowClear && typeof value === "number"
          ? {
              label: "Set as TBD",
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
          >
            <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
              <TeamName team={team} size="xs" />
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">#{team.id}</span>
            </div>
            <AdminComboboxCheck selected={value === team.id} />
          </CommandItem>
        ))}
      </CommandGroup>
    </AdminCombobox>
  );
}
