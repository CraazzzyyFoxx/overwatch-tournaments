"use client";

import { useTranslations } from "next-intl";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useWorkspaceStore } from "@/stores/workspace.store";

/** The `?scope=` value for roles with `workspace_id IS NULL`. */
const GLOBAL_SCOPE = "global";

export interface RoleScopeOption {
  value: string;
  label: string;
}

/**
 * The role scopes the reader may list, and the one `?scope=` picks.
 *
 * Roles and Permissions both read the param, so they share this rather than
 * each re-deriving the fallback: with no param it lands on whatever the reader
 * may actually see, because a workspace admin without the global `role.read`
 * would otherwise land on an empty Global scope and think there are no roles.
 */
export function useRoleScope(): {
  options: RoleScopeOption[];
  scope: string | number;
  workspaceId: number | null;
} {
  const tc = useTranslations("adminAccess.common");
  const { hasPermission, isSuperuser, canAccessAnyPermission } = usePermissions();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const { searchParams } = useQueryParams();

  const canReadGlobalRoles = isSuperuser || hasPermission("role.read");
  const adminWorkspaces = workspaces.filter(
    (workspace) =>
      isSuperuser ||
      canAccessAnyPermission(
        ["role.read", "role.create", "role.update", "role.delete"],
        workspace.id
      )
  );
  const options = [
    ...(canReadGlobalRoles ? [{ value: GLOBAL_SCOPE, label: tc("global") }] : []),
    ...adminWorkspaces.map((workspace) => ({ value: String(workspace.id), label: workspace.name }))
  ];

  const scopeParam = searchParams?.get("scope") ?? "";
  const requestedScope =
    scopeParam === "" ? (canReadGlobalRoles ? GLOBAL_SCOPE : "") : scopeParam;
  const scope: string | number =
    requestedScope === GLOBAL_SCOPE
      ? GLOBAL_SCOPE
      : requestedScope === ""
        ? (adminWorkspaces[0]?.id ?? GLOBAL_SCOPE)
        : Number(requestedScope);

  return { options, scope, workspaceId: scope === GLOBAL_SCOPE ? null : (scope as number) };
}

/** The scope picker; renders nothing when there is only one scope to pick. */
export function RoleScopeSelect({
  options,
  value,
  onValueChange,
  className
}: Readonly<{
  options: RoleScopeOption[];
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
}>) {
  const tc = useTranslations("adminAccess.common");
  if (options.length < 2) return null;
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger size="sm" aria-label={tc("scope")} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
