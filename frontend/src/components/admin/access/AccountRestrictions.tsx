"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Globe } from "lucide-react";

import { AccountDisclosure } from "@/components/admin/access/AccountCard";
import {
  PermissionPicker,
  type PermissionCatalogEntry
} from "@/components/admin/access/PermissionPicker";
import { TONE_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
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
import { Spinner } from "@/components/ui/spinner";
import { accessQueryKeys } from "@/lib/access/query-keys";

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
    key: "account.rename",
    resource: "account",
    action: "rename",
    description: "Change own name"
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
    key: "custom_game.self_join",
    resource: "custom_game",
    action: "self_join",
    description: "Self-join pickup mixes"
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
 * Collapsed by default: most accounts have none, and a six-row red panel on
 * every account buried the roles above it. Active denies stay visible as chips
 * while collapsed, so a restricted account never reads as unrestricted.
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
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<DenyScope>("global");
  const scopeId = useId();
  const scopeWorkspaceId = scope === "global" ? null : scope;

  const deniesQuery = useQuery({
    queryKey: accessQueryKeys.denies(userId),
    queryFn: () => rbacService.getUserDenies(userId)
  });
  const permissionsQuery = useQuery({
    // The whole inventory, not a `search` narrowed to one resource: the
    // restrictable capabilities span three resources now, and a row whose
    // permission id is missing here is silently dropped from the picker below.
    // Only once opened — the collapsed line needs the denies alone.
    queryKey: accessQueryKeys.permissionsInventory(),
    queryFn: () => rbacService.listPermissionsAll(),
    enabled: open
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
      queryClient.setQueryData(accessQueryKeys.denies(userId), updated),
    onError: (error) => notify.apiError(error, { title: "Could not change the restriction" })
  });

  const catalog = RESTRICTABLE.filter(
    (entry) => permissionIdByName.get(entry.key) !== undefined
  );

  const scopeLabel = (workspaceId: number | null | undefined) =>
    workspaceId
      ? (workspaces.find((workspace) => workspace.id === workspaceId)?.name ??
        `Workspace #${workspaceId}`)
      : "Global";

  return (
    <AccountDisclosure
      title="Restrictions"
      open={open}
      onOpenChange={setOpen}
      summary={
        deniesQuery.isLoading ? (
          <Spinner className="size-3.5" />
        ) : denies.length === 0 ? (
          "None"
        ) : (
          <span className="text-danger">{denies.length} active</span>
        )
      }
      preview={
        denies.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Active restrictions">
            {denies.map((deny) => (
              <li key={`${deny.permission_id}-${deny.workspace_id ?? "global"}`}>
                <Badge tone="danger" className="font-normal">
                  <span className="font-mono">{deny.name}</span>
                  <span className="opacity-80">· {scopeLabel(deny.workspace_id)}</span>
                </Badge>
              </li>
            ))}
          </ul>
        ) : null
      }
    >
      <div className={cn("space-y-2 rounded-lg border p-3", TONE_CLASS.danger)}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label htmlFor={scopeId} className="text-xs text-muted-foreground">
            Scope
          </Label>
          <Select
            value={String(scope)}
            onValueChange={(value) => setScope(value === "global" ? "global" : Number(value))}
          >
            <SelectTrigger id={scopeId} className="h-8 w-44 text-xs" disabled={!canEdit}>
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

        <p className="text-xs text-muted-foreground">
          A checked capability is revoked in the selected scope. It beats every grant, superuser
          included, for that exact action in that scope only.
        </p>

        {permissionsQuery.isLoading ? (
          <Spinner className="size-4 text-muted-foreground" />
        ) : (
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
        )}
      </div>
    </AccountDisclosure>
  );
}
