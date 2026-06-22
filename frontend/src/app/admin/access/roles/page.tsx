"use client";

import { useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import {
  Building2,
  CheckSquare,
  Eye,
  Globe,
  Lock,
  MoreHorizontal,
  Pencil,
  Plus,
  ShieldAlert,
  Trash2,
  Wrench,
  XSquare
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  RbacPermission,
  RbacRole,
  RbacRoleDetail,
  UpsertRolePayload
} from "@/types/rbac.types";

const PAGE_SIZE = 15;
const ACTION_ORDER = [
  "*",
  "read",
  "create",
  "update",
  "delete",
  "assign",
  "import",
  "export",
  "sync",
  "recalculate",
  "calculate",
  "publish",
  "generate",
  "approve",
  "reject",
  "check_in",
  "upload",
  "stream",
  "reprocess",
  "revoke"
];

/** "global" = global roles (workspace_id IS NULL), number = workspace-scoped */
type RoleScope = "global" | number;

function formatPermissionLabel(value: string): string {
  if (value === "*") {
    return "All";
  }
  return value.replaceAll("_", " ");
}

function sortActions(left: string, right: string): number {
  const leftIndex = ACTION_ORDER.indexOf(left);
  const rightIndex = ACTION_ORDER.indexOf(right);
  if (leftIndex !== -1 || rightIndex !== -1) {
    return (
      (leftIndex === -1 ? ACTION_ORDER.length : leftIndex) -
      (rightIndex === -1 ? ACTION_ORDER.length : rightIndex)
    );
  }
  return left.localeCompare(right);
}

function samePermissionIds(left: number[], right: number[]): boolean {
  if (left.length !== right.length) {
    return false;
  }
  const rightIds = new Set(right);
  return left.every((permissionId) => rightIds.has(permissionId));
}

function hasRoleFormChanges(current: UpsertRolePayload, initial: UpsertRolePayload): boolean {
  return (
    current.name !== initial.name ||
    (current.description || "") !== (initial.description || "") ||
    !samePermissionIds(current.permission_ids, initial.permission_ids)
  );
}

const emptyRoleForm: UpsertRolePayload = {
  name: "",
  description: "",
  permission_ids: []
};

function roleToForm(role: RbacRoleDetail): UpsertRolePayload {
  return {
    name: role.name,
    description: role.description || "",
    permission_ids: role.permissions.map((permission) => permission.id)
  };
}

type PermissionMatrixRow = {
  resource: string;
  permissions: RbacPermission[];
  permissionIds: number[];
  byAction: Map<string, RbacPermission>;
};

type PermissionMatrixColumn = {
  action: string;
  permissionIds: number[];
};

function MatrixCheckbox({
  checked,
  disabled,
  label,
  onChange
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <input
      type="checkbox"
      className="h-4 w-4 shrink-0 cursor-pointer rounded border border-primary bg-background accent-primary disabled:cursor-not-allowed disabled:opacity-40"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      onChange={(event) => onChange(event.currentTarget.checked)}
    />
  );
}

export default function AccessAdminRolesPage() {
  const queryClient = useQueryClient();
  const { hasPermission, isSuperuser, canAccessPermission, canAccessAnyPermission } =
    usePermissions();

  const { workspaces } = useWorkspaceStore();
  const adminWorkspaces = workspaces.filter(
    (ws) =>
      isSuperuser ||
      canAccessAnyPermission(
        ["role.read", "role.create", "role.update", "role.delete", "role.assign"],
        ws.id
      )
  );

  // Scope selector: "global" or a workspace id
  const [selectedScope, setSelectedScope] = useState<RoleScope>("global");
  const canReadGlobalRoles = isSuperuser || hasPermission("role.read");
  const effectiveScope =
    selectedScope === "global" && !canReadGlobalRoles && adminWorkspaces[0]
      ? adminWorkspaces[0].id
      : selectedScope;

  // For global scope: use global RBAC permissions
  // For workspace scope: user just needs to be workspace admin
  const canReadPermissions =
    effectiveScope === "global"
      ? hasPermission("permission.read")
      : typeof effectiveScope === "number" &&
        canAccessPermission("permission.read", effectiveScope);
  const canManageInScope =
    effectiveScope === "global"
      ? hasPermission("role.create") && canReadPermissions
      : typeof effectiveScope === "number" && canAccessPermission("role.create", effectiveScope);
  const canCreateRole = canManageInScope && canReadPermissions;
  const canUpdateRole =
    effectiveScope === "global"
      ? hasPermission("role.update") && canReadPermissions
      : typeof effectiveScope === "number" &&
        canAccessPermission("role.update", effectiveScope) &&
        canReadPermissions;
  const canDeleteRole =
    effectiveScope === "global"
      ? hasPermission("role.delete")
      : typeof effectiveScope === "number" && canAccessPermission("role.delete", effectiveScope);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingRoleId, setEditingRoleId] = useState<number | null>(null);
  const [deletingRole, setDeletingRole] = useState<RbacRole | null>(null);
  const [formOverride, setFormOverride] = useState<UpsertRolePayload | null>(emptyRoleForm);
  const [isReadOnly, setIsReadOnly] = useState(false);

  const permissionsQuery = useQuery({
    queryKey: ["access-admin", "permissions", effectiveScope],
    queryFn: () =>
      rbacService.listPermissionsAll(
        effectiveScope === "global" ? undefined : { workspace_id: effectiveScope }
      ),
    enabled: canReadPermissions && (createDialogOpen || editingRoleId !== null)
  });

  const roleDetailQuery = useQuery({
    queryKey: ["access-admin", "roles", editingRoleId],
    queryFn: () => rbacService.getRole(editingRoleId as number),
    enabled: editingRoleId !== null
  });

  const createRoleMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (payload: UpsertRolePayload) => rbacService.createRole(payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "permissions"] })
      ]);
      setCreateDialogOpen(false);
      setFormOverride(emptyRoleForm);
      notify.success("Role created");
    }
  });

  const updateRoleMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: ({ id, payload }: { id: number; payload: Partial<UpsertRolePayload> }) =>
      rbacService.updateRole(id, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] })
      ]);
      setEditingRoleId(null);
      setFormOverride(emptyRoleForm);
      notify.success("Role updated");
    }
  });

  const deleteRoleMutation = useMutation({
    mutationFn: (roleId: number) => rbacService.deleteRole(roleId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] })
      ]);
      setDeletingRole(null);
      notify.success("Role deleted");
    }
  });

  const columns: ColumnDef<RbacRole>[] = [
    {
      accessorKey: "name",
      header: "Role"
    },
    {
      accessorKey: "description",
      header: "Description",
      enableSorting: false,
      cell: ({ row }) =>
        row.original.description || <span className="text-muted-foreground">No description</span>
    },
    {
      id: "scope",
      header: "Scope",
      cell: ({ row }) => {
        const role = row.original;
        if (role.workspace_id) {
          const ws = workspaces.find((w) => w.id === role.workspace_id);
          return (
            <div className="flex items-center gap-1.5">
              <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-sm">{ws?.name ?? `#${role.workspace_id}`}</span>
            </div>
          );
        }
        return (
          <div className="flex items-center gap-1.5">
            <Globe className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-sm">Global</span>
          </div>
        );
      }
    },
    {
      id: "system",
      header: "Type",
      cell: ({ row }) =>
        row.original.is_system ? (
          <StatusIcon icon={Lock} label="System" variant="muted" />
        ) : (
          <StatusIcon icon={Wrench} label="Custom" variant="info" />
        )
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const role = row.original;

        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Open actions for role ${role.name}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              <DropdownMenuItem
                onClick={() => {
                  updateRoleMutation.reset();
                  setFormOverride(null);
                  setEditingRoleId(role.id);
                  setIsReadOnly(true);
                }}
              >
                <Eye className="mr-2 h-4 w-4" />
                View
              </DropdownMenuItem>
              {canUpdateRole && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={role.is_system}
                    onClick={() => {
                      updateRoleMutation.reset();
                      setFormOverride(null);
                      setEditingRoleId(role.id);
                      setIsReadOnly(false);
                    }}
                  >
                    <Pencil className="mr-2 h-4 w-4" />
                    Edit
                  </DropdownMenuItem>
                </>
              )}
              {canDeleteRole && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    disabled={role.is_system}
                    onClick={() => setDeletingRole(role)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      }
    }
  ];

  const permissionMatrix = useMemo(() => {
    const groups = new Map<string, RbacPermission[]>();
    const actions = new Set<string>();

    for (const permission of permissionsQuery.data ?? []) {
      actions.add(permission.action);
      const current = groups.get(permission.resource) ?? [];
      current.push(permission);
      groups.set(permission.resource, current);
    }

    const rows: PermissionMatrixRow[] = Array.from(groups.entries())
      .map(([resource, permissions]) => {
        const sortedPermissions = [...permissions].sort((left, right) =>
          sortActions(left.action, right.action)
        );
        return {
          resource,
          permissions: sortedPermissions,
          permissionIds: sortedPermissions.map((permission) => permission.id),
          byAction: new Map(sortedPermissions.map((permission) => [permission.action, permission]))
        };
      })
      .sort((left, right) => left.resource.localeCompare(right.resource));

    const sortedActions = Array.from(actions).sort(sortActions);
    const columns: PermissionMatrixColumn[] = sortedActions.map((action) => ({
      action,
      permissionIds: rows
        .map((row) => row.byAction.get(action)?.id)
        .filter((permissionId): permissionId is number => permissionId !== undefined)
    }));

    return {
      columns,
      rows,
      allPermissionIds: rows.flatMap((row) => row.permissionIds)
    };
  }, [permissionsQuery.data]);

  const isSubmitting = createRoleMutation.isPending || updateRoleMutation.isPending;
  const isEditing = editingRoleId !== null;
  const roleDetail = roleDetailQuery.data?.id === editingRoleId ? roleDetailQuery.data : undefined;
  const currentBaseline = useMemo(
    () => (isEditing && roleDetail ? roleToForm(roleDetail) : emptyRoleForm),
    [isEditing, roleDetail]
  );
  const formData = formOverride ?? currentBaseline;
  const selectedPermissionIds = useMemo(
    () => new Set(formData.permission_ids),
    [formData.permission_ids]
  );
  const permissionSelectionStats = useMemo(() => {
    const selectedIds = selectedPermissionIds;
    const rowSelectedCounts = new Map<string, number>();
    const rowChecked = new Map<string, boolean>();
    const columnChecked = new Map<string, boolean>();

    for (const row of permissionMatrix.rows) {
      const selectedCount = row.permissionIds.filter((permissionId) =>
        selectedIds.has(permissionId)
      ).length;
      rowSelectedCounts.set(row.resource, selectedCount);
      rowChecked.set(
        row.resource,
        row.permissionIds.length > 0 && selectedCount === row.permissionIds.length
      );
    }

    for (const column of permissionMatrix.columns) {
      columnChecked.set(
        column.action,
        column.permissionIds.length > 0 &&
          column.permissionIds.every((permissionId) => selectedIds.has(permissionId))
      );
    }

    return { columnChecked, rowChecked, rowSelectedCounts };
  }, [permissionMatrix.columns, permissionMatrix.rows, selectedPermissionIds]);
  const isFormDirty = useMemo(
    () =>
      !isReadOnly &&
      (createDialogOpen || isEditing) &&
      hasRoleFormChanges(formData, currentBaseline),
    [isReadOnly, createDialogOpen, currentBaseline, formData, isEditing]
  );

  const updateFormData = (
    updater: UpsertRolePayload | ((current: UpsertRolePayload) => UpsertRolePayload)
  ) => {
    setFormOverride((current) => {
      const value = current ?? currentBaseline;
      return typeof updater === "function" ? updater(value) : updater;
    });
  };

  const togglePermission = (permissionId: number, checked: boolean) => {
    updateFormData((current) => ({
      ...current,
      permission_ids: checked
        ? [...current.permission_ids, permissionId]
        : current.permission_ids.filter((id) => id !== permissionId)
    }));
  };

  const setPermissions = (permissionIds: number[]) => {
    updateFormData((current) => ({
      ...current,
      permission_ids: Array.from(new Set(permissionIds))
    }));
  };

  const togglePermissionGroup = (permissionIds: number[], checked: boolean) => {
    updateFormData((current) => {
      const next = new Set(current.permission_ids);
      for (const permissionId of permissionIds) {
        if (checked) {
          next.add(permissionId);
        } else {
          next.delete(permissionId);
        }
      }
      return {
        ...current,
        permission_ids: Array.from(next)
      };
    });
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (isEditing) {
      updateRoleMutation.mutate({ id: editingRoleId, payload: formData });
      return;
    }
    // Include workspace_id when creating in workspace scope
    const payload: UpsertRolePayload = {
      ...formData,
      workspace_id: effectiveScope === "global" ? null : effectiveScope
    };
    createRoleMutation.mutate(payload);
  };

  const scopeLabel =
    effectiveScope === "global"
      ? "Global"
      : (workspaces.find((w) => w.id === effectiveScope)?.name ?? "Workspace");

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Roles"
        description="Create custom roles, inspect protected system roles, and manage permission bundles."
        meta={<Badge variant="secondary">RBAC</Badge>}
        actions={
          canCreateRole ? (
            <Button
              onClick={() => {
                createRoleMutation.reset();
                updateRoleMutation.reset();
                setFormOverride(emptyRoleForm);
                setIsReadOnly(false);
                setCreateDialogOpen(true);
              }}
            >
              <Plus className="mr-2 h-4 w-4" />
              Create Role
            </Button>
          ) : undefined
        }
      />

      {/* Workspace scope selector */}
      <div className="flex items-center gap-3">
        <Label className="text-sm text-muted-foreground">Scope:</Label>
        <Select
          value={String(effectiveScope)}
          onValueChange={(value) => setSelectedScope(value === "global" ? "global" : Number(value))}
        >
          <SelectTrigger className="w-[220px]">
            <SelectValue placeholder="Select scope" />
          </SelectTrigger>
          <SelectContent>
            {canReadGlobalRoles && (
              <SelectItem value="global">
                <div className="flex items-center gap-2">
                  <Globe className="h-3.5 w-3.5" />
                  Global
                </div>
              </SelectItem>
            )}
            {adminWorkspaces.map((ws) => (
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

      <AdminDataTable
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[10, 20, 50, 100]}
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "access-admin",
          "roles",
          effectiveScope,
          page,
          search,
          pageSize,
          sortField,
          sortDir
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) => {
          const workspaceId = effectiveScope === "global" ? undefined : effectiveScope;
          return rbacService.listRoles({
            page,
            per_page: pageSize,
            sort: sortField ?? undefined,
            order: sortDir,
            search: search || undefined,
            workspace_id: workspaceId,
          });
        }}
        columns={columns}
        searchPlaceholder="Search roles..."
        emptyMessage="No roles found."
        onRowDoubleClick={(row) => {
          updateRoleMutation.reset();
          setFormOverride(null);
          setEditingRoleId(row.original.id);
          setIsReadOnly(row.original.is_system || !canUpdateRole);
        }}
      />

      <EntityFormDialog
        open={createDialogOpen || isEditing}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialogOpen(false);
            setEditingRoleId(null);
            setFormOverride(emptyRoleForm);
            setIsReadOnly(false);
          }
        }}
        title={
          isReadOnly
            ? `View Role: ${roleDetail?.name ?? ""}`
            : isEditing
              ? "Edit Role"
              : `Create Role (${scopeLabel})`
        }
        description={
          isReadOnly
            ? "Inspect role metadata and its permission matrix."
            : isEditing
              ? "Update role metadata and its permission bundle."
              : `Create a new custom role in the ${scopeLabel} scope and attach explicit permissions.`
        }
        onSubmit={handleSubmit}
        isSubmitting={isSubmitting}
        submittingLabel={isEditing ? "Updating role..." : "Creating role..."}
        errorMessage={
          (isEditing ? updateRoleMutation.error : createRoleMutation.error) instanceof Error
            ? (isEditing ? updateRoleMutation.error : createRoleMutation.error)?.message
            : undefined
        }
        isDirty={isFormDirty}
        isReadOnly={isReadOnly}
        contentClassName="!max-w-[min(96vw,1440px)] sm:!max-h-[94dvh]"
      >
        <div className="space-y-5">
          {roleDetail?.is_system ? (
            <div className="flex items-start gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {isReadOnly
                  ? "System roles are system-defined and cannot be modified."
                  : "System roles are protected. Some edits may be rejected by the API."}
              </span>
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="role-name">Name</Label>
            <Input
              id="role-name"
              value={formData.name}
              onChange={(event) =>
                updateFormData((current) => ({ ...current, name: event.target.value }))
              }
              placeholder="support_admin"
              required
              disabled={isReadOnly}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="role-description">Description</Label>
            <Input
              id="role-description"
              value={formData.description || ""}
              onChange={(event) =>
                updateFormData((current) => ({ ...current, description: event.target.value }))
              }
              placeholder="Describe what this role is allowed to do"
              disabled={isReadOnly}
            />
          </div>

          <div className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Label>Permission Matrix</Label>
                <Badge variant="outline">
                  {formData.permission_ids.length}/{permissionMatrix.allPermissionIds.length}{" "}
                  selected
                </Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setPermissions(permissionMatrix.allPermissionIds)}
                  disabled={isReadOnly || permissionMatrix.allPermissionIds.length === 0}
                >
                  <CheckSquare className="h-4 w-4" />
                  Grant all
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setPermissions([])}
                  disabled={isReadOnly || formData.permission_ids.length === 0}
                >
                  <XSquare className="h-4 w-4" />
                  Revoke all
                </Button>
              </div>
            </div>

            <div className="max-h-[62dvh] overflow-auto rounded-md border border-border/60">
              <Table wrapperClassName="min-w-[900px] overflow-visible">
                <TableHeader className="sticky top-0 z-10 bg-background">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="sticky left-0 z-20 w-[240px] bg-background">
                      Resource
                    </TableHead>
                    {permissionMatrix.columns.map((column) => {
                      return (
                        <TableHead
                          key={column.action}
                          className="min-w-[96px] bg-background text-center"
                        >
                          <div className="flex flex-col items-center gap-1.5">
                            <MatrixCheckbox
                              checked={
                                permissionSelectionStats.columnChecked.get(column.action) ?? false
                              }
                              label={`Toggle all ${column.action} permissions`}
                              disabled={isReadOnly || column.permissionIds.length === 0}
                              onChange={(checked) =>
                                togglePermissionGroup(column.permissionIds, checked)
                              }
                            />
                            <span className="text-xs capitalize">
                              {formatPermissionLabel(column.action)}
                            </span>
                          </div>
                        </TableHead>
                      );
                    })}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {permissionMatrix.rows.map((row) => {
                    const rowChecked =
                      permissionSelectionStats.rowChecked.get(row.resource) ?? false;
                    const rowSelectedCount =
                      permissionSelectionStats.rowSelectedCounts.get(row.resource) ?? 0;

                    return (
                      <TableRow key={row.resource}>
                        <TableCell className="sticky left-0 z-[1] bg-background">
                          <div className="flex items-center gap-3">
                            <MatrixCheckbox
                              checked={rowChecked}
                              label={`Toggle all ${row.resource} permissions`}
                              disabled={isReadOnly}
                              onChange={(checked) =>
                                togglePermissionGroup(row.permissionIds, checked)
                              }
                            />
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium">
                                {formatPermissionLabel(row.resource)}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {rowSelectedCount}/{row.permissionIds.length}
                              </p>
                            </div>
                          </div>
                        </TableCell>
                        {permissionMatrix.columns.map((column) => {
                          const permission = row.byAction.get(column.action);
                          if (!permission) {
                            return (
                              <TableCell
                                key={column.action}
                                className="text-center text-muted-foreground/40"
                              >
                                -
                              </TableCell>
                            );
                          }

                          return (
                            <TableCell key={column.action} className="text-center">
                              <div className="flex justify-center">
                                <MatrixCheckbox
                                  checked={selectedPermissionIds.has(permission.id)}
                                  label={`Toggle ${permission.name}`}
                                  disabled={isReadOnly}
                                  onChange={(checked) => togglePermission(permission.id, checked)}
                                />
                              </div>
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </div>
        </div>
      </EntityFormDialog>

      {deletingRole ? (
        <DeleteConfirmDialog
          open={!!deletingRole}
          onOpenChange={(open) => !open && setDeletingRole(null)}
          onConfirm={() => deleteRoleMutation.mutate(deletingRole.id)}
          isDeleting={deleteRoleMutation.isPending}
          title={`Delete role ${deletingRole.name}?`}
          description="This removes the role definition. Users currently assigned to it will lose the access granted by this role."
        />
      ) : null}
    </div>
  );
}
