"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Globe, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

// Self-service, allow-by-default capabilities an admin can revoke per user
// (negative RBAC). A toggle ON = denied for the selected scope. Governance
// permissions are not deniable (the backend rejects them).
const RESTRICTABLE_CAPABILITIES = [
  { name: "account.avatar", label: "Change own avatar" },
  { name: "account.social", label: "Manage own linked accounts" },
];

/** "global" = the deny applies everywhere; a number scopes it to one workspace. */
type DenyScope = "global" | number;

function scopeToWorkspaceId(scope: DenyScope): number | null {
  return scope === "global" ? null : scope;
}

export function UserDenyEditor({ userId, canEdit }: { userId: number; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const [scope, setScope] = useState<DenyScope>("global");
  const scopeWorkspaceId = scopeToWorkspaceId(scope);

  const deniesQuery = useQuery({
    queryKey: ["access-admin", "denies", userId],
    queryFn: () => rbacService.getUserDenies(userId),
  });
  const permsQuery = useQuery({
    queryKey: ["access-admin", "permissions", "account"],
    queryFn: () => rbacService.listPermissionsAll({ search: "account" }),
  });

  const denies = deniesQuery.data ?? [];
  const permIdByName = useMemo(() => {
    const map = new Map<string, number>();
    for (const perm of permsQuery.data ?? []) map.set(perm.name, perm.id);
    return map;
  }, [permsQuery.data]);

  const workspaceLabel = (workspaceId: number | null | undefined): string => {
    if (workspaceId == null) return "Global";
    return workspaces.find((ws) => ws.id === workspaceId)?.name ?? `Workspace #${workspaceId}`;
  };

  const toggle = useMutation({
    mutationFn: ({
      permissionId,
      deny,
      workspaceId,
    }: {
      permissionId: number;
      deny: boolean;
      workspaceId: number | null;
    }) =>
      deny
        ? rbacService.addUserDeny(userId, permissionId, workspaceId)
        : rbacService.removeUserDeny(userId, permissionId, workspaceId),
    onSuccess: (updatedDenies) =>
      queryClient.setQueryData(["access-admin", "denies", userId], updatedDenies),
  });

  const loading = deniesQuery.isLoading || permsQuery.isLoading;

  return (
    <div className="space-y-3 rounded-lg border border-border/60 bg-card/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Restricted actions
          </h3>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Scope:</span>
          <Select
            value={String(scope)}
            onValueChange={(value) => setScope(value === "global" ? "global" : Number(value))}
          >
            <SelectTrigger className="h-8 w-[180px] text-xs" disabled={!canEdit}>
              <SelectValue placeholder="Select scope" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="global">
                <div className="flex items-center gap-2">
                  <Globe className="h-3.5 w-3.5" />
                  Global
                </div>
              </SelectItem>
              {workspaces.map((ws) => (
                <SelectItem key={ws.id} value={String(ws.id)}>
                  <div className="flex items-center gap-2">
                    <Building2 className="h-3.5 w-3.5" />
                    {ws.name}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Revoke self-service capabilities for this user in the selected scope. A restriction overrides
        any grant (including superuser) for that exact action, in that scope only.
      </p>
      <div className="space-y-2">
        {RESTRICTABLE_CAPABILITIES.map((capability) => {
          const permissionId = permIdByName.get(capability.name);
          const denied = denies.some(
            (d) => d.name === capability.name && (d.workspace_id ?? null) === scopeWorkspaceId
          );
          return (
            <label
              key={capability.name}
              className="flex items-center justify-between gap-3 rounded-md border border-border/60 p-3"
            >
              <span className="text-sm">{capability.label}</span>
              <Switch
                checked={denied}
                disabled={!canEdit || permissionId === undefined || toggle.isPending}
                onCheckedChange={(checked) =>
                  permissionId !== undefined &&
                  toggle.mutate({ permissionId, deny: checked, workspaceId: scopeWorkspaceId })
                }
                aria-label={`Restrict: ${capability.label} (${workspaceLabel(scopeWorkspaceId)})`}
              />
            </label>
          );
        })}
      </div>

      {denies.length > 0 && (
        <div className="space-y-1.5 border-t border-border/60 pt-3">
          <p className="text-xs font-medium text-muted-foreground">Active restrictions</p>
          <ul className="space-y-1.5">
            {denies.map((deny) => {
              const capability = RESTRICTABLE_CAPABILITIES.find((c) => c.name === deny.name);
              const label = capability?.label ?? deny.name;
              return (
                <li
                  key={`${deny.permission_id}-${deny.workspace_id ?? "global"}`}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="flex items-center gap-2">
                    <span>{label}</span>
                    <Badge variant="outline" className="gap-1 text-[10px]">
                      {deny.workspace_id ? (
                        <Building2 className="h-3 w-3" />
                      ) : (
                        <Globe className="h-3 w-3" />
                      )}
                      {workspaceLabel(deny.workspace_id)}
                    </Badge>
                  </span>
                  {canEdit && (
                    <button
                      type="button"
                      className="text-muted-foreground transition-colors hover:text-destructive disabled:opacity-40"
                      disabled={toggle.isPending}
                      onClick={() =>
                        toggle.mutate({
                          permissionId: deny.permission_id,
                          deny: false,
                          workspaceId: deny.workspace_id ?? null,
                        })
                      }
                      aria-label={`Remove restriction: ${label} (${workspaceLabel(deny.workspace_id)})`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
