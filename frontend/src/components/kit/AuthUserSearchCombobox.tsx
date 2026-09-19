"use client";

import { rbacService } from "@/services/rbac.service";
import type { AuthAdminUser } from "@/types/rbac.types";
import { AdminCombobox, AdminComboboxCheck } from "@/components/kit/AdminCombobox";
import { useSearchComboboxQuery } from "@/components/kit/useSearchComboboxQuery";
import { CommandGroup, CommandItem } from "@/components/ui/command";

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
  searchPlaceholder = "Search by email or username…",
  disabled = false
}: Readonly<AuthUserSearchComboboxProps>) {
  const {
    open,
    setOpen,
    searchValue,
    setSearchValue,
    results,
    handleSelect,
    emptyMessage
  } = useSearchComboboxQuery<AuthAdminUser, AuthUserOption>({
    queryKeyPrefix: ["auth-users-search"],
    fetchResults: ({ query }) =>
      rbacService.listUsers({ search: query, per_page: 20 }).then((page) => page.results),
    onSelect,
    messages: {
      loading: "Loading accounts…",
      error: "Could not load accounts. Try again.",
      minChars: "Type at least 2 characters to search.",
      empty: "No accounts match that email or username."
    }
  });

  const label =
    selectedLabel ?? (typeof value === "number" && value > 0 ? `User #${value}` : placeholder);

  return (
    <AdminCombobox
      id={id}
      open={open}
      onOpenChange={setOpen}
      label={label}
      disabled={disabled}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder={searchPlaceholder}
      emptyMessage={emptyMessage}
      // Results are already server-filtered; don't let cmdk re-filter them out.
      shouldFilter={false}
      clear={
        typeof value === "number" && value > 0
          ? {
              label: "Clear selection",
              value: "clear-auth-user-selection",
              onSelect: () => handleSelect(undefined)
            }
          : undefined
      }
    >
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
            <AdminComboboxCheck selected={value === user.id} />
          </CommandItem>
        ))}
      </CommandGroup>
    </AdminCombobox>
  );
}
