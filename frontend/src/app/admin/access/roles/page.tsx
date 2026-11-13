"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { RoleEditor } from "@/components/admin/access/RoleEditor";
import { RoleList } from "@/components/admin/access/RoleList";
import { RoleScopeSelect, useRoleScope } from "@/components/admin/access/RoleScopeSelect";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { MasterDetail } from "@/components/kit/MasterDetail";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RbacRole } from "@/types/rbac.types";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { useTranslations } from "next-intl";

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
  const t = useTranslations("adminAccess.rolesUi");
  const tc = useTranslations("adminAccess.common");
  const queryClient = useQueryClient();
  const { hasPermission, canAccessPermission } = usePermissions();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const { searchParams, setParams } = useQueryParams({ mode: "push" });
  const { options: scopeOptions, scope, workspaceId } = useRoleScope();

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
      notify.success(t("created"), { description: t("createdDescription") });
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
      notify.success(t("deleted"));
    },
    onError: (error) => notify.apiError(error, { title: t("deleteError") })
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
        title={t("loadError")}
        onAction={() => void rolesQuery.refetch()}
        actionLabel={tc("tryAgain")}
      />
    );
  }

  return (
    <div>
      {rolesQuery.isLoading ? (
        <Skeleton className="h-72 w-full rounded-xl" />
      ) : (
        <MasterDetail
          list={
            <RoleList
              roles={roles}
              selectedRoleId={selectedRole?.id ?? null}
              onSelect={selectRole}
              actions={
                scopeOptions.length > 1 || canCreateRole ? (
                  <div className="flex items-center gap-2">
                    <RoleScopeSelect
                      options={scopeOptions}
                      value={String(scope)}
                      onValueChange={(value) => setParams({ scope: value, role: null })}
                      className="min-w-0 flex-1"
                    />
                    {canCreateRole ? (
                      <Button
                        size="sm"
                        className="ml-auto shrink-0"
                        onClick={() => {
                          createMutation.reset();
                          setCreateOpen(true);
                        }}
                      >
                        <Plus aria-hidden className="size-4" />
                        {tc("createRole")}
                      </Button>
                    ) : null}
                  </div>
                ) : null
              }
            />
          }
          detail={
            selectedRole ? (
              permissionsQuery.isError && !permissionsQuery.data ? (
                <PageStateCard
                  state="error"
                  title={t("permissionsLoadError")}
                  onAction={() => void permissionsQuery.refetch()}
                />
              ) : permissionsQuery.isLoading ? (
                <Skeleton className="h-72 w-full rounded-xl" />
              ) : (
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
              )
            ) : null
          }
          emptyDetail={
            <PageStateCard
              state="empty"
              title={roles.length > 0 ? t("noSelected") : t("noScopeRoles")}
              description={
                roles.length > 0
                  ? t("pickRole")
                  : t("createForGroup")
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
        title={tc("createRole")}
        description={t("createDescription", { scope:
          workspaceId === null
            ? tc("global")
            : (workspaces.find((workspace) => workspace.id === workspaceId)?.name ?? tc("workspace"))
        })}
        submitLabel={tc("createRole")}
        submittingLabel={t("creating")}
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
            <Label htmlFor="create-role-name">{tc("name")}</Label>
            <Input
              id="create-role-name"
              required
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="create-role-description">{tc("description")}</Label>
            <Input
              id="create-role-description"
              value={createDescription}
              placeholder={t("descriptionPlaceholder")}
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
                title: t("discardTitle"),
                description: t("discardDescription"),
                confirmLabel: t("discardChanges"),
                tone: "warning"
              }
            : {
                title: tc("deleteRole"),
                description: t("deleteDescription", { name: pending?.kind === "delete" ? pending.role.name : t("thisRole") }),
                confirmLabel: tc("deleteRole"),
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
