"use client";

import { ColumnDef } from "@tanstack/react-table";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { Badge } from "@/components/ui/badge";
import { paginateResults, sortArray } from "@/lib/paginate-results";
import { rbacService } from "@/services/rbac.service";
import type { RbacPermission } from "@/types/rbac.types";

const PAGE_SIZE = 20;

export default function AccessAdminPermissionsPage() {
  const columns: ColumnDef<RbacPermission>[] = [
    {
      accessorKey: "name",
      header: "Permission",
    },
    {
      accessorKey: "resource",
      header: "Resource",
      cell: ({ row }) => <Badge variant="outline">{row.original.resource}</Badge>,
    },
    {
      accessorKey: "action",
      header: "Action",
      cell: ({ row }) => <Badge variant="secondary">{row.original.action}</Badge>,
    },
    {
      accessorKey: "description",
      header: "Description",
      cell: ({ row }) => row.original.description || <span className="text-muted-foreground">No description</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Permissions"
        description="Read-only inventory of effective permission primitives available to superusers and roles."
        meta={<Badge variant="secondary">RBAC</Badge>}
      />

      <AdminDataTable
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[10, 20, 50, 100]}
        queryKey={(page, search, pageSize, sortField, sortDir) => ["access-admin", "permissions", page, search, pageSize, sortField, sortDir]}
        queryFn={async (page, search, pageSize, sortField, sortDir) => {
          const permissions = await rbacService.listPermissions();
          const filteredPermissions = search
            ? permissions.filter((permission) => {
                const haystack = `${permission.name} ${permission.resource} ${permission.action} ${permission.description || ""}`.toLowerCase();
                return haystack.includes(search.toLowerCase());
              })
            : permissions;
          return paginateResults(sortArray(filteredPermissions, sortField, sortDir), page, pageSize);
        }}
        columns={columns}
        searchPlaceholder="Search permissions..."
        emptyMessage="No permissions found."
      />
    </div>
  );
}
