"use client";

import { useCallback, useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import type { Team } from "@/types/team.types";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

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
  searchPlaceholder = "Search team...",
  disabled = false,
  allowClear = true
}: TeamComboboxProps) {
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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
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
            <CommandEmpty>No teams found.</CommandEmpty>
            <CommandGroup>
              {teams.map((team) => (
                <CommandItem
                  key={team.id}
                  value={`${team.name} ${team.id}`}
                  onSelect={() => handleSelect(team)}
                >
                  <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                    <span className="truncate">{team.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">#{team.id}</span>
                  </div>
                  <Check
                    className={`ml-2 h-4 w-4 ${value === team.id ? "opacity-100" : "opacity-0"}`}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
            {allowClear && typeof value === "number" ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem value="clear-team-selection" onSelect={() => handleSelect(undefined)}>
                    Set as TBD
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
