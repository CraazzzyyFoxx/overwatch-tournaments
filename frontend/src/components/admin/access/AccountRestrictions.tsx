"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Globe } from "lucide-react";

import { AccountDisclosure } from "@/components/admin/access/AccountCard";
import {
  PermissionPicker,
  type PermissionCatalogEntry
} from "@/components/admin/access/PermissionPicker";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Skeleton } from "@/components/ui/skeleton";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { useTranslations } from "next-intl";

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
const RESTRICTABLE: Array<Omit<PermissionCatalogEntry, "description"> & { descriptionKey: string }> = [
  {
    key: "account.avatar",
    resource: "account",
    action: "avatar",
    descriptionKey: "avatar"
  },
  {
    key: "account.rename",
    resource: "account",
    action: "rename",
    descriptionKey: "rename"
  },
  {
    key: "account.social",
    resource: "account",
    action: "social",
    descriptionKey: "social"
  },
  {
    key: "registration.self_register",
    resource: "registration",
    action: "self_register",
    descriptionKey: "registration"
  },
  {
    key: "custom_game.self_join",
    resource: "custom_game",
    action: "self_join",
    descriptionKey: "pickup"
  },
  {
    key: "workspace.self_create",
    resource: "workspace",
    action: "self_create",
    descriptionKey: "createWorkspace"
  }
];

/** "global" = the deny applies everywhere; a number scopes it to one workspace. */
type DenyScope = "global" | number;

/**
 * Restrictions for one auth account — the same `PermissionPicker` as roles and
 * API keys, read as "what this account may NOT do".
 *
 * Collapsed by default: most accounts have none, and a six-row red panel on
 * every account buried the roles above it. Active denies stay listed while
 * collapsed, so a restricted account never reads as unrestricted; open, the
 * checked rows say it.
 */
export function AccountRestrictions({
  userId,
  canEdit
}: Readonly<{ userId: number; canEdit: boolean }>) {
  const t = useTranslations("adminAccess.restrictionsUi");
  const tc = useTranslations("adminAccess.common");
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
    onError: (error) => notify.apiError(error, { title: t("error") })
  });

  const catalog: PermissionCatalogEntry[] = RESTRICTABLE.filter(
    (entry) => permissionIdByName.get(entry.key) !== undefined
  ).map(({ descriptionKey, ...entry }) => ({
    ...entry,
    description: t(descriptionKey as "avatar" | "rename" | "social" | "registration" | "pickup" | "createWorkspace")
  }));

  const scopeLabel = (workspaceId: number | null | undefined) =>
    workspaceId
      ? (workspaces.find((workspace) => workspace.id === workspaceId)?.name ??
        tc("workspaceFallback", { id: workspaceId }))
      : t("global");

  return (
    <AccountDisclosure
      title={t("title")}
      open={open}
      onOpenChange={setOpen}
      summary={
        deniesQuery.isLoading ? undefined : denies.length === 0 ? (
          t("none")
        ) : (
          <span className="text-danger">{t("active", { count: denies.length })}</span>
        )
      }
      preview={
        !open && denies.length > 0 ? (
          <ul className="space-y-0.5 text-caption text-danger" aria-label={t("activeLabel")}>
            {denies.map((deny) => (
              <li key={`${deny.permission_id}-${deny.workspace_id ?? "global"}`}>
                <span className="font-mono">{deny.name}</span> · {scopeLabel(deny.workspace_id)}
              </li>
            ))}
          </ul>
        ) : null
      }
    >
      <div className="space-y-2">
        {workspaces.length > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label htmlFor={scopeId} className="text-xs text-muted-foreground">
              {t("scope")}
            </Label>
            <Select
              value={String(scope)}
              onValueChange={(value) => setScope(value === "global" ? "global" : Number(value))}
            >
              <SelectTrigger id={scopeId} size="sm" className="w-44">
                <SelectValue placeholder={t("selectScope")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="global">
                  <span className="flex items-center gap-2">
                    <Globe aria-hidden className="size-3.5" />
                    {t("global")}
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
        ) : null}

        <p className="text-xs text-muted-foreground">
          {t("notice")}
        </p>

        {permissionsQuery.isLoading ? (
          <Skeleton className="h-32 w-full" />
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
