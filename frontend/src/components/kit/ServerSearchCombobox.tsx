"use client";

import { type ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  useSearchComboboxQuery,
  type SearchComboboxMessages
} from "@/components/kit/useSearchComboboxQuery";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Skeleton } from "@/components/ui/skeleton";
import { rbacService } from "@/services/rbac.service";
import userService from "@/services/user.service";
import type { AuthUserLookup } from "@/types/rbac.types";
import type { MinimizedUser } from "@/types/user.types";

/** Trigger props every server-searched picker forwards unchanged. */
interface ServerSearchChrome {
  /** Forwarded to the trigger so a `<Label htmlFor>` can name it. */
  id?: string;
  /** The picked item's id; `undefined` (or 0) when nothing is picked. */
  value?: number;
  /** Trigger text for `value` until it shows up among the loaded results. */
  selectedLabel?: string;
  /** Skeleton in the trigger while the caller resolves `selectedLabel`. */
  labelLoading?: boolean;
  /** Accessible name when no `<Label htmlFor>` points at the trigger. */
  triggerAriaLabel?: string;
  disabled?: boolean;
  size?: "sm" | "default";
}

export interface ServerSearchComboboxProps<TItem> extends ServerSearchChrome {
  onSelect: (item: TItem | undefined) => void;
  /** react-query key prefix; the debounced, trimmed search term is appended. */
  queryKey: unknown[];
  fetch: (params: { query: string; signal: AbortSignal }) => Promise<TItem[]>;
  itemId: (item: TItem) => number;
  /** Plain-text name, shown in the trigger once the item is picked. */
  label: (item: TItem) => string;
  /** Row body; defaults to `label`. */
  renderItem?: (item: TItem) => ReactNode;
  messages: SearchComboboxMessages;
  placeholder: string;
  searchPlaceholder: string;
  /** Label of the row that clears the pick; omit for no such row. */
  clearLabel?: string;
  /** Trimmed characters before the first request; the hook's default (2) when omitted. */
  minQueryLength?: number;
}

/**
 * The one server-searched picker: type two characters, get the server's
 * matches. Query plumbing comes from `useSearchComboboxQuery`, the shell from
 * `ui/combobox`; callers say what to fetch and how a row reads.
 */
export function ServerSearchCombobox<TItem>({
  id,
  value,
  selectedLabel,
  labelLoading = false,
  triggerAriaLabel,
  disabled = false,
  size,
  onSelect,
  queryKey,
  fetch,
  itemId,
  label,
  renderItem,
  messages,
  placeholder,
  searchPlaceholder,
  clearLabel,
  minQueryLength
}: Readonly<ServerSearchComboboxProps<TItem>>) {
  const { open, setOpen, searchValue, setSearchValue, results, handleSelect, emptyMessage } =
    useSearchComboboxQuery<TItem, TItem>({
      queryKeyPrefix: queryKey,
      fetchResults: fetch,
      onSelect,
      messages,
      minQueryLength
    });

  const picked = value ? results.find((item) => itemId(item) === value) : undefined;
  // `||`, not `??`: a form's cleared name field is "", and "" is no label.
  const text = picked ? label(picked) : selectedLabel || placeholder;

  return (
    <Combobox
      id={id}
      open={open}
      onOpenChange={setOpen}
      label={labelLoading ? <Skeleton className="h-4 w-32" /> : text}
      labelTitle={text}
      triggerAriaLabel={triggerAriaLabel}
      size={size}
      disabled={disabled}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder={searchPlaceholder}
      emptyMessage={emptyMessage}
      // Results are already server-filtered; don't let cmdk re-filter them out.
      shouldFilter={false}
      clear={
        clearLabel && value
          ? { label: clearLabel, value: "__clear__", onSelect: () => handleSelect(undefined) }
          : undefined
      }
    >
      <CommandGroup>
        {results.map((item) => (
          <CommandItem
            key={itemId(item)}
            value={String(itemId(item))}
            onSelect={() => handleSelect(item)}
          >
            <span className="min-w-0 flex-1">
              {renderItem ? (
                renderItem(item)
              ) : (
                <span className="block truncate">{label(item)}</span>
              )}
            </span>
            <ComboboxCheck selected={value === itemId(item)} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}

interface UserPickerProps<TPicked> extends ServerSearchChrome {
  onSelect: (item: TPicked | undefined) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  /** Label of the row that clears the pick; `null` drops the row. */
  clearLabel?: string | null;
}

/** Player identities (`MinimizedUser`), searched by name. */
export function UserSearchCombobox({
  onSelect,
  placeholder,
  searchPlaceholder,
  clearLabel,
  ...chrome
}: Readonly<UserPickerProps<MinimizedUser>>) {
  const t = useTranslations("kit.userSearch");
  return (
    <ServerSearchCombobox<MinimizedUser>
      {...chrome}
      selectedLabel={
        chrome.selectedLabel || (chrome.value ? t("userId", { id: chrome.value }) : undefined)
      }
      onSelect={onSelect}
      queryKey={["users-search-minimized"]}
      fetch={({ query, signal }) => userService.searchUsers(query, signal)}
      itemId={(user) => user.id}
      label={(user) => user.name}
      renderItem={(user) => (
        <span className="flex items-center justify-between gap-3">
          <span className="truncate">{user.name}</span>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">#{user.id}</span>
        </span>
      )}
      messages={{
        loading: t("loading"),
        error: t("error"),
        minChars: t("minChars"),
        empty: t("empty")
      }}
      placeholder={placeholder ?? t("placeholder")}
      searchPlaceholder={searchPlaceholder ?? t("searchPlaceholder")}
      clearLabel={clearLabel === null ? undefined : (clearLabel ?? t("clearSelection"))}
    />
  );
}

export interface AuthUserOption {
  id: number;
  label: string;
}

/**
 * Auth (login) accounts, searched by email or username — for linking a player
 * to one, or adding a workspace member. `workspaceId` scopes the read grant; a
 * caller holding it only there gets lookup hits without an email.
 */
export function AuthUserSearchCombobox({
  workspaceId,
  onSelect,
  placeholder,
  searchPlaceholder,
  clearLabel,
  ...chrome
}: Readonly<UserPickerProps<AuthUserOption> & { workspaceId?: number }>) {
  const t = useTranslations("kit.authUser");
  return (
    <ServerSearchCombobox<AuthUserLookup>
      {...chrome}
      selectedLabel={
        chrome.selectedLabel || (chrome.value ? t("userId", { id: chrome.value }) : undefined)
      }
      onSelect={(user) => onSelect(user && { id: user.id, label: user.username })}
      queryKey={["auth-users-search", workspaceId ?? null]}
      fetch={({ query }) =>
        rbacService
          .listUsers({ search: query, per_page: 20, workspace_id: workspaceId })
          .then((page) => page.results)
      }
      itemId={(user) => user.id}
      // The workspace-scoped account search answers an empty page below 3 characters.
      minQueryLength={3}
      label={(user) => user.username}
      renderItem={(user) => (
        <span className="flex flex-col">
          <span className="truncate">{user.username}</span>
          {user.email ? (
            <span className="truncate text-xs text-muted-foreground">{user.email}</span>
          ) : null}
        </span>
      )}
      messages={{
        loading: t("loading"),
        error: t("error"),
        minChars: t("minChars"),
        empty: t("empty")
      }}
      placeholder={placeholder ?? t("placeholder")}
      searchPlaceholder={searchPlaceholder ?? t("searchPlaceholder")}
      clearLabel={clearLabel === null ? undefined : (clearLabel ?? t("clearSelection"))}
    />
  );
}
