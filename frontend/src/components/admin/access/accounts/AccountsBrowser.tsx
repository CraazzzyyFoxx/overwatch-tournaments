"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DataTable } from "@/components/data-table";
import { AccountInspector } from "@/components/admin/access/AccountInspector";
import { accountTitle } from "@/components/admin/access/AccountCard";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import type { AuthAdminUser } from "@/types/rbac.types";
import { accessQueryKeys } from "@/lib/access/query-keys";

import { useAccountFilterDefs } from "./filters";
import { accountSubtitle } from "./model";
import { useAccountColumns } from "./useAccountColumns";

const PAGE_SIZE = 15;

/**
 * Auth accounts (T2, F15) — who can sign in, and with what.
 *
 * Named "Accounts" rather than "Users" on purpose: two sidebar entries called
 * "Users" (auth logins here, player identities in People) were the collision
 * the new IA removes. This screen owns the login; People owns the person, and
 * the inspector links across.
 */
export function AccountsBrowser() {
  const t = useTranslations("adminAccess.common");
  const ta = useTranslations("adminAccess.accounts");
  const queryClient = useQueryClient();
  const router = useRouter();
  const { hasPermission, isSuperuser, canAccessPermission } = usePermissions();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row is on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;

  const canReadRoles = hasPermission("role.read");
  const canAssignRoles = hasPermission("role.update") && canReadRoles;
  const canUpdateAccount = hasPermission("auth_user.update");
  // Same gate as the People route: a workspace-scoped `user.read` opens it.
  const canReadPeople = canAccessPermission("user.read");

  const [pageRows, setPageRows] = useState<AuthAdminUser[]>([]);
  const [pendingDelete, setPendingDelete] = useState<AuthAdminUser | null>(null);

  const rolesQuery = useQuery({
    queryKey: accessQueryKeys.rolesAll(),
    queryFn: () => rbacService.listRolesAll(),
    enabled: canReadRoles
  });
  const roles = useMemo(() => rolesQuery.data ?? [], [rolesQuery.data]);

  const defs = useAccountFilterDefs(roles);
  const filters = useFilters(defs);
  const roleFilter = String(filters.values.role ?? "");
  const excludeRoleIds = Array.isArray(filters.values.exclude_role)
    ? filters.values.exclude_role.map(Number).filter((id) => Number.isInteger(id))
    : [];
  const statusFilter = String(filters.values.status ?? "");
  const superuserFilter = filters.values.superuser === true;

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const deleteMutation = useMutation({
    mutationFn: (userId: number) => rbacService.deleteUser(userId),
    onSuccess: async () => {
      const removed = pendingDelete;
      await queryClient.invalidateQueries({ queryKey: accessQueryKeys.users() });
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success(ta("accountDeleted"));
    },
    onError: (error) => notify.apiError(error)
  });

  const columns = useAccountColumns({ canReadPeople, isSuperuser, onDelete: setPendingDelete });

  return (
    <div className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <DataTable<AuthAdminUser>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          cellAlign="top"
          searchPlaceholder={t("searchAccounts")}
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          emptyMessage={ta("noAuthMatches")}
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          onRowDoubleClick={
            canReadPeople
              ? (row) => {
                  const linked = getSingleLinkedPlayer(row.original.linked_players);
                  if (linked) router.push(`/admin/people/${linked.player_id}`);
                }
              : undefined
          }
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{row.original.email}</p>
              <p className="truncate text-caption text-muted-foreground">@{row.original.username}</p>
              <p className="truncate text-caption text-muted-foreground">
                {[
                  row.original.is_active ? null : t("inactive"),
                  row.original.roles.map((role) => role.name).join(", ")
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
          )}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "access-admin",
            "users",
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            { role: roleFilter, excludeRole: excludeRoleIds, status: statusFilter, superuser: superuserFilter }
          ]}
          queryFn={(page, search, pageSize, sortField, sortDir) =>
            rbacService.listUsers({
              page,
              per_page: pageSize,
              sort: sortField ?? undefined,
              order: sortDir,
              search: search || undefined,
              role_id: roleFilter ? Number(roleFilter) : undefined,
              exclude_role_id: excludeRoleIds.length ? excludeRoleIds : undefined,
              is_active: statusFilter ? statusFilter === "active" : undefined,
              is_superuser: superuserFilter ? true : undefined
            })
          }
          onPageRowsChange={setPageRows}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? accountTitle(openRow) : ""}
        subtitle={openRow ? accountSubtitle(openRow) : undefined}
        onPrev={
          openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
        }
        onNext={
          openIndex >= 0 && openIndex < pageRows.length - 1
            ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
            : undefined
        }
      >
        {openRow ? (
          <AccountInspector
            key={openRow.id}
            userId={openRow.id}
            canAssignRoles={canAssignRoles}
            canUpdateAccount={canUpdateAccount}
            canReadPeople={canReadPeople}
          />
        ) : null}
      </Inspector>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: ta("deleteTitle"),
          description: ta("deleteDescription", { account: pendingDelete?.email ?? t("account") }),
          confirmLabel: t("deleteAccount"),
          tone: "danger",
          cascade: [
            ta("deleteDetailsRoles"),
            ta("deleteDetailsOauth"),
            ta("deleteDetailsKeys"),
            ta("deleteDetailsSessions")
          ]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
