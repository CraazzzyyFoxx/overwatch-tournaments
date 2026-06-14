"use client";

import { useCallback, useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import type { Tournament } from "@/types/tournament.types";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface TournamentComboboxProps {
  tournaments: Tournament[];
  value?: number;
  onSelect: (tournament: Tournament | undefined) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
}

export function TournamentCombobox({
  tournaments,
  value,
  onSelect,
  placeholder = "All tournaments",
  searchPlaceholder = "Search tournament...",
  disabled = false,
  allowClear = true,
}: TournamentComboboxProps) {
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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className="h-10 w-full justify-between border-border/60 bg-background/80 font-normal hover:bg-background/90"
        >
          <span className="truncate" title={selectedLabel}>
            {selectedLabel}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0"
        style={{ width: "var(--radix-popover-trigger-width)" }}
      >
        <Command>
          <CommandInput
            value={searchValue}
            onValueChange={setSearchValue}
            placeholder={searchPlaceholder}
          />
          <CommandList>
            <CommandEmpty>No tournaments found.</CommandEmpty>
            <CommandGroup>
              {tournaments.map((tournament) => (
                <CommandItem
                  key={tournament.id}
                  value={`${tournament.name} ${tournament.id}`}
                  onSelect={() => handleSelect(tournament)}
                >
                  <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                    <span className="truncate">{tournament.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">#{tournament.id}</span>
                  </div>
                  <Check
                    className={`ml-2 h-4 w-4 ${value === tournament.id ? "opacity-100" : "opacity-0"}`}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
            {allowClear && typeof value === "number" ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value="clear-tournament-selection"
                    onSelect={() => handleSelect(undefined)}
                  >
                    Clear selection
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
