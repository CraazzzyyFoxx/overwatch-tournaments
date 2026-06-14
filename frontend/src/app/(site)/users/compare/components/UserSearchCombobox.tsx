"use client";

import React, { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { useDebounce } from "use-debounce";

import userService from "@/services/user.service";
import { MinimizedUser } from "@/types/user.types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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

interface UserSearchComboboxProps {
  value?: number;
  onSelect: (nextUserId: number | undefined) => void;
  placeholder: string;
  selectedName?: string;
  allowClear?: boolean;
  isLabelLoading?: boolean;
}

const UserSearchCombobox = ({
  value,
  onSelect,
  placeholder,
  selectedName,
  allowClear = true,
  isLabelLoading = false
}: UserSearchComboboxProps) => {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch] = useDebounce(searchValue, 250);

  const normalizedQuery = debouncedSearch.trim();
  const shouldSearch = normalizedQuery.length >= 2;

  const usersQuery = useQuery({
    queryKey: ["users-search-minimized", normalizedQuery],
    enabled: open && shouldSearch,
    queryFn: ({ signal }) => userService.searchUsers(normalizedQuery, signal),
    staleTime: 60 * 1000
  });

  const results = usersQuery.data ?? ([] as MinimizedUser[]);

  const selectedLabel = useMemo(() => {
    const fromResults = results.find((user) => user.id === value);
    if (fromResults) return fromResults.name;
    if (selectedName) return selectedName;
    if (typeof value === "number" && value > 0) return `User #${value}`;
    return placeholder;
  }, [placeholder, results, selectedName, value]);

  const handleSelect = useCallback(
    (nextUserId: number | undefined): void => {
      onSelect(nextUserId);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect]
  );

  const emptyMessage = usersQuery.isFetching
    ? "Loading users..."
    : usersQuery.isError
      ? "Failed to load users."
      : !shouldSearch
        ? "Type at least 2 characters."
        : "No users found.";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-10 w-full justify-between border-border/60 bg-background/15 font-normal hover:bg-background/20"
        >
          {isLabelLoading ? (
            <Skeleton className="h-4 w-32" />
          ) : (
            <span className="truncate" title={selectedLabel}>
              {selectedLabel}
            </span>
          )}
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="liquid-glass-panel p-0"
        style={{ width: "var(--radix-popover-trigger-width)" }}
      >
        <Command className="liquid-glass-surface">
          <CommandInput value={searchValue} onValueChange={setSearchValue} placeholder="Search user..." />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup>
              {results.map((user) => (
                <CommandItem
                  key={user.id}
                  value={`${user.name} ${user.id}`}
                  onSelect={() => handleSelect(user.id)}
                >
                  <span className="truncate">{user.name}</span>
                  <Check className={`ml-auto h-4 w-4 ${value === user.id ? "opacity-100" : "opacity-0"}`} />
                </CommandItem>
              ))}
            </CommandGroup>
            {allowClear && typeof value === "number" ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem value="clear-user-selection" onSelect={() => handleSelect(undefined)}>
                    Compare with all players avg
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

export default UserSearchCombobox;
