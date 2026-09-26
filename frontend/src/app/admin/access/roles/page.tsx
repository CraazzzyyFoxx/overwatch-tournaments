"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { RoleEditor } from "@/components/admin/access/RoleEditor";
import { RoleList } from "@/components/admin/access/RoleList";
import { FilterBar } from "@/components/kit/FilterBar";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { MasterDetail } from "@/components/kit/MasterDetail";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RbacRole } from "@/types/rbac.types";
import { accessQueryKeys } from "@/lib/access/query-keys";

/** The `scope` chip's value for roles with `workspace_id IS NULL`. */
const GLOBAL_SCOPE = "global";

/**
 * Roles (T4, F15): the roles of one scope on the left, one role's editor on
 * the right.
 *
 * `?role=` is written with `mode: "push"` on purpose — below `md`
 * `MasterDetail` shows either the list or the editor, and its "Back to list"
 * button steps the history entry back, so a `replace` here would trap the user
 * in the editor.
 */
export default function AccessAdminRolesPage() {
  const queryClient = useQueryClient();
  const { hasPermission, isSuperuser, canAccessPermission, canAccessAnyPermission } =
    usePermissions();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const { searchParams, setParams } = useQueryParams({ mode: "push" });

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  /**
   * The screen's single `ConfirmDialog` serves both interruptions: deleting a
   * role, and leaving an unsaved draft behind by picking another one.
   */
  const [pending, setPending] = useState<
    { kind: "delete"; role: RbacRole } | { kind: "switch"; roleId: number } | null
  >(null);

  const canReadGlobalRoles = isSuperuser || hasPermission("role.read");
  const adminWorkspaces = workspaces.filter(
    (workspace) =>
      isSuperuser ||
      canAccessAnyPermission(
        ["role.read", "role.create", "role.update", "role.delete"],
        workspace.id
      )
  );

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "scope",
        label: "Scope",
        kind: "single",
        options: [
          ...(canReadGlobalRoles ? [{ value: GLOBAL_SCOPE, label: "Global" }] : []),
          ...adminWorkspaces.map((workspace) => ({
            value: String(workspace.id),
            label: workspace.name
          }))
        ]
      }
    ],
    [canReadGlobalRoles, adminWorkspaces]
  );
  const filters = useFilters(defs);

  // Falls back to whatever the reader may actually see: a workspace admin
  // without the global `role.read` would otherwise land on an empty Global
  // scope and think there are no roles at all.
  const scopeParam = String(filters.values.scope ?? "");
  const requestedScope =
    scopeParam === "" ? (canReadGlobalRoles ? GLOBAL_SCOPE : "") : scopeParam;
  const scope: string | number =
    requestedScope === GLOBAL_SCOPE
      ? GLOBAL_SCOPE
      : requestedScope === ""
        ? (adminWorkspaces[0]?.id ?? GLOBAL_SCOPE)
        : Number(requestedScope);
  const workspaceId = scope === GLOBAL_SCOPE ? null : (scope as number);

  const canReadPermissions =
    workspaceId === null
      ? hasPermission("permission.read")
      : canAccessPermission("permission.read", workspaceId);
  const canCreateRole =
    (workspaceId === null
      ? hasPermission("role.create")
      : canAccessPermission("role.create", workspaceId)) && canReadPermissions;
  const canUpdateRole =
    (workspaceId === null
      ? hasPermission("role.update")
      : canAccessPermission("role.update", workspaceId)) && canReadPermissions;
  const canDeleteRole =
    workspaceId === null
      ? hasPermission("role.delete")
      : canAccessPermission("role.delete", workspaceId);

  const rolesQuery = useQuery({
    queryKey: accessQueryKeys.rolesByScope(scope),
    queryFn: () => rbacService.listRolesAll({ workspace_id: workspaceId })
  });

  const permissionsQuery = useQuery({
    queryKey: accessQueryKeys.permissionsByScope(scope),
    queryFn: () =>
      rbacService.listPermissionsAll(workspaceId === null ? undefined : { workspace_id: workspaceId }),
    enabled: canReadPermissions
  });

  const roles = rolesQuery.data ?? [];
  const roleParam = Number(searchParams?.get("role"));
  const selectedRole = roles.find((role) => role.id === roleParam) ?? null;

  const createMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: () =>
      rbacService.createRole({
        name: createName.trim(),
        description: createDescription,
        permission_ids: [],
        workspace_id: workspaceId
      }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: accessQueryKeys.roles() });
      setCreateOpen(false);
      setCreateName("");
      setCreateDescription("");
      notify.success("Role created", { description: "Now grant it the permissions it needs." });
      setParams({ role: created.id });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (roleId: number) => rbacService.deleteRole(roleId),
    onSuccess: async (_result, roleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: accessQueryKeys.roles() }),
        queryClient.invalidateQueries({ queryKey: accessQueryKeys.users() })
      ]);
      setPending(null);
      if (roleId === roleParam) setParams({ role: null });
      notify.success("Role deleted");
    },
    onError: (error) => notify.apiError(error, { title: "Could not delete the role" })
  });

  // The role list is buttons, not links, because `MasterDetail`'s narrow-mode
  // Back needs the selection PUSHED through `useQueryParams`. `SaveBar`'s
  // guard only sees anchors, so the interception for an unsaved draft is here.
  const selectRole = (roleId: number) => {
    if (editorDirty && roleId !== roleParam) {
      setPending({ kind: "switch", roleId });
      return;
    }
    setParams({ role: roleId });
  };

  if (rolesQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load the roles"
        onAction={() => void rolesQuery.refetch()}
        actionLabel="Try again"
      />
    );
  }

  return (
    <div className="space-y-4">
      <FilterBar
        defs={defs}
        filters={filters}
        trailing={
          canCreateRole ? (
            <Button
              size="sm"
              onClick={() => {
                createMutation.reset();
                setCreateOpen(true);
              }}
            >
              <Plus aria-hidden className="size-4" />
              Create role
            </Button>
          ) : undefined
        }
      />

      {rolesQuery.isLoading ? (
        <Skeleton className="h-72 w-full rounded-xl" />
      ) : (
        <MasterDetail
          listWidth={260}
          list={
            <RoleList
              roles={roles}
              selectedRoleId={selectedRole?.id ?? null}
              onSelect={selectRole}
            />
          }
          detail={
            selectedRole ? (
              <RoleEditor
                key={selectedRole.id}
                role={selectedRole}
                permissions={permissionsQuery.data ?? []}
                workspaceName={
                  workspaces.find((workspace) => workspace.id === selectedRole.workspace_id)?.name
                }
                canUpdate={canUpdateRole}
                canDelete={canDeleteRole}
                onRequestDelete={() => setPending({ kind: "delete", role: selectedRole })}
                onDirtyChange={setEditorDirty}
              />
            ) : null
          }
          emptyDetail={
            <PageStateCard
              state="empty"
              title={roles.length > 0 ? "No role selected" : "No roles in this scope"}
              description={
                roles.length > 0
                  ? "Pick a role on the left to see and change the permissions it bundles."
                  : "Create a role to bundle the permissions a group of people needs."
              }
            />
          }
        />
      )}

      <EntityFormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) {
            createMutation.reset();
            setCreateName("");
            setCreateDescription("");
          }
        }}
        title="Create role"
        description={`Name the role, then grant its permissions in the editor. It is created in the ${
          workspaceId === null
            ? "global"
            : (workspaces.find((workspace) => workspace.id === workspaceId)?.name ?? "workspace")
        } scope.`}
        submitLabel="Create role"
        submittingLabel="Creating role…"
        isSubmitting={createMutation.isPending}
        errorMessage={createMutation.error instanceof Error ? createMutation.error.message : undefined}
        isDirty={createName.trim().length > 0 || createDescription.length > 0}
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (!createName.trim()) return;
          createMutation.mutate();
        }}
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="create-role-name">Name</Label>
            <Input
              id="create-role-name"
              required
              value={createName}
              placeholder="support_admin"
              onChange={(event) => setCreateName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="create-role-description">Description</Label>
            <Input
              id="create-role-description"
              value={createDescription}
              placeholder="Describe what this role is allowed to do"
              onChange={(event) => setCreateDescription(event.target.value)}
            />
          </div>
        </div>
      </EntityFormDialog>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        pending={deleteMutation.isPending}
        intent={
          pending?.kind === "switch"
            ? {
                title: "Discard unsaved changes?",
                description:
                  "This role has unsaved changes. Open another role now and the current edits will be lost.",
                confirmLabel: "Discard changes",
                tone: "warning"
              }
            : {
                title: "Delete role",
                description: `Deleting “${pending?.kind === "delete" ? pending.role.name : "this role"}” removes the definition permanently. Everyone assigned to it immediately loses the access it granted. This cannot be undone.`,
                confirmLabel: "Delete role",
                tone: "danger"
              }
        }
        onConfirm={() => {
          if (pending === null) return;
          if (pending.kind === "switch") {
            const roleId = pending.roleId;
            setPending(null);
            setEditorDirty(false);
            setParams({ role: roleId });
            return;
          }
          deleteMutation.mutate(pending.role.id);
        }}
      />
    </div>
  );
}
