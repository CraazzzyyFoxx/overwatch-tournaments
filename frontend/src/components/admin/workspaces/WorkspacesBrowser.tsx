"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { DataTable } from "@/components/data-table";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { paginateResults, sortArray } from "@/lib/api/paginate-results";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { WorkspaceListItem } from "@/types/workspace.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";

import { WorkspaceIcon } from "./WorkspaceCells";
import { WorkspaceInspectorActions, WorkspaceInspectorPanel } from "./WorkspaceInspectorPanel";
import { useWorkspaceColumns, workspaceHref } from "./useWorkspaceColumns";

const PAGE_SIZE = 15;

/**
 * Every workspace on the platform, as a list.
 *
 * The list itself is all this screen owns: a workspace's settings are eleven
 * sections behind `/admin/workspaces/[id]/*` (the same ones `/admin/settings`
 * mounts for the current workspace), so editing here means going there rather
 * than reproducing a form the sections already own.
 */
export function WorkspacesBrowser() {
  const t = useTranslations("adminAccess.common");
  const tw = useTranslations("adminAccess.workspace");
  const { isSuperuser, isWorkspaceAdmin } = usePermissions();
  const queryClient = useQueryClient();
  const router = useRouter();
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row sits on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;

  const [pageRows, setPageRows] = useState<WorkspaceListItem[]>([]);
  const [pendingDelete, setPendingDelete] = useState<WorkspaceListItem | null>(null);

  const invalidate = () => {
    // `["admin-workspaces"]` is the prefix the workspace settings sections
    // invalidate too (`workspace-settings/useWorkspaceSettingsForm.ts`), so a
    // rename made there refreshes this list without a reload.
    queryClient.invalidateQueries({ queryKey: adminQueryKeys.workspaces() });
    fetchWorkspaces();
  };

  const deleteMutation = useMutation({
    mutationFn: (id: number) => workspaceService.delete(id),
    onSuccess: () => {
      const removed = pendingDelete;
      invalidate();
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success(tw("deleted"));
    }
  });

  const columns = useWorkspaceColumns({
    isSuperuser,
    isWorkspaceAdmin,
    onDelete: setPendingDelete
  });

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;
  const canManageOpen = openRow ? isSuperuser || isWorkspaceAdmin(openRow.id) : false;

  return (
    <>
      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <DataTable<WorkspaceListItem>
            columns={columns}
            initialPageSize={PAGE_SIZE}
            searchPlaceholder={t("searchWorkspaces")}
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            emptyMessage={tw("noWorkspaces")}
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            onRowDoubleClick={(row) => {
              if (isSuperuser || isWorkspaceAdmin(row.original.id)) router.push(workspaceHref(row.original.id));
            }}
            renderMobileCard={(row) => (
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <WorkspaceIcon workspace={row.original} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{row.original.name}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    {row.original.slug}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {row.original.is_active ? t("active") : t("inactive")} ·{" "}
                    {row.original.is_hidden ? t("hidden") : t("listed")}
                  </p>
                </div>
              </div>
            )}
            queryKey={(page, search, pageSize, sortField, sortDir) => [
              "admin-workspaces",
              isSuperuser,
              page,
              search,
              pageSize,
              sortField,
              sortDir
            ]}
            queryFn={async (page, search, pageSize, sortField, sortDir) => {
              // `admin`: every workspace for a superuser (this is where
              // `unverified` ones get verified), memberships otherwise — then
              // narrowed to the ones the caller actually administers, which is
              // a permission question the endpoint does not answer.
              const all = await workspaceService.getAll("admin");
              const visible = isSuperuser ? all : all.filter((ws) => isWorkspaceAdmin(ws.id));
              const needle = search.trim().toLowerCase();
              const matching = needle
                ? visible.filter(
                    (ws) =>
                      ws.name.toLowerCase().includes(needle) ||
                      ws.slug.toLowerCase().includes(needle)
                  )
                : visible;
              return paginateResults(sortArray(matching, sortField, sortDir), page, pageSize);
            }}
            onPageRowsChange={setPageRows}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow?.name ?? ""}
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
          actions={
            openRow ? (
              <WorkspaceInspectorActions
                workspace={openRow}
                canEdit={canManageOpen}
                canDelete={isSuperuser}
                onDelete={setPendingDelete}
              />
            ) : null
          }
        >
          {openRow ? <WorkspaceInspectorPanel workspace={openRow} /> : null}
        </Inspector>
      </div>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: t("deleteWorkspace"),
          description: tw("deleteDescription", {
            workspace: pendingDelete?.name ?? t("thisWorkspace")
          }),
          confirmLabel: t("deleteWorkspace"),
          tone: "danger",
          cascade: [tw("deleteTournaments"), tw("deleteTeams"), tw("deleteMembers")],
          requireTyped: pendingDelete?.name
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </>
  );
}
