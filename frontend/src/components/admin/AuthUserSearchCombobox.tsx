"use client";

import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { useDebounce } from "use-debounce";

import { rbacService } from "@/services/rbac.service";
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

export interface AuthUserOption {
  id: number;
  label: string;
}

interface AuthUserSearchComboboxProps {
  id?: string;
  value?: number;
  selectedLabel?: string;
  onSelect: (user: AuthUserOption | undefined) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
}

/** Server-side search over auth (AuthUser) accounts, for linking a player to
 *  one. Mirrors UserSearchCombobox, but that searches player identities; this
 *  hits rbacService.listUsers (email/username). */
export function AuthUserSearchCombobox({
  id,
  value,
  selectedLabel,
  onSelect,
  placeholder = "Select auth account",
  searchPlaceholder = "Search by email or username...",
  disabled = false
}: AuthUserSearchComboboxProps) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch] = useDebounce(searchValue, 250);

  const normalizedQuery = debouncedSearch.trim();
  const shouldSearch = normalizedQuery.length >= 2;

  const usersQuery = useQuery({
    queryKey: ["auth-users-search", normalizedQuery],
    enabled: open && shouldSearch,
    queryFn: () => rbacService.listUsers({ search: normalizedQuery, per_page: 20 }),
    staleTime: 60 * 1000
  });
  const results = usersQuery.data?.results ?? [];

  const label =
    selectedLabel ?? (typeof value === "number" && value > 0 ? `User #${value}` : placeholder);

  const handleSelect = useCallback(
    (user: AuthUserOption | undefined) => {
      onSelect(user);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect]
  );

  const emptyMessage = usersQuery.isFetching
    ? "Loading accounts..."
    : usersQuery.isError
      ? "Failed to load accounts."
      : !shouldSearch
        ? "Type at least 2 characters."
        : "No accounts found.";

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
          <span className="truncate" title={label}>
            {label}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-0">
        {/* Results are already server-filtered; don't let cmdk re-filter them out. */}
        <Command shouldFilter={false}>
          <CommandInput
            value={searchValue}
            onValueChange={setSearchValue}
            placeholder={searchPlaceholder}
          />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup>
              {results.map((user) => (
                <CommandItem
                  key={user.id}
                  value={`${user.username} ${user.email} ${user.id}`}
                  onSelect={() => handleSelect({ id: user.id, label: user.username })}
                >
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate">{user.username}</span>
                    <span className="truncate text-xs text-muted-foreground">{user.email}</span>
                  </div>
                  <Check
                    className={`ml-2 h-4 w-4 shrink-0 ${value === user.id ? "opacity-100" : "opacity-0"}`}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
            {typeof value === "number" && value > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value="clear-auth-user-selection"
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
