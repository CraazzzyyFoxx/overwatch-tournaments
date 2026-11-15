"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQueries, useQuery } from "@tanstack/react-query";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { Check } from "lucide-react";

import {
  GLOBAL_WILDCARD,
  humanize,
  sortActions,
  wildcardCovers
} from "@/components/admin/access/PermissionPicker";
import { RoleScopeSelect, useRoleScope } from "@/components/admin/access/RoleScopeSelect";
import { DataTable, columnMeta, type DataTableGroup } from "@craazzzyyfoxx/admin-kit/data-table";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useQueryParams } from "@/hooks/useQueryParams";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { rbacService } from "@/services/rbac.service";
import type { RbacPermission } from "@/types/rbac.types";

/**
 * The access map (F15): one row per permission, grouped by resource, and one
 * column per role of the scope marking whether that role grants it. Read-only
 * on purpose; a role's name links to its editor, the one place a grant changes.
 *
 * Wildcards are not rows: a role holding `admin.*` says so in its header's
 * tooltip, and any wildcard a role holds marks every permission it covers.
 *
 * Every query key is shared with Roles, so a role saved there is current here.
 */
export function PermissionsBrowser() {
  const t = useTranslations("adminAccess.common");
  const tp = useTranslations("adminAccess.permissionsUi");
  const ti = useTranslations("adminAccess.pickerUi");
  const tw = useTranslations("adminAccess.permissions");
  const { setParams } = useQueryParams();
  const { options, scope, workspaceId } = useRoleScope();

  const rolesQuery = useQuery({
    queryKey: accessQueryKeys.rolesByScope(scope),
    queryFn: () => rbacService.listRolesAll({ workspace_id: workspaceId }),
    enabled: options.length > 0
  });
  const permissionsQuery = useQuery({
    queryKey: accessQueryKeys.permissionsByScope(scope),
    queryFn: () =>
      rbacService.listPermissionsAll(
        workspaceId === null ? undefined : { workspace_id: workspaceId }
      )
  });
  const roles = rolesQuery.data ?? [];
  // A scope holds a handful of roles, so one detail request each is cheap, and
  // they share `RoleEditor`'s keys.
  const detailQueries = useQueries({
    queries: roles.map((role) => ({
      queryKey: accessQueryKeys.role(role.id),
      queryFn: () => rbacService.getRole(role.id)
    }))
  });

  if (options.length === 0) {
    return <PageStateCard state="empty" title={tp("noRoleAccess")} />;
  }

  const failed = [rolesQuery, permissionsQuery, ...detailQueries].filter((entry) => entry.isError);
  if (failed.length > 0) {
    return (
      <PageStateCard
        state="error"
        title={tp("loadError")}
        onAction={() => failed.forEach((entry) => void entry.refetch())}
        actionLabel={t("tryAgain")}
      />
    );
  }

  const catalog = (permissionsQuery.data ?? [])
    .filter((permission) => permission.action !== "*")
    .sort(
      (left, right) =>
        left.resource.localeCompare(right.resource) || sortActions(left.action, right.action)
    );

  const grants = roles.map((role, index) => {
    const held = detailQueries[index]?.data?.permissions ?? [];
    const wildcards = held
      .filter((permission) => permission.action === "*")
      .map((permission) => permission.name);
    const granted = new Set(held.map((permission) => permission.name));
    for (const permission of catalog) {
      if (
        wildcards.some((wildcard) =>
          wildcardCovers(wildcard, {
            key: permission.name,
            resource: permission.resource,
            action: permission.action
          })
        )
      ) {
        granted.add(permission.name);
      }
    }
    return { role, granted, fullAccess: wildcards.includes(GLOBAL_WILDCARD) };
  });

  const roleColumns: ColumnDef<RbacPermission>[] = grants.map(({ role, granted, fullAccess }) => ({
    id: `role-${role.id}`,
    accessorFn: (permission) => granted.has(permission.name),
    header: () => (
      <Link
        href={`/admin/access/roles?scope=${scope}&role=${role.id}`}
        className="hover:text-foreground hover:underline"
      >
        {role.name}
      </Link>
    ),
    enableSorting: false,
    meta: columnMeta<RbacPermission>({
      align: "center",
      className: "w-28",
      headerTooltip: fullAccess ? `${ti("fullAccess")}: ${tw("everything")}` : undefined
    }),
    cell: ({ row }) =>
      granted.has(row.original.name) ? (
        <>
          <Check aria-hidden className="mx-auto size-4 text-primary" />
          <span className="sr-only">{tp("granted")}</span>
        </>
      ) : (
        <>
          <span aria-hidden className="text-muted-foreground">
            -
          </span>
          <span className="sr-only">{tp("notGranted")}</span>
        </>
      )
  }));

  const columns: ColumnDef<RbacPermission>[] = [
    {
      accessorKey: "name",
      header: t("permission"),
      enableSorting: false,
      meta: columnMeta<RbacPermission>({
        className: "min-w-56",
        ellipsis: false,
        searchValue: (permission) => `${permission.name} ${permission.description ?? ""}`
      }),
      cell: ({ row }) => (
        <>
          <span className="font-mono text-sm">{row.original.action}</span>
          {/* Many seeded rows repeat their own name as the description. */}
          {row.original.description && row.original.description !== row.original.name ? (
            <span className="block text-xs text-muted-foreground">{row.original.description}</span>
          ) : null}
        </>
      )
    },
    ...roleColumns
  ];

  const groupRows = (pageRows: Row<RbacPermission>[]): DataTableGroup<RbacPermission>[] => {
    const groups = new Map<string, Row<RbacPermission>[]>();
    for (const row of pageRows) {
      const bucket = groups.get(row.original.resource);
      if (bucket) bucket.push(row);
      else groups.set(row.original.resource, [row]);
    }
    return [...groups].map(([resource, rows]) => ({
      key: resource,
      label: humanize(resource),
      rows
    }));
  };

  return (
    <DataTable<RbacPermission>
      rows={catalog}
      isLoading={
        rolesQuery.isLoading ||
        permissionsQuery.isLoading ||
        detailQueries.some((entry) => entry.isLoading)
      }
      columns={columns}
      getRowId={(row) => String(row.id)}
      paging="all"
      groupRows={groupRows}
      filterKey={String(scope)}
      searchPlaceholder={t("searchPermissions")}
      emptyMessage={tp("noMatches")}
      // A phone has no room for a column per role: name the roles instead.
      renderMobileCard={(row) => {
        const holders = grants
          .filter(({ granted }) => granted.has(row.original.name))
          .map(({ role }) => role.name);
        return (
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-sm">{row.original.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {holders.length > 0 ? holders.join(", ") : tp("noHolders")}
            </p>
          </div>
        );
      }}
      toolbar={
        <RoleScopeSelect
          options={options}
          value={String(scope)}
          onValueChange={(value) => setParams({ scope: value })}
          className="w-56"
        />
      }
    />
  );
}
