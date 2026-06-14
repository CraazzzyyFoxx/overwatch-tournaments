"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import type { AchievementRule } from "@/types/admin.types";
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
import { Badge } from "@/components/ui/badge";

interface AchievementComboboxProps {
  rules: AchievementRule[];
  value?: number;
  onSelect: (rule: AchievementRule | undefined) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
}

export function AchievementCombobox({
  rules,
  value,
  onSelect,
  placeholder = "Select achievement",
  searchPlaceholder = "Search achievement...",
  disabled = false,
  allowClear = true,
}: AchievementComboboxProps) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [contentWidth, setContentWidth] = useState<number | undefined>(undefined);

  useEffect(() => {
    if (!open) return;
    setContentWidth(triggerRef.current?.offsetWidth);
  }, [open]);

  const selectedRule = useMemo(
    () => rules.find((r) => r.id === value),
    [rules, value],
  );

  const selectedLabel = selectedRule
    ? `${selectedRule.name} (${selectedRule.slug})`
    : placeholder;

  const handleSelect = useCallback(
    (rule: AchievementRule | undefined) => {
      onSelect(rule);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect],
  );

  // Group rules by category for better navigation
  const grouped = useMemo(() => {
    const map: Record<string, AchievementRule[]> = {};
    for (const rule of rules) {
      (map[rule.category] ??= []).push(rule);
    }
    return Object.entries(map).sort(([a], [b]) => a.localeCompare(b));
  }, [rules]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
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
        style={contentWidth ? { width: `${contentWidth}px` } : undefined}
      >
        <Command>
          <CommandInput
            value={searchValue}
            onValueChange={setSearchValue}
            placeholder={searchPlaceholder}
          />
          <CommandList>
            <CommandEmpty>No achievements found.</CommandEmpty>
            {grouped.map(([category, categoryRules]) => (
              <CommandGroup key={category} heading={category}>
                {categoryRules.map((rule) => (
                  <CommandItem
                    key={rule.id}
                    value={`${rule.name} ${rule.slug} ${rule.category}`}
                    onSelect={() => handleSelect(rule)}
                  >
                    <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                      <span className="truncate">{rule.name}</span>
                      <Badge variant="outline" className="shrink-0 text-xs">
                        {rule.slug}
                      </Badge>
                    </div>
                    <Check
                      className={`ml-2 h-4 w-4 ${value === rule.id ? "opacity-100" : "opacity-0"}`}
                    />
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
            {allowClear && typeof value === "number" && value > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value="clear-achievement-selection"
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
