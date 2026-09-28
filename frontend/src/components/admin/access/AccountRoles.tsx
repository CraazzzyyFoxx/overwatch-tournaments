"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { AccountSection, invalidateAccount } from "@/components/admin/access/AccountCard";
import { Combobox } from "@/components/kit/Combobox";
import { Badge } from "@/components/ui/badge";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RbacRole } from "@/types/rbac.types";

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
        `Workspace #${role.workspace_id}`);

  const assign = useMutation({
    mutationFn: (roleId: number) => rbacService.assignRole({ user_id: userId, role_id: roleId }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success("Role assigned");
    },
    onError: (error) => notify.apiError(error)
  });

  const remove = useMutation({
    mutationFn: (roleId: number) => rbacService.removeRole({ user_id: userId, role_id: roleId }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success("Role removed");
    },
    onError: (error) => notify.apiError(error)
  });

  const assigned = new Set(roles.map((role) => role.id));
  const groups = new Map<string, { key: string; label: string; roles: RbacRole[] }>();
  for (const role of catalogQuery.data ?? []) {
    if (assigned.has(role.id)) continue;
    const key = role.workspace_id == null ? "global" : String(role.workspace_id);
    const group = groups.get(key) ?? { key, label: scopeName(role) ?? "Global", roles: [] };
    group.roles.push(role);
    groups.set(key, group);
  }
  // Global first, then workspaces by name.
  const orderedGroups = [...groups.values()].sort((a, b) =>
    a.key === "global" ? -1 : b.key === "global" ? 1 : a.label.localeCompare(b.label)
  );

  return (
    <AccountSection
      title="Roles"
      summary={roles.length}
      action={
        canEdit ? (
          <Combobox
            open={open}
            onOpenChange={setOpen}
            label={
              <span className="inline-flex items-center gap-1">
                <Plus aria-hidden className="size-3.5" />
                Add role
              </span>
            }
            labelTitle="Add role"
            triggerAriaLabel="Add a role to this account"
            triggerClassName="h-7 w-auto gap-1.5 px-2 text-xs"
            disabled={assign.isPending}
            searchValue={search}
            onSearchValueChange={setSearch}
            searchPlaceholder="Search roles…"
            emptyMessage={
              catalogQuery.isLoading ? "Loading roles…" : "No other role to assign."
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
          No roles. This account only has what every signed-in user gets.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1.5" aria-label="Assigned roles">
          {roles.map((role) => {
            const scope = scopeName(role);
            return (
              <li key={role.id}>
                <Badge
                  variant="outline"
                  className="h-7 gap-1 bg-muted/40 text-sm font-normal"
                  title={role.description || undefined}
                >
                  <span className="font-medium">{role.name}</span>
                  {scope ? <span className="text-xs text-muted-foreground">· {scope}</span> : null}
                  {canEdit ? (
                    <button
                      type="button"
                      aria-label={`Remove role ${role.name} from this account`}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(role.id)}
                      className="-mr-1.5 inline-flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    >
                      <X aria-hidden className="size-3.5" />
                    </button>
                  ) : null}
                </Badge>
              </li>
            );
          })}
        </ul>
      )}
    </AccountSection>
  );
}
