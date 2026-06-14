"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Globe, MonitorSmartphone, Shield } from "lucide-react";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { paginateResults, sortArray } from "@/lib/paginate-results";
import { rbacService } from "@/services/rbac.service";
import type { AdminAuthSession, AdminSessionStatus } from "@/types/rbac.types";

const PAGE_SIZE = 20;

const STATUS_META: Record<
  AdminSessionStatus,
  {
    dotClassName: string;
    label: string;
    textClassName: string;
  }
> = {
  active: {
    dotClassName: "bg-emerald-500",
    label: "Active",
    textClassName: "text-emerald-500",
  },
  revoked: {
    dotClassName: "bg-amber-500",
    label: "Revoked",
    textClassName: "text-amber-500",
  },
  expired: {
    dotClassName: "bg-slate-500",
    label: "Expired",
    textClassName: "text-slate-400",
  },
};

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Unavailable";

  return new Date(value).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function detectBrowser(userAgent: string): string | null {
  if (/Edg\//i.test(userAgent)) return "Edge";
  if (/OPR\//i.test(userAgent)) return "Opera";
  if (/Chrome\//i.test(userAgent)) return "Chrome";
  if (/Firefox\//i.test(userAgent)) return "Firefox";
  if (/Safari\//i.test(userAgent) && !/Chrome\//i.test(userAgent)) return "Safari";
  return null;
}

function detectPlatform(userAgent: string): string | null {
  if (/iPhone|iPad|iPod/i.test(userAgent)) return "iOS";
  if (/Android/i.test(userAgent)) return "Android";
  if (/Windows/i.test(userAgent)) return "Windows";
  if (/Macintosh|Mac OS X/i.test(userAgent)) return "macOS";
  if (/Linux/i.test(userAgent)) return "Linux";
  return null;
}

function formatDeviceLabel(userAgent: string | null | undefined): string {
  if (!userAgent) return "Unknown device";

  const browser = detectBrowser(userAgent);
  const platform = detectPlatform(userAgent);

  if (browser && platform) return `${browser} on ${platform}`;
  if (browser) return browser;
  if (platform) return platform;

  return userAgent.length > 64 ? `${userAgent.slice(0, 64)}...` : userAgent;
}

function StatusCell({ status }: { status: AdminSessionStatus }) {
  const meta = STATUS_META[status];

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta.textClassName}`}>
      <span className={`size-1.5 rounded-full ${meta.dotClassName}`} />
      {meta.label}
    </span>
  );
}

export default function AccessAdminSessionsPage() {
  const [statusFilter, setStatusFilter] = useState<"all" | AdminSessionStatus>("all");

  const columns: ColumnDef<AdminAuthSession>[] = [
    {
      id: "user",
      header: "User",
      accessorFn: (row) => row.email ?? row.username ?? `#${row.user_id}`,
      cell: ({ row }) => (
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{row.original.email ?? "Email unavailable"}</p>
          <p className="truncate text-xs text-muted-foreground">
            {row.original.username ? `@${row.original.username}` : `User #${row.original.user_id}`}
          </p>
        </div>
      ),
    },
    {
      id: "device",
      header: "Device",
      accessorFn: (row) => formatDeviceLabel(row.user_agent),
      cell: ({ row }) => (
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <MonitorSmartphone className="h-4 w-4 text-muted-foreground" />
            <span className="truncate text-sm font-medium">{formatDeviceLabel(row.original.user_agent)}</span>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {row.original.user_agent ?? "User agent unavailable"}
          </p>
        </div>
      ),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ row }) => <StatusCell status={row.original.status} />,
    },
    {
      accessorKey: "login_at",
      header: "Signed In",
      cell: ({ row }) => <span className="text-sm text-muted-foreground">{formatTimestamp(row.original.login_at)}</span>,
    },
    {
      accessorKey: "last_seen_at",
      header: "Last Seen",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{formatTimestamp(row.original.last_seen_at)}</span>
      ),
    },
    {
      accessorKey: "expires_at",
      header: "Expires",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{formatTimestamp(row.original.expires_at)}</span>
      ),
    },
    {
      id: "network",
      header: "Network",
      accessorFn: (row) => row.ip_address ?? "",
      cell: ({ row }) => (
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm">
            <Globe className="h-4 w-4 text-muted-foreground" />
            <span>{row.original.ip_address ?? "Unavailable"}</span>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            Session ID: {row.original.session_id}
          </p>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Auth Sessions"
        description="Superuser view across all user sessions. Read-only inventory for investigation and support."
        meta={
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Shield className="size-3.5" />
            Superuser
          </span>
        }
      />

      <AdminDataTable
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[10, 20, 50, 100]}
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "access-admin",
          "sessions",
          page,
          search,
          pageSize,
          sortField,
          sortDir,
          statusFilter,
        ]}
        queryFn={async (page, search, pageSize, sortField, sortDir) => {
          const sessions = await rbacService.listSessions({
            search: search || undefined,
            status: statusFilter !== "all" ? statusFilter : undefined,
          });
          return paginateResults(sortArray(sessions, sortField, sortDir), page, pageSize);
        }}
        columns={columns}
        searchPlaceholder="Search by email, username, IP, or user agent..."
        emptyMessage="No sessions found."
        actions={
          <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as "all" | AdminSessionStatus)}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="revoked">Revoked</SelectItem>
              <SelectItem value="expired">Expired</SelectItem>
            </SelectContent>
          </Select>
        }
      />
    </div>
  );
}
