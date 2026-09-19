"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Globe, MonitorSmartphone, UserCog } from "lucide-react";
import { useFormatter } from "next-intl";

import { AdminDataTable, createKebabColumn } from "@/components/data-table";
import { AdminFilterBar } from "@/components/kit/AdminFilterBar";
import { AdminInspector } from "@/components/kit/AdminInspector";
import { useAdminFilters, type FilterDef } from "@/components/kit/useAdminFilters";
import { EYEBROW_CLASS, TONE_TEXT, type Tone } from "@/components/kit/tone";
import type { AdminDateFormatter } from "@/components/kit/format-time";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import { detectBrowser, detectPlatform } from "@/lib/user-agent";
import { rbacService } from "@/services/rbac.service";
import type { AdminAuthSession, AdminSessionStatus } from "@/types/rbac.types";

const PAGE_SIZE = 20;

const STATUS_META: Record<AdminSessionStatus, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  revoked: { label: "Revoked", tone: "warning" },
  expired: { label: "Expired", tone: "neutral" }
};

function formatTimestamp(format: AdminDateFormatter, value: string | null | undefined): string {
  if (!value) return "Unavailable";

  return format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" });
}

function formatDeviceLabel(userAgent: string | null | undefined): string {
  if (!userAgent) return "Unknown device";

  const browser = detectBrowser(userAgent);
  const platform = detectPlatform(userAgent);

  if (browser && platform) return `${browser} on ${platform}`;
  if (browser) return browser;
  if (platform) return platform;

  return userAgent.length > 64 ? `${userAgent.slice(0, 64)}…` : userAgent;
}

function accountsHref(session: AdminAuthSession): string {
  return `/admin/access/accounts?search=${encodeURIComponent(session.email ?? session.username ?? "")}`;
}

function StatusCell({ status }: Readonly<{ status: AdminSessionStatus }>) {
  const meta = STATUS_META[status];

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs font-medium", TONE_TEXT[meta.tone])}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {meta.label}
    </span>
  );
}

function Field({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <div className="mt-0.5 break-words text-sm">{children}</div>
    </div>
  );
}

/**
 * Auth sessions (T2, F15) — the superuser's read-only view of who is signed in
 * where.
 *
 * The status `<Select>` is now a URL chip, and the raw user agent and the
 * network address live in the inspector: they are what an investigation needs
 * and what made every row three lines tall. The session id stays in the row,
 * truncated, because it is how a session is named in a report.
 */
export default function AccessAdminSessionsPage() {
  const format = useFormatter();
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const [pageRows, setPageRows] = useState<AdminAuthSession[]>([]);

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "status",
        label: "Status",
        kind: "single",
        options: (Object.keys(STATUS_META) as AdminSessionStatus[]).map((status) => ({
          value: status,
          label: STATUS_META[status].label
        }))
      }
    ],
    []
  );
  const filters = useAdminFilters(defs);
  const statusFilter = String(filters.values.status ?? "");

  const openRow = pageRows.find((row) => row.session_id === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const columns = useMemo<ColumnDef<AdminAuthSession>[]>(
    () => [
      {
        accessorKey: "session_id",
        header: "ID",
        size: 140,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block truncate font-mono text-xs" title={row.original.session_id}>
            {row.original.session_id}
          </span>
        )
      },
      {
        id: "user",
        header: "Account",
        enableSorting: false,
        accessorFn: (row) => row.email ?? row.username ?? `#${row.user_id}`,
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">
              {row.original.email ?? "Email unavailable"}
            </p>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {row.original.username
                ? `@${row.original.username}`
                : `account #${row.original.user_id}`}
            </p>
          </div>
        )
      },
      {
        id: "device",
        header: "Device",
        enableSorting: false,
        accessorFn: (row) => formatDeviceLabel(row.user_agent),
        cell: ({ row }) => (
          <span className="flex min-w-0 items-center gap-2">
            <MonitorSmartphone aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate text-sm">{formatDeviceLabel(row.original.user_agent)}</span>
          </span>
        )
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusCell status={row.original.status} />
      },
      {
        accessorKey: "login_at",
        header: "Signed in",
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.login_at)}
          </span>
        )
      },
      {
        accessorKey: "last_seen_at",
        header: "Last seen",
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.last_seen_at)}
          </span>
        )
      },
      createKebabColumn<AdminAuthSession>(
        (row) => [{ label: "Open auth account", icon: UserCog, href: accountsHref(row) }],
        { rowLabel: (row) => `session of ${row.email ?? row.username ?? `#${row.user_id}`}` }
      )
    ],
    [format]
  );

  return (
    <div className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <AdminDataTable<AdminAuthSession>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          searchPlaceholder="Search by email, username, IP, or user agent…"
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => row.session_id}
          toolbar={<AdminFilterBar defs={defs} filters={filters} />}
          emptyMessage="No session matches. Clear the status chip to see every session."
          onRowClick={(row) => setParams({ id: row.original.session_id })}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {row.original.email ?? `account #${row.original.user_id}`}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {formatDeviceLabel(row.original.user_agent)}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {STATUS_META[row.original.status].label} ·{" "}
                <span className="tabular-nums">
                  {formatTimestamp(format, row.original.last_seen_at)}
                </span>
              </p>
            </div>
          )}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "access-admin",
            "sessions",
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            statusFilter
          ]}
          queryFn={async (page, search, pageSize, sortField, sortDir) => {
            const result = await rbacService.listSessions({
              page,
              per_page: pageSize,
              sort: sortField ?? undefined,
              order: sortDir,
              search: search || undefined,
              status: (statusFilter || undefined) as AdminSessionStatus | undefined
            });
            setPageRows(result.results);
            return result;
          }}
        />
      </div>

      <AdminInspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? (openRow.email ?? `Account #${openRow.user_id}`) : ""}
        subtitle={openRow ? formatDeviceLabel(openRow.user_agent) : undefined}
        openHref={openRow ? accountsHref(openRow) : undefined}
        onPrev={
          openIndex > 0
            ? () => setParams({ id: pageRows[openIndex - 1].session_id })
            : undefined
        }
        onNext={
          openIndex >= 0 && openIndex < pageRows.length - 1
            ? () => setParams({ id: pageRows[openIndex + 1].session_id })
            : undefined
        }
      >
        {openRow ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Status">
                <StatusCell status={openRow.status} />
              </Field>
              <Field label="Network">
                <span className="flex items-center gap-1.5">
                  <Globe aria-hidden className="size-3.5 text-muted-foreground" />
                  <span className="tabular-nums">{openRow.ip_address ?? "Unavailable"}</span>
                </span>
              </Field>
              <Field label="Signed in">
                <span className="tabular-nums">{formatTimestamp(format, openRow.login_at)}</span>
              </Field>
              <Field label="Last seen">
                <span className="tabular-nums">
                  {formatTimestamp(format, openRow.last_seen_at)}
                </span>
              </Field>
              <Field label="Expires">
                <span className="tabular-nums">{formatTimestamp(format, openRow.expires_at)}</span>
              </Field>
              <Field label="Revoked">
                <span className="tabular-nums">
                  {openRow.revoked_at ? formatTimestamp(format, openRow.revoked_at) : "Not revoked"}
                </span>
              </Field>
            </div>
            <Field label="Session id">
              <span className="font-mono text-xs tabular-nums">{openRow.session_id}</span>
            </Field>
            <Field label="User agent">
              <span className="font-mono text-xs">
                {openRow.user_agent ?? "User agent unavailable"}
              </span>
            </Field>
          </div>
        ) : null}
      </AdminInspector>
    </div>
  );
}
