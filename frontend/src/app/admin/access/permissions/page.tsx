"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";

import { AdminDataTable, adminColumnMeta } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import type { RbacPermission } from "@/types/rbac.types";

const PAGE_SIZE = 20;

/**
 * The permission inventory (T2, F15) — read-only, and the vocabulary every
 * role and API key is built from.
 *
 * Fetched whole (roughly ninety rows) and paged client-side, because the
 * endpoint filters only by free text: deriving the resource and action chips
 * needs the full set anyway, and once it is in memory a second round-trip per
 * chip buys nothing.
 */
export default function AccessAdminPermissionsPage() {
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const permissionsQuery = useQuery({
    queryKey: ["access-admin", "permissions", "inventory"],
    queryFn: () => rbacService.listPermissionsAll()
  });
  const permissions = permissionsQuery.data ?? [];

  const defs = useMemo<FilterDef[]>(() => {
    const resources = [...new Set(permissions.map((permission) => permission.resource))].sort();
    const actions = [...new Set(permissions.map((permission) => permission.action))].sort();
    return [
      {
        key: "resource",
        label: "Resource",
        kind: "single",
        options: resources.map((resource) => ({ value: resource, label: resource }))
      },
      {
        key: "action",
        label: "Action",
        kind: "single",
        options: actions.map((action) => ({ value: action, label: action }))
      }
    ];
  }, [permissions]);

  const filters = useFilters(defs);
  const resourceFilter = String(filters.values.resource ?? "");
  const actionFilter = String(filters.values.action ?? "");

  const rows = permissions.filter(
    (permission) =>
      (!resourceFilter || permission.resource === resourceFilter) &&
      (!actionFilter || permission.action === actionFilter)
  );

  const openRow = rows.find((permission) => String(permission.id) === openId) ?? null;
  const openIndex = openRow ? rows.indexOf(openRow) : -1;

  const columns = useMemo<ColumnDef<RbacPermission>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Permission",
        meta: adminColumnMeta<RbacPermission>({
          searchValue: (permission) => `${permission.name} ${permission.description ?? ""}`
        }),
        cell: ({ row }) => <span className="font-mono text-sm">{row.original.name}</span>
      },
      {
        accessorKey: "resource",
        header: "Resource",
        cell: ({ row }) => <Badge variant="outline">{row.original.resource}</Badge>
      },
      {
        accessorKey: "action",
        header: "Action",
        cell: ({ row }) => <Badge variant="secondary">{row.original.action}</Badge>
      },
      {
        accessorKey: "description",
        header: "Description",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.description || (
            <span className="text-muted-foreground">No description</span>
          )
      }
    ],
    []
  );

  if (permissionsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load the permission inventory"
        onAction={() => void permissionsQuery.refetch()}
        actionLabel="Try again"
      />
    );
  }

  return (
    <div className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <AdminDataTable<RbacPermission>
          rows={rows}
          isLoading={permissionsQuery.isLoading}
          columns={columns}
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          searchPlaceholder="Search permissions…"
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          emptyMessage="No permission matches. Clear the filters to see the full inventory."
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? openRow.name : ""}
        subtitle={openRow ? `${openRow.resource} · ${openRow.action}` : undefined}
        onPrev={openIndex > 0 ? () => setParams({ id: String(rows[openIndex - 1].id) }) : undefined}
        onNext={
          openIndex >= 0 && openIndex < rows.length - 1
            ? () => setParams({ id: String(rows[openIndex + 1].id) })
            : undefined
        }
      >
        {openRow ? (
          <div className="space-y-3">
            <div>
              <p className={EYEBROW_CLASS}>Description</p>
              <p className="mt-0.5 text-sm">
                {openRow.description || "This permission carries no description."}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className={EYEBROW_CLASS}>Resource</p>
                <p className="mt-0.5 font-mono text-sm">{openRow.resource}</p>
              </div>
              <div>
                <p className={EYEBROW_CLASS}>Action</p>
                <p className="mt-0.5 font-mono text-sm">{openRow.action}</p>
              </div>
              <div>
                <p className={EYEBROW_CLASS}>Id</p>
                <p className="mt-0.5 font-mono text-sm tabular-nums">#{openRow.id}</p>
              </div>
              <div>
                <p className={EYEBROW_CLASS}>Added</p>
                <p className="mt-0.5 text-sm tabular-nums">{openRow.created_at.slice(0, 10)}</p>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              The inventory is defined by the platform. Grant a permission by adding it to a role
              on the Roles tab.
            </p>
          </div>
        ) : null}
      </Inspector>
    </div>
  );
}
