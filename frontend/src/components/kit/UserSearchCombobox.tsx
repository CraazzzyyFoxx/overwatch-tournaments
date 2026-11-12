"use client";

import { useTranslations } from "next-intl";

import {
  ServerSearchCombobox,
  type ServerSearchComboboxProps
} from "@craazzzyyfoxx/admin-kit/kit/ServerSearchCombobox";
import { ComboboxMeta } from "@/components/ui/combobox";
import { rbacService } from "@/services/rbac.service";
import userService from "@/services/user.service";
import type { AuthUserLookup } from "@/types/rbac.types";
import type { MinimizedUser } from "@/types/user.types";

/** Trigger props every picker forwards to the kit's `ServerSearchCombobox` unchanged. */
type ServerSearchChrome = Pick<
  ServerSearchComboboxProps<unknown>,
  | "id"
  | "value"
  | "selectedLabel"
  | "labelLoading"
  | "triggerAriaLabel"
  | "disabled"
  | "size"
  | "aria-invalid"
  | "triggerClassName"
>;

type UserPickerProps<TPicked> = ServerSearchChrome & {
  onSelect: (item: TPicked | undefined) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  /** Label of the first row, "nothing picked"; `null` drops the row. */
  clearLabel?: string | null;
};

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
          <ComboboxMeta>#{user.id}</ComboboxMeta>
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
      clearLabel={clearLabel === null ? undefined : (clearLabel ?? t("none"))}
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
      fetch={({ query, signal }) =>
        rbacService
          .listUsers({ search: query, per_page: 20, workspace_id: workspaceId }, signal)
          .then((page) => page.results)
      }
      itemId={(user) => user.id}
      // The workspace-scoped account search answers an empty page below 3 characters.
      minQueryLength={3}
      label={(user) => user.username}
      renderItem={(user) => (
        <span className="flex flex-col">
          <span className="truncate">{user.username}</span>
          {user.email ? <ComboboxMeta className="truncate">{user.email}</ComboboxMeta> : null}
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
      clearLabel={clearLabel === null ? undefined : (clearLabel ?? t("none"))}
    />
  );
}
