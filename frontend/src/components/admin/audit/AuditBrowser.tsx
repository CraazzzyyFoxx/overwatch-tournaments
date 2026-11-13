"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { DataTable } from "@craazzzyyfoxx/admin-kit/data-table";
import {
  auditHistoryStartQuery,
  describeAuditAction,
  formatAuditActor,
  formatAuditDate,
  formatAuditTarget,
  formatAuditTimestamp,
  useAuditTranslator
} from "@/components/kit/audit-log";
import { FilterBar } from "@craazzzyyfoxx/admin-kit/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { AuditLogRead } from "@/types/admin.types";

import { AuditInspectorPanel } from "./AuditInspectorPanel";
import { auditFilterDefs } from "./filters";
import { SORTABLE, auditFeedFilters } from "./model";
import { useAuditColumns } from "./useAuditColumns";

/** Server caps `per_page` at 200, so the selector must not offer more. */
const PAGE_SIZE = 25;
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 200];

/**
 * Who did what, across the workspace.
 *
 * Six existing per-domain journals answer this inside their own domain; this one
 * answers it for role changes, API keys, tournament deletions and workspace
 * settings, which had no trail beyond stdout.
 *
 * Two writers used to share the query string — this page merged its filters onto
 * `window.location.search` by hand while `DataTable` wrote `page`/`search`
 * through the History API — and a filter change and a page change overwrote each
 * other depending on which landed last. Now the filters are a `useFilters`
 * chip set (one `router.replace` per change, which also drops `page` and `id`)
 * and the table keeps its own five names. Nothing else touches the URL.
 *
 * Mounted only once the page has a scope and `audit.read` in it.
 */
export function AuditBrowser({
  workspaceId,
  allWorkspaces,
  isSuperuser
}: Readonly<{
  workspaceId: number | null;
  /** The feed is platform-wide: every workspace plus the rows that belong to none. */
  allWorkspaces: boolean;
  isSuperuser: boolean;
}>) {
  const t = useTranslations("adminMatches.audit");
  const auditT = useAuditTranslator();
  const format = useFormatter();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row sits on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;

  const [pageRows, setPageRows] = useState<AuditLogRead[]>([]);

  const entityIdParam = searchParams?.get("entity_id") ?? "";
  const actorParam = searchParams?.get("actor_user_id") ?? "";
  const actionParam = searchParams?.get("action") ?? "";

  const defs = useMemo(
    () =>
      auditFilterDefs({
        t,
        auditT,
        isSuperuser,
        entityId: entityIdParam,
        actor: actorParam,
        action: actionParam,
        pageRows
      }),
    [isSuperuser, entityIdParam, actorParam, actionParam, pageRows, t, auditT]
  );

  const filters = useFilters(defs);
  const { entityType, entityId, actorUserId, action } = auditFeedFilters(filters.values);
  const scopeWorkspaceId = allWorkspaces ? null : workspaceId;

  /**
   * Filters that narrow *which rows* are in the feed, as opposed to which
   * workspace it covers. Only these change what an empty result means, so the
   * scope chip is deliberately not one of them.
   */
  const isNarrowed = entityType != null || entityId != null || actorUserId != null || action != null;

  // Skipped while a filter is on: only the unfiltered empty states quote the
  // journal's start date. The page never mounts this without a scope to ask
  // about, which the endpoint would answer with a 422 rather than a wider feed.
  const historyStart = useQuery({
    ...auditHistoryStartQuery({ workspaceId, allWorkspaces }),
    enabled: !isNarrowed,
    retry: false,
  });

  /**
   * Unfiltered, the empty feed quotes the journal's start date when it has one:
   * there is no backfill, so "nothing recorded" must not read as "nobody touched
   * anything". A workspace feed also says what it never holds: a global role
   * grant can reach inside this workspace and still land on a row with no
   * workspace. Whole sentences joined, never a split one.
   */
  const emptyMessage = isNarrowed
    ? t("noEntriesMatchFilters")
    : [
        t("noEntriesYet"),
        historyStart.data == null
          ? null
          : t("startedOn", { date: formatAuditDate(format, historyStart.data) }),
        allWorkspaces ? null : t("workspaceRows"),
      ]
        .filter(Boolean)
        .join(" ");

  const columns = useAuditColumns(filters);

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;
  const openTarget = openRow ? formatAuditTarget(openRow, auditT) : null;

  return (
      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <DataTable<AuditLogRead>
            columns={columns}
            initialPageSize={PAGE_SIZE}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            initialSort={{ field: "created_at", dir: "desc" }}
            filterKey={`${filters.filterKey}|${allWorkspaces}|${workspaceId}`}
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            searchPlaceholder={t("search")}
            emptyMessage={emptyMessage}
            toolbar={<FilterBar defs={defs} filters={filters} />}
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {describeAuditAction(row.original.action, auditT).label}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {formatAuditActor(row.original, auditT)}
                  {formatAuditTarget(row.original, auditT) ? ` · ${formatAuditTarget(row.original, auditT)}` : ""}
                </p>
                <p className="text-xs tabular-nums text-muted-foreground">
                  {formatAuditTimestamp(format, row.original.created_at)}
                </p>
              </div>
            )}
            queryKey={(page, search, pageSize, sortField, sortDir) => [
              "admin",
              "audit",
              "feed",
              allWorkspaces ? "all" : workspaceId,
              entityType,
              entityId,
              actorUserId,
              action,
              page,
              search,
              pageSize,
              sortField,
              sortDir,
            ]}
            queryFn={(page, search, pageSize, sortField, sortDir) =>
              adminService.listAudit({
                page,
                per_page: pageSize,
                // An unsortable column id would 422; the whitelist gate keeps the
                // request honest even if a column is added without checking.
                sort: sortField ? SORTABLE[sortField] : undefined,
                order: sortDir,
                search: search || undefined,
                entity_type: entityType,
                entity_id: entityId,
                actor_user_id: actorUserId,
                action,
                workspace_id: scopeWorkspaceId,
                allWorkspaces,
              })
            }
            onPageRowsChange={setPageRows}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow ? describeAuditAction(openRow.action, auditT).label : ""}
          subtitle={
            openRow
              ? t(openTarget ? "inspectorSubtitleWithTarget" : "inspectorSubtitle", {
                  time: formatAuditTimestamp(format, openRow.created_at),
                  actor: formatAuditActor(openRow, auditT),
                  target: openTarget ?? ""
                })
              : undefined
          }
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
        >
          {openRow ? <AuditInspectorPanel row={openRow} /> : null}
        </Inspector>
      </div>
  );
}
