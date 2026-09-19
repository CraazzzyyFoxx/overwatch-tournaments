"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Globe, MoreHorizontal, ShieldAlert, Trash2 } from "lucide-react";

import {
  PermissionPicker,
  type PermissionCatalogEntry
} from "@/components/admin/access/PermissionPicker";
import { SaveBar } from "@/components/kit/SaveBar";
import { TONE_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import type { RbacPermission, RbacRole, RbacRoleDetail } from "@/types/rbac.types";

interface RoleDraft {
  name: string;
  description: string;
  /** Permission NAMES, which is also what `PermissionPicker` speaks. */
  granted: Set<string>;
}

function sameNames(left: Set<string>, right: Set<string>): boolean {
  if (left.size !== right.size) return false;
  for (const name of left) {
    if (!right.has(name)) return false;
  }
  return true;
}

interface RoleEditorProps {
  role: RbacRole;
  /** Every permission grantable in this role's scope. */
  permissions: RbacPermission[];
  /** Name of the workspace the role belongs to; absent for a global role. */
  workspaceName?: string;
  canUpdate: boolean;
  canDelete: boolean;
  /** Raises the screen's single `ConfirmDialog`; the page owns the deletion. */
  onRequestDelete: () => void;
  /**
   * Reported up so the page can intercept a selection change: the draft is
   * local to this mount, and picking another role in the list unmounts it.
   * `SaveBar`'s own guard only sees anchor clicks, and the list is buttons.
   */
  onDirtyChange: (dirty: boolean) => void;
}

/**
 * The detail column of Roles (T4, F15): one role's metadata and its whole
 * permission bundle, saved through `SaveBar`.
 *
 * The screen this replaces put the same matrix inside a dialog, which forced a
 * 1440px-wide modal and hid the role list behind it while you worked. Here the
 * list stays beside the editor, and the draft is committed by an explicit save
 * rather than by closing a modal.
 *
 * Mount this with `key={role.id}`: the draft is local, and a new role must
 * start from its own baseline rather than inherit the previous one's edits.
 */
export function RoleEditor({ role, ...rest }: Readonly<RoleEditorProps>) {
  const detailQuery = useQuery({
    queryKey: ["access-admin", "roles", role.id],
    queryFn: () => rbacService.getRole(role.id)
  });

  const detail = detailQuery.data?.id === role.id ? detailQuery.data : undefined;
  if (!detail) {
    return <Skeleton className="h-72 w-full rounded-xl" />;
  }

  return <RoleForm detail={detail} {...rest} />;
}

/**
 * Split from the fetch above so the draft and the dirty-reporting effect sit
 * above every early return, and so a refetched role rebuilds its baseline.
 */
function RoleForm({
  detail,
  permissions,
  workspaceName,
  canUpdate,
  canDelete,
  onRequestDelete,
  onDirtyChange
}: Readonly<Omit<RoleEditorProps, "role"> & { detail: RbacRoleDetail }>) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<RoleDraft | null>(null);

  const saveMutation = useMutation({
    mutationFn: (payload: { name: string; description: string; permission_ids: number[] }) =>
      rbacService.updateRole(detail.id, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] })
      ]);
      setDraft(null);
      notify.success("Role updated");
    },
    onError: (error) => notify.apiError(error, { title: "Could not save the role" })
  });

  // A `resource.*` row in the catalogue is a wildcard, not a normal grant: it
  // covers every action on that resource, including ones added later. The
  // picker renders those apart and locks what they already cover.
  const wildcards = permissions
    .filter((permission) => permission.action === "*")
    .map((permission) => permission.name);
  const catalog: PermissionCatalogEntry[] = permissions
    .filter((permission) => permission.action !== "*")
    .map((permission) => ({
      key: permission.name,
      resource: permission.resource,
      action: permission.action,
      description: permission.description ?? undefined
    }));
  const permissionIdByName = new Map(
    permissions.map((permission) => [permission.name, permission.id])
  );

  const baseline: RoleDraft = {
    name: detail.name,
    description: detail.description ?? "",
    granted: new Set(detail.permissions.map((permission) => permission.name))
  };
  const current = draft ?? baseline;
  const readOnly = detail.is_system || !canUpdate;
  const changedCount =
    (current.name === baseline.name ? 0 : 1) +
    (current.description === baseline.description ? 0 : 1) +
    (sameNames(current.granted, baseline.granted) ? 0 : 1);
  const dirty = !readOnly && changedCount > 0;

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  const patch = (next: Partial<RoleDraft>) => setDraft({ ...(draft ?? baseline), ...next });

  return (
    <div className="min-w-0 rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-start gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="min-w-0 truncate font-display text-lg font-semibold text-foreground">
              {detail.name}
            </h2>
            <Badge tone={detail.is_system ? "neutral" : "info"} className="shrink-0">
              {detail.is_system ? "System role" : "Custom role"}
            </Badge>
          </div>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground">
            {detail.workspace_id ? (
              <>
                <Building2 aria-hidden className="size-3.5" />
                <span>{workspaceName ?? `Workspace #${detail.workspace_id}`}</span>
              </>
            ) : (
              <>
                <Globe aria-hidden className="size-3.5" />
                <span>Global</span>
              </>
            )}
            <span aria-hidden>·</span>
            <span className="tabular-nums">{detail.permissions.length} permissions</span>
          </p>
        </div>

        {canDelete && !detail.is_system ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon" variant="ghost" aria-label={`Actions for role ${detail.name}`}>
                <MoreHorizontal aria-hidden className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                className="gap-2 text-danger focus:text-danger"
                onSelect={onRequestDelete}
              >
                <Trash2 aria-hidden className="size-3.5" />
                Delete role
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>

      <div className="space-y-4 p-4">
        {detail.is_system ? (
          <p
            className={cn(
              "flex items-start gap-2 rounded-md border p-3 text-sm",
              TONE_CLASS.warning
            )}
          >
            <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            <span>
              System roles are defined by the platform and cannot be edited. Create a custom role
              to change what a group of people may do.
            </span>
          </p>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="role-name">Name</Label>
            <Input
              id="role-name"
              value={current.name}
              disabled={readOnly}
              placeholder="support_admin"
              onChange={(event) => patch({ name: event.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="role-description">Description</Label>
            <Input
              id="role-description"
              value={current.description}
              disabled={readOnly}
              placeholder="Describe what this role is allowed to do"
              onChange={(event) => patch({ description: event.target.value })}
            />
          </div>
        </div>

        <PermissionPicker
          mode="matrix"
          readOnly={readOnly}
          catalog={catalog}
          wildcards={wildcards}
          value={current.granted}
          onChange={(granted) => patch({ granted })}
        />

        <SaveBar
          dirty={dirty}
          saving={saveMutation.isPending}
          primaryLabel="Save role"
          summary={`${changedCount} change${changedCount === 1 ? "" : "s"} to ${detail.name}`}
          onDiscard={() => setDraft(null)}
          onSave={() =>
            saveMutation.mutate({
              name: current.name.trim(),
              description: current.description,
              permission_ids: [...current.granted]
                .map((name) => permissionIdByName.get(name))
                .filter((id): id is number => id !== undefined)
            })
          }
        />
      </div>
    </div>
  );
}
