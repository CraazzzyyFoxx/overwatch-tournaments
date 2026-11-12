"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { AccountSection, invalidateAccount } from "@/components/admin/access/AccountCard";
import { Combobox } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@craazzzyyfoxx/admin-kit/ui/command";
import { FilterChip } from "@craazzzyyfoxx/admin-kit/ui/filter-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RbacRole } from "@/types/rbac.types";
import { useTranslations } from "next-intl";

/**
 * The roles an account holds, as chips, and one picker to add another.
 *
 * Picking a role assigns it: the old Select + "Assign role" pair was two
 * controls and an error toast for one decision. The picker groups roles by
 * scope because a workspace role handed out as if it were global is the
 * mistake worth making visible before the click, not after.
 */
export function AccountRoles({
  userId,
  roles,
  canEdit
}: Readonly<{ userId: number; roles: RbacRole[]; canEdit: boolean }>) {
  const t = useTranslations("adminAccess.accountRolesUi");
  const tc = useTranslations("adminAccess.common");
  const queryClient = useQueryClient();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  // The same entry the Accounts filter bar reads: no second request there.
  const catalogQuery = useQuery({
    queryKey: accessQueryKeys.rolesAll(),
    queryFn: () => rbacService.listRolesAll(),
    enabled: canEdit
  });

  const scopeName = (role: RbacRole) =>
    role.workspace_id == null
      ? null
      : (workspaces.find((workspace) => workspace.id === role.workspace_id)?.name ??
        tc("workspaceFallback", { id: role.workspace_id }));
  const roleLabel = (role: RbacRole) => {
    const scope = scopeName(role);
    return scope ? `${role.name} · ${scope}` : role.name;
  };

  const assign = useMutation({
    mutationFn: (roleId: number) => rbacService.assignRole({ user_id: userId, role_id: roleId }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success(t("assigned"));
    },
    onError: (error) => notify.apiError(error)
  });

  const remove = useMutation({
    mutationFn: (roleId: number) => rbacService.removeRole({ user_id: userId, role_id: roleId }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success(t("removed"));
    },
    onError: (error) => notify.apiError(error)
  });

  const assigned = new Set(roles.map((role) => role.id));
  const groups = new Map<string, { key: string; label: string; roles: RbacRole[] }>();
  for (const role of catalogQuery.data ?? []) {
    if (assigned.has(role.id)) continue;
    const key = role.workspace_id == null ? "global" : String(role.workspace_id);
    const group = groups.get(key) ?? { key, label: scopeName(role) ?? tc("global"), roles: [] };
    group.roles.push(role);
    groups.set(key, group);
  }
  // Global first, then workspaces by name.
  const orderedGroups = [...groups.values()].sort((a, b) =>
    a.key === "global" ? -1 : b.key === "global" ? 1 : a.label.localeCompare(b.label)
  );

  return (
    <AccountSection
      title={tc("roles")}
      action={
        canEdit ? (
          <Combobox
            open={open}
            onOpenChange={setOpen}
            label={
              <span className="inline-flex items-center gap-1">
                <Plus aria-hidden className="size-3.5" />
                {tc("addRole")}
              </span>
            }
            labelTitle={tc("addRole")}
            triggerAriaLabel={t("addLabel")}
            size="sm"
            triggerClassName="h-7 w-auto gap-1.5 px-2"
            disabled={assign.isPending}
            searchValue={search}
            onSearchValueChange={setSearch}
            searchPlaceholder={tc("searchRoles")}
            emptyMessage={
              catalogQuery.isLoading ? (
                <div role="status" className="space-y-2 px-2">
                  <span className="sr-only">{t("loading")}</span>
                  <Skeleton aria-hidden className="h-4 w-full" />
                  <Skeleton aria-hidden className="h-4 w-2/3" />
                </div>
              ) : (
                t("noOtherRole")
              )
            }
          >
            {orderedGroups.map((group) => (
              <CommandGroup key={group.key} heading={group.label}>
                {group.roles.map((role) => (
                  <CommandItem
                    key={role.id}
                    value={`${role.name} ${group.label} ${role.id}`}
                    onSelect={() => {
                      setOpen(false);
                      setSearch("");
                      assign.mutate(role.id);
                    }}
                  >
                    <span className="min-w-0">
                      <span className="block truncate">{role.name}</span>
                      {role.description ? (
                        <span className="block truncate text-xs text-muted-foreground">
                          {role.description}
                        </span>
                      ) : null}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </Combobox>
        ) : null
      }
    >
      {roles.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {tc("roleNone")}
        </p>
      ) : canEdit ? (
        <ul className="flex flex-wrap items-center gap-1.5" aria-label={t("assignedLabel")}>
          {roles.map((role) => (
            <li key={role.id} title={role.description || undefined}>
              <FilterChip
                active
                aria-label={t("removeLabel", { role: role.name })}
                disabled={remove.isPending}
                onClick={() => remove.mutate(role.id)}
              >
                {roleLabel(role)}
                <X aria-hidden className="size-3" />
              </FilterChip>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm">{roles.map(roleLabel).join(", ")}</p>
      )}
    </AccountSection>
  );
}
