"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { useDebounce } from "use-debounce";

import userService from "@/services/user.service";
import { MinimizedUser } from "@/types/user.types";
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

interface UserSearchComboboxProps {
  id?: string;
  value?: number;
  selectedName?: string;
  onSelect: (user: MinimizedUser | undefined) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
}

export function UserSearchCombobox({
  id,
  value,
  selectedName,
  onSelect,
  placeholder = "Select user",
  searchPlaceholder = "Search user...",
  disabled = false,
  allowClear = true,
}: UserSearchComboboxProps) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch] = useDebounce(searchValue, 250);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const normalizedQuery = debouncedSearch.trim();
  const shouldSearch = normalizedQuery.length >= 2;

  const usersQuery = useQuery({
    queryKey: ["users-search-minimized", normalizedQuery],
    enabled: open && shouldSearch,
    queryFn: ({ signal }) => userService.searchUsers(normalizedQuery, signal),
    staleTime: 60 * 1000,
  });

  const results = usersQuery.data ?? [];

  const selectedLabel = useMemo(() => {
    const matchedUser = results.find((user) => user.id === value);

    if (matchedUser) {
      return matchedUser.name;
    }

    if (selectedName) {
      return selectedName;
    }

    if (typeof value === "number" && value > 0) {
      return `User #${value}`;
    }

    return placeholder;
  }, [placeholder, results, selectedName, value]);

  const handleSelect = useCallback(
    (user: MinimizedUser | undefined) => {
      onSelect(user);
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
          id={id}
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
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-0">
        <Command>
          <CommandInput value={searchValue} onValueChange={setSearchValue} placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup>
              {results.map((user) => (
                <CommandItem
                  key={user.id}
                  value={`${user.name} ${user.id}`}
                  onSelect={() => handleSelect(user)}
                >
                  <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                    <span className="truncate">{user.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">#{user.id}</span>
                  </div>
                  <Check className={`ml-2 h-4 w-4 ${value === user.id ? "opacity-100" : "opacity-0"}`} />
                </CommandItem>
              ))}
            </CommandGroup>
            {allowClear && typeof value === "number" && value > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem value="clear-user-selection" onSelect={() => handleSelect(undefined)}>
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
