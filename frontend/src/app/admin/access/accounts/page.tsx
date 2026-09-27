"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { BadgeCheck, CheckCircle, ShieldAlert, Trash2, UserRound, XCircle } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DataTable, columnMeta, createKebabColumn } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { AccountInspector } from "@/components/admin/access/AccountInspector";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { Badge } from "@/components/ui/badge";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { AuthAdminUser } from "@/types/rbac.types";
import { accessQueryKeys } from "@/lib/access/query-keys";

const PAGE_SIZE = 15;

/**
 * Auth accounts (T2, F15) — who can sign in, and with what.
 *
 * Named "Accounts" rather than "Users" on purpose: two sidebar entries called
 * "Users" (auth logins here, player identities in People) were the collision
 * the new IA removes. This screen owns the login; People owns the person, and
 * the inspector links across.
 */
export default function AccessAdminAccountsPage() {
  const queryClient = useQueryClient();
  const { hasPermission, isSuperuser, canAccessPermission } = usePermissions();
  const currentUserId = useAuthProfileStore((state) => state.user?.id);
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row is on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const canReadRoles = hasPermission("role.read");
  const canAssignRoles = hasPermission("role.update") && canReadRoles;
  const canManageLinkedPlayers = hasPermission("auth_user.update");
  // Same gate as the People route: a workspace-scoped `user.read` opens it.
  const canReadPeople = canAccessPermission("user.read");

  const [pageRows, setPageRows] = useState<AuthAdminUser[]>([]);
  const [pendingDelete, setPendingDelete] = useState<AuthAdminUser | null>(null);

  const rolesQuery = useQuery({
    queryKey: accessQueryKeys.rolesAll(),
    queryFn: () => rbacService.listRolesAll(),
    enabled: canReadRoles
  });
  const roles = rolesQuery.data ?? [];

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "role",
        label: "Role",
        kind: "single",
        options: roles.map((role) => ({ value: String(role.id), label: role.name }))
      },
      {
        key: "status",
        label: "Status",
        kind: "single",
        options: [
          { value: "active", label: "Active" },
          { value: "inactive", label: "Inactive" }
        ]
      },
      { key: "superuser", label: "Superusers only", kind: "toggle" }
    ],
    [roles]
  );

  const filters = useFilters(defs);
  const roleFilter = String(filters.values.role ?? "");
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
      notify.success("Account deleted");
    },
    onError: (error) => notify.apiError(error)
  });

  const columns = useMemo<ColumnDef<AuthAdminUser>[]>(
    () => [
      {
        accessorKey: "id",
        header: "ID",
        size: 60,
        cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>
      },
      {
        accessorKey: "email",
        header: "Account",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-foreground">{row.original.email}</p>
            <p className="truncate font-mono text-xs text-muted-foreground">
              @{row.original.username}
            </p>
          </div>
        )
      },
      {
        id: "linkedPlayer",
        header: "Player identity",
        enableSorting: false,
        cell: ({ row }) => {
          const linked = getSingleLinkedPlayer(row.original.linked_players);
          if (!linked) {
            return <span className="text-sm text-muted-foreground">Not linked</span>;
          }
          return <span className="truncate text-sm">{linked.player_name}</span>;
        }
      },
      {
        id: "status",
        header: "Status",
        enableSorting: false,
        meta: columnMeta<AuthAdminUser>({ align: "center" }),
        cell: ({ row }) => (
          <div className="flex flex-wrap justify-center gap-2">
            {row.original.is_active ? (
              <StatusIcon icon={CheckCircle} label="Active" variant="success" />
            ) : (
              <StatusIcon icon={XCircle} label="Inactive" variant="muted" />
            )}
            {row.original.is_verified ? (
              <StatusIcon icon={BadgeCheck} label="Verified" variant="info" />
            ) : null}
            {row.original.is_superuser ? (
              <StatusIcon icon={ShieldAlert} label="Superuser" variant="destructive" />
            ) : null}
          </div>
        )
      },
      {
        id: "roles",
        header: "Roles",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.roles.length === 0 ? (
            <span className="text-sm text-muted-foreground">No roles</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {row.original.roles.map((role) => (
                <Badge key={role.id} variant="secondary">
                  {role.name}
                </Badge>
              ))}
            </div>
          )
      },
      createKebabColumn<AuthAdminUser>(
        (row) => {
          const linked = getSingleLinkedPlayer(row.linked_players);
          return [
            {
              label: "Open in People",
              icon: UserRound,
              hidden: !canReadPeople || linked === null,
              href: linked ? `/admin/people/${linked.player_id}` : undefined
            },
            {
              label: "Delete account",
              icon: Trash2,
              destructive: true,
              hidden: !isSuperuser || row.id === currentUserId,
              onSelect: () => setPendingDelete(row)
            }
          ];
        },
        { rowLabel: (row) => row.email }
      )
    ],
    [canReadPeople, currentUserId, isSuperuser]
  );

  return (
    <div className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <DataTable<AuthAdminUser>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          cellAlign="top"
          searchPlaceholder="Search accounts…"
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          emptyMessage="No auth accounts match. Clear the filters to see every account."
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{row.original.email}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">
                @{row.original.username}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {row.original.is_active ? "Active" : "Inactive"} ·{" "}
                {row.original.roles.length === 0
                  ? "no roles"
                  : row.original.roles.map((role) => role.name).join(", ")}
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
            { role: roleFilter, status: statusFilter, superuser: superuserFilter }
          ]}
          queryFn={async (page, search, pageSize, sortField, sortDir) => {
            const result = await rbacService.listUsers({
              page,
              per_page: pageSize,
              sort: sortField ?? undefined,
              order: sortDir,
              search: search || undefined,
              role_id: roleFilter ? Number(roleFilter) : undefined,
              is_active: statusFilter ? statusFilter === "active" : undefined,
              is_superuser: superuserFilter ? true : undefined
            });
            // The inspector steps through the rows currently on screen, and the
            // table owns the fetch, so this is where that page is observed.
            setPageRows(result.results);
            return result;
          }}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? openRow.email : ""}
        subtitle={openRow ? `@${openRow.username}` : undefined}
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
            canManageLinkedPlayers={canManageLinkedPlayers}
            canReadPeople={canReadPeople}
            roles={roles}
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
          title: "Delete auth account",
          description: `This permanently deletes the login for ${pendingDelete?.email ?? "this account"} and signs it out of every device immediately. The linked player profile and its tournament history are preserved — only unlinked. This cannot be undone.`,
          confirmLabel: "Delete account",
          tone: "danger",
          cascade: [
            "Assigned roles and permission restrictions",
            "OAuth connections",
            "API keys owned by this account",
            "Active sessions"
          ]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
