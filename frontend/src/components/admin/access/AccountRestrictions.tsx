"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Globe, Loader2 } from "lucide-react";

import {
  PermissionPicker,
  type PermissionCatalogEntry
} from "@/components/admin/access/PermissionPicker";
import { EYEBROW_CLASS, TONE_CLASS } from "@/components/kit/tone";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Self-service, allow-by-default capabilities an admin can revoke per account
 * (negative RBAC). A checked row = denied in the selected scope. Governance
 * permissions are not deniable — the backend rejects them — so the catalogue is
 * this list and not the whole permission inventory.
 *
 * It has to mirror the "self-service capabilities" block of
 * `shared/rbac/catalog.py`: a capability the backend gates on `can_capability`
 * but that never appears here is unrevokable in practice.
 */
const RESTRICTABLE: PermissionCatalogEntry[] = [
  {
    key: "account.avatar",
    resource: "account",
    action: "avatar",
    description: "Change own avatar"
  },
  {
    key: "account.social",
    resource: "account",
    action: "social",
    description: "Manage own linked accounts"
  },
  {
    key: "registration.self_register",
    resource: "registration",
    action: "self_register",
    description: "Sign up for tournaments"
  },
  {
    key: "workspace.self_create",
    resource: "workspace",
    action: "self_create",
    description: "Create own workspaces"
  }
];

/** "global" = the deny applies everywhere; a number scopes it to one workspace. */
type DenyScope = "global" | number;

/**
 * Restrictions for one auth account — the same `PermissionPicker` as roles and
 * API keys, read as "what this account may NOT do".
 *
 * The picker's signature carries no tone, so the danger reading comes from the
 * panel around it rather than from the control: a checked row here takes access
 * away, which is the opposite of every other picker on the screen and must not
 * look identical to it.
 */
export function AccountRestrictions({
  userId,
  canEdit
}: Readonly<{ userId: number; canEdit: boolean }>) {
  const queryClient = useQueryClient();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const [scope, setScope] = useState<DenyScope>("global");
  const scopeId = useId();
  const scopeWorkspaceId = scope === "global" ? null : scope;

  const deniesQuery = useQuery({
    queryKey: ["access-admin", "denies", userId],
    queryFn: () => rbacService.getUserDenies(userId)
  });
  const permissionsQuery = useQuery({
    // The whole inventory, not a `search` narrowed to one resource: the
    // restrictable capabilities span three resources now, and a row whose
    // permission id is missing here is silently dropped from the picker below.
    queryKey: ["access-admin", "permissions", "inventory"],
    queryFn: () => rbacService.listPermissionsAll()
  });

  const denies = deniesQuery.data ?? [];
  const permissionIdByName = new Map(
    (permissionsQuery.data ?? []).map((permission) => [permission.name, permission.id])
  );

  const denied = new Set(
    denies
      .filter((deny) => (deny.workspace_id ?? null) === scopeWorkspaceId)
      .map((deny) => deny.name)
  );

  const toggle = useMutation({
    mutationFn: ({ permissionId, deny }: { permissionId: number; deny: boolean }) =>
      deny
        ? rbacService.addUserDeny(userId, permissionId, scopeWorkspaceId)
        : rbacService.removeUserDeny(userId, permissionId, scopeWorkspaceId),
    onSuccess: (updated) =>
      queryClient.setQueryData(["access-admin", "denies", userId], updated),
    onError: (error) => notify.apiError(error, { title: "Could not change the restriction" })
  });

  const loading = deniesQuery.isLoading || permissionsQuery.isLoading;
  const catalog = RESTRICTABLE.filter(
    (entry) => permissionIdByName.get(entry.key) !== undefined
  );

  return (
    <section className={cn("space-y-2 rounded-xl border p-3", TONE_CLASS.danger)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className={EYEBROW_CLASS}>Restricted actions</h3>
          {loading ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin text-muted-foreground" />
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor={scopeId} className="text-xs text-muted-foreground">
            Scope
          </Label>
          <Select
            value={String(scope)}
            onValueChange={(value) => setScope(value === "global" ? "global" : Number(value))}
          >
            <SelectTrigger id={scopeId} className="h-8 w-40 text-xs" disabled={!canEdit}>
              <SelectValue placeholder="Select scope" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="global">
                <span className="flex items-center gap-2">
                  <Globe aria-hidden className="size-3.5" />
                  Global
                </span>
              </SelectItem>
              {workspaces.map((workspace) => (
                <SelectItem key={workspace.id} value={String(workspace.id)}>
                  <span className="flex items-center gap-2">
                    <Building2 aria-hidden className="size-3.5" />
                    {workspace.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        A checked capability is revoked for this account in the selected scope. A restriction beats
        every grant, superuser included, for that exact action in that scope only.
      </p>

      <PermissionPicker
        mode="list"
        readOnly={!canEdit || toggle.isPending}
        catalog={catalog}
        value={denied}
        onChange={(next) => {
          const entry = catalog.find(
            (candidate) => next.has(candidate.key) !== denied.has(candidate.key)
          );
          const permissionId = entry ? permissionIdByName.get(entry.key) : undefined;
          if (!entry || permissionId === undefined) return;
          toggle.mutate({ permissionId, deny: next.has(entry.key) });
        }}
      />

      {denies.length > 0 ? (
        <ul className="space-y-1 border-t border-border/60 pt-2">
          {denies.map((deny) => (
            <li
              key={`${deny.permission_id}-${deny.workspace_id ?? "global"}`}
              className="flex items-center gap-2 text-xs"
            >
              <span className="font-mono">{deny.name}</span>
              <span className="text-muted-foreground">
                {deny.workspace_id
                  ? (workspaces.find((workspace) => workspace.id === deny.workspace_id)?.name ??
                    `Workspace #${deny.workspace_id}`)
                  : "Global"}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
