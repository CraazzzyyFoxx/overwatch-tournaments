"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { DataTable, type TableCommand } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { notify } from "@/lib/notify";
import { usePermissions } from "@/hooks/usePermissions";
import { rbacService } from "@/services/rbac.service";
import workspaceService from "@/services/workspace.service";
import type { WorkspaceMember, WorkspaceSystemRole } from "@/types/workspace.types";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";
import { useTranslations } from "next-intl";

import { AddMemberDialog } from "./AddMemberDialog";
import { memberFilterDefs } from "./filters";
import { memberLabel, sortRoles, useRoleLabel } from "./model";
import { useMemberColumns } from "./useMemberColumns";

/**
 * The members of one workspace: who they are, the role each holds, and the
 * add / fill-missing / remove actions the caller's `workspace_member.*` grants allow.
 */
export function MembersBrowser({
  workspaceId,
  workspaceName
}: Readonly<{ workspaceId: number; workspaceName: string }>) {
  const t = useTranslations("adminAccess.common");
  const tw = useTranslations("adminAccess.workspace");
  const tm = useTranslations("adminAccess.member");
  const { isSuperuser, canAccessAnyPermission } = usePermissions();
  const queryClient = useQueryClient();

  const [addOpen, setAddOpen] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<WorkspaceMember | null>(null);

  const canCreateMembers =
    isSuperuser || canAccessAnyPermission(["workspace_member.create"], workspaceId);
  const canUpdateMembers =
    isSuperuser || canAccessAnyPermission(["workspace_member.update"], workspaceId);
  const canDeleteMembers =
    isSuperuser || canAccessAnyPermission(["workspace_member.delete"], workspaceId);

  const { data: scopedRoles } = useQuery({
    queryKey: workspaceQueryKeys.rbacRoles(workspaceId),
    queryFn: () => rbacService.listRolesAll({ workspace_id: workspaceId }),
    enabled: canCreateMembers || canUpdateMembers
  });

  const systemRoleId = useCallback(
    (name: WorkspaceSystemRole): number | undefined =>
      scopedRoles?.find((role) => role.name === name)?.id,
    [scopedRoles]
  );
  const roles = useMemo(() => sortRoles(scopedRoles ?? []), [scopedRoles]);
  const roleLabel = useRoleLabel();

  const filterDefs = useMemo(
    () => memberFilterDefs(roles, { role: t("role"), excludeRole: tm("excludeRole") }, roleLabel),
    [roles, roleLabel, t, tm]
  );
  const filters = useFilters(filterDefs);
  const roleFilter = String(filters.values.role ?? "");
  const excludeRoleIds = Array.isArray(filters.values.exclude_role)
    ? filters.values.exclude_role.map(Number).filter((id) => Number.isInteger(id))
    : [];

  const invalidateMembers = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: workspaceQueryKeys.memberList(workspaceId) });
  }, [queryClient, workspaceId]);

  const removeMemberMutation = useMutation({
    mutationFn: (authUserId: number) => workspaceService.removeMember(workspaceId, authUserId),
    onSuccess: () => {
      invalidateMembers();
      setPendingRemoval(null);
      notify.success(tw("memberRemoved"));
    },
    onError: (error) => notify.apiError(error)
  });

  const autofillMutation = useMutation({
    mutationFn: () => workspaceService.autofillMemberRoles(workspaceId),
    onSuccess: ({ assigned }) => {
      invalidateMembers();
      notify.success(
        assigned > 0
          ? tm("assignedPlayer", { count: assigned })
          : tm("everyoneHasRole")
      );
    },
    onError: (error) => notify.apiError(error)
  });

  const columns = useMemberColumns({
    workspaceId,
    roles,
    canUpdateMembers,
    canDeleteMembers,
    requestRemoval: setPendingRemoval
  });

  const commands: TableCommand[] = [
    {
      id: "fill-missing",
      label: tw("fillMissing"),
      hidden: !canUpdateMembers,
      disabled: autofillMutation.isPending,
      onSelect: () => autofillMutation.mutate()
    },
    {
      id: "add-member",
      label: t("addMember"),
      icon: Plus,
      primary: true,
      hidden: !canCreateMembers,
      onSelect: () => setAddOpen(true)
    }
  ];

  return (
    <>
      <DataTable<WorkspaceMember>
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "workspace-members",
          workspaceId,
          { page, search, pageSize, sortField, sortDir, roleId: roleFilter || null, excludeRoleIds }
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          workspaceService.getMembers(workspaceId, {
            page,
            per_page: pageSize,
            search,
            role_id: roleFilter ? Number(roleFilter) : null,
            exclude_role_id: excludeRoleIds,
            sort: sortField === "role" ? "role" : "username",
            order: sortDir
          })
        }
        columns={columns}
        initialPageSize={25}
        searchPlaceholder={t("searchByNameEmail")}
        filterKey={filters.filterKey}
        getRowId={(row) => String(row.auth_user_id)}
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        emptyMessage={tw("noMembers")}
        commands={commands}
      />

      {canCreateMembers ? (
        <AddMemberDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          workspaceId={workspaceId}
          systemRoleId={systemRoleId}
          onAdded={() => {
            invalidateMembers();
            setAddOpen(false);
          }}
        />
      ) : null}

      <ConfirmDialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => (open ? null : setPendingRemoval(null))}
        intent={{
          title: t("removeMember"),
          description: pendingRemoval
            ? tm("removeDescription", { member: memberLabel(pendingRemoval), workspace: workspaceName })
            : "",
          confirmLabel: t("removeMember"),
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingRemoval) removeMemberMutation.mutate(pendingRemoval.auth_user_id);
        }}
        pending={removeMemberMutation.isPending}
      />
    </>
  );
}
