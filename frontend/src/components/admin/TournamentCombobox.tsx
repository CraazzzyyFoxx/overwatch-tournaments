"use client";

import { useCallback, useMemo, useState } from "react";

import type { Tournament } from "@/types/tournament.types";
import { AdminCombobox, AdminComboboxCheck } from "@/components/kit/AdminCombobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";

interface TournamentComboboxProps {
  tournaments: Tournament[];
  value?: number;
  onSelect: (tournament: Tournament | undefined) => void;
  id?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
}

export function TournamentCombobox({
  tournaments,
  value,
  onSelect,
  id,
  placeholder = "All tournaments",
  searchPlaceholder = "Search tournament…",
  disabled = false,
  allowClear = true,
}: Readonly<TournamentComboboxProps>) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const selected = useMemo(
    () => tournaments.find((t) => t.id === value),
    [tournaments, value],
  );

  const selectedLabel = selected ? selected.name : placeholder;

  const handleSelect = useCallback(
    (tournament: Tournament | undefined) => {
      onSelect(tournament);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect],
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
      emptyMessage="No tournaments match that search. Try a shorter name or the numeric id."
      clear={
        allowClear && typeof value === "number"
          ? {
              label: "Clear selection",
              value: "clear-tournament-selection",
              onSelect: () => handleSelect(undefined),
            }
          : undefined
      }
    >
      <CommandGroup>
        {tournaments.map((tournament) => (
          <CommandItem
            key={tournament.id}
            value={`${tournament.name} ${tournament.id}`}
            onSelect={() => handleSelect(tournament)}
          >
            <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
              <span className="truncate">{tournament.name}</span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                #{tournament.id}
              </span>
            </div>
            <AdminComboboxCheck selected={value === tournament.id} />
          </CommandItem>
        ))}
      </CommandGroup>
    </AdminCombobox>
  );
}
