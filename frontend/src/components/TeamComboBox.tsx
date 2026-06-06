"use client";

import React, { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Team } from "@/types/team.types";
import { Check, ChevronsUpDown } from "lucide-react";

export interface TeamComboBoxProps {
  teams: Team[];
  onSelect: (team: Team) => void;
  selectedTeam: string;
  variant?: "default" | "glass";
}

const TeamComboBox = ({ teams, onSelect, selectedTeam, variant = "default" }: TeamComboBoxProps) => {
  const [open, setOpen] = useState(false);

  const isGlass = variant === "glass";

  const values: { label: string; value: string }[] = useMemo(() => {
    return teams.map((team) => ({
      label: team.name,
      value: team.name
    }));
  }, [teams]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "h-10 xs:w-full md:w-[250px] justify-between",
            isGlass &&
              "bg-background/15 border-border/60 backdrop-blur-md hover:bg-background/20 hover:text-foreground",
            isGlass && open && "bg-background/25 border-ring/40"
          )}
        >
          <span className="min-w-0 truncate" title={selectedTeam || ""}>
            {selectedTeam
              ? values.find((team) => team.value === selectedTeam)?.label
              : "Find team..."}
          </span>
          <ChevronsUpDown className="h-4 w-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={cn("p-0", isGlass && "liquid-glass-panel")}
        style={{ width: "var(--radix-popover-trigger-width)" }}
      >
        <Command className={cn(isGlass && "liquid-glass-surface")}>
          <CommandInput placeholder="Search team..." />
          <CommandList>
            <CommandEmpty>No team found.</CommandEmpty>
            <CommandGroup heading="Teams">
              {values.map((team) => (
                <CommandItem
                  key={team.value}
                  value={team.value}
                  onSelect={(currentValue) => {
                    setOpen(false);
                    onSelect(teams.find((t) => t.name === currentValue)!);
                  }}
                >
                  {team.label}
                  <Check
                    className={cn(
                      "ml-auto h-4 w-4",
                      selectedTeam === team.value ? "opacity-100" : "opacity-0"
                    )}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

export default TeamComboBox;
