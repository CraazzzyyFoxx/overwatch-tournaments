"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { rbacService } from "@/services/rbac.service";

// Self-service, allow-by-default capabilities an admin can revoke per user
// (negative RBAC). A toggle ON = denied. Governance permissions are not
// deniable (the backend rejects them).
const RESTRICTABLE_CAPABILITIES = [
  { name: "account.avatar", label: "Change own avatar" },
  { name: "account.social", label: "Manage own linked accounts" },
];

export function UserDenyEditor({ userId, canEdit }: { userId: number; canEdit: boolean }) {
  const queryClient = useQueryClient();

  const deniesQuery = useQuery({
    queryKey: ["access-admin", "denies", userId],
    queryFn: () => rbacService.getUserDenies(userId),
  });
  const permsQuery = useQuery({
    queryKey: ["access-admin", "permissions", "account"],
    queryFn: () => rbacService.listPermissionsAll({ search: "account" }),
  });

  const deniedNames = useMemo(
    () => new Set((deniesQuery.data ?? []).map((d) => d.name)),
    [deniesQuery.data],
  );
  const permIdByName = useMemo(() => {
    const map = new Map<string, number>();
    for (const perm of permsQuery.data ?? []) map.set(perm.name, perm.id);
    return map;
  }, [permsQuery.data]);

  const toggle = useMutation({
    mutationFn: ({ permissionId, deny }: { permissionId: number; deny: boolean }) =>
      deny ? rbacService.addUserDeny(userId, permissionId) : rbacService.removeUserDeny(userId, permissionId),
    onSuccess: (denies) => queryClient.setQueryData(["access-admin", "denies", userId], denies),
  });

  const loading = deniesQuery.isLoading || permsQuery.isLoading;

  return (
    <div className="space-y-3 rounded-lg border border-border/60 bg-card/60 p-4">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Restricted actions</h3>
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
      </div>
      <p className="text-xs text-muted-foreground">
        Revoke self-service capabilities for this user. A restriction overrides any grant (including superuser) for that exact action.
      </p>
      <div className="space-y-2">
        {RESTRICTABLE_CAPABILITIES.map((capability) => {
          const permissionId = permIdByName.get(capability.name);
          const denied = deniedNames.has(capability.name);
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
                  permissionId !== undefined && toggle.mutate({ permissionId, deny: checked })
                }
                aria-label={`Restrict: ${capability.label}`}
              />
            </label>
          );
        })}
      </div>
    </div>
  );
}
