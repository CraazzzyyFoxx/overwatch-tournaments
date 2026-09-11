"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { CheckCircle, Eye, EyeOff, Pencil, Plus, Trash2, XCircle } from "lucide-react";

import { CreateWorkspaceDialog } from "@/components/CreateWorkspaceDialog";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { adminColumnMeta } from "@/components/admin/admin-table-columns";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { AdminInspector } from "@/components/admin/kit/AdminInspector";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import { createKebabColumn } from "@/components/admin/kit/kebab-column";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { WorkspaceOwnerValue } from "@/components/admin/workspace-owner";
import { WorkspaceVerificationIcon } from "@/components/admin/workspace-verification";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { paginateResults, sortArray } from "@/lib/paginate-results";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Workspace } from "@/types/workspace.types";

const PAGE_SIZE = 15;

function WorkspaceIcon({ workspace }: Readonly<{ workspace: Workspace }>) {
  if (workspace.icon_url) {
    return (
      <img
        src={workspace.icon_url}
        alt=""
        aria-hidden
        className="size-8 shrink-0 rounded-md border border-border object-cover"
      />
    );
  }
  return (
    <div
      aria-hidden
      className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-xs font-medium text-muted-foreground"
    >
      {workspace.name.charAt(0).toUpperCase()}
    </div>
  );
}

function InspectorField({
  label,
  children
}: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <p className="mt-0.5 break-words text-sm text-foreground">{children}</p>
    </div>
  );
}

/**
 * Every workspace on the platform, as a list.
 *
 * The list itself is all this screen owns: a workspace's settings are eleven
 * sections behind `/admin/workspaces/[id]/*` (the same ones `/admin/settings`
 * mounts for the current workspace), so editing here means going there rather
 * than reproducing a form the sections already own.
 */
export default function WorkspacesPage() {
  const { isSuperuser, isWorkspaceAdmin, canManageAnyWorkspace, canUseCapability, isLoaded } =
    usePermissions();
  const queryClient = useQueryClient();
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row sits on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const [pageRows, setPageRows] = useState<Workspace[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Workspace | null>(null);

  const invalidate = () => {
    // `["admin-workspaces"]` is the prefix the workspace settings sections
    // invalidate too (`workspace-settings/useWorkspaceSettingsForm.ts`), so a
    // rename made there refreshes this list without a reload.
    queryClient.invalidateQueries({ queryKey: ["admin-workspaces"] });
    fetchWorkspaces();
  };

  const deleteMutation = useMutation({
    mutationFn: (id: number) => workspaceService.delete(id),
    onSuccess: () => {
      const removed = pendingDelete;
      invalidate();
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success("Workspace deleted");
    }
  });

  const columns = useMemo<ColumnDef<Workspace>[]>(
    () => [
      {
        accessorKey: "id",
        header: "#",
        size: 76,
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {row.original.id}
          </span>
        )
      },
      {
        accessorKey: "name",
        header: "Workspace",
        cell: ({ row }) => (
          <div className="flex min-w-0 items-center gap-2">
            <WorkspaceIcon workspace={row.original} />
            <span className="truncate font-medium" title={row.original.name}>
              {row.original.name}
            </span>
            <WorkspaceVerificationIcon status={row.original.verification_status} />
          </div>
        )
      },
      {
        accessorKey: "slug",
        header: "Slug",
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">{row.original.slug}</span>
        )
      },
      {
        accessorKey: "is_active",
        header: "Status",
        size: 120,
        meta: adminColumnMeta<Workspace>({ align: "center" }),
        cell: ({ row }) =>
          row.original.is_active ? (
            <StatusIcon icon={CheckCircle} label="Active" variant="success" />
          ) : (
            <StatusIcon icon={XCircle} label="Inactive" variant="muted" />
          )
      },
      {
        accessorKey: "is_hidden",
        header: "Visibility",
        size: 120,
        meta: adminColumnMeta<Workspace>({ align: "center" }),
        cell: ({ row }) =>
          row.original.is_hidden ? (
            <StatusIcon icon={EyeOff} label="Hidden" variant="warning" />
          ) : (
            <StatusIcon icon={Eye} label="Listed" variant="muted" />
          )
      },
      createKebabColumn<Workspace>(
        (row) => [
          {
            label: "Edit workspace",
            icon: Pencil,
            hidden: !(isSuperuser || isWorkspaceAdmin(row.id)),
            // The one place a workspace is edited: the settings sections under
            // `[id]/`, which are the same ones `/admin/settings` mounts.
            href: `/admin/workspaces/${row.id}/general`
          },
          {
            label: "Delete workspace",
            icon: Trash2,
            destructive: true,
            hidden: !isSuperuser,
            onSelect: () => setPendingDelete(row)
          }
        ],
        { rowLabel: (row) => row.name }
      )
    ],
    [isSuperuser, isWorkspaceAdmin]
  );

  if (!isLoaded) return <Skeleton className="h-64 w-full rounded-xl" />;

  // The same gate `admin-navigation.ts` puts on `/admin/workspaces`: the row
  // carries no permission, only `workspaceAdminVisible`, which for a null
  // workspace scope is exactly "administers at least one workspace".
  if (!canManageAnyWorkspace()) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unauthorized</CardTitle>
          <CardDescription>
            You do not administer any workspace, so there is none to list here.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;
  const canManageOpen = openRow ? isSuperuser || isWorkspaceAdmin(openRow.id) : false;

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Workspaces"
        description="Isolated tournament environments. Open one to edit its settings."
        actions={
          /* Creating a workspace is open to any active account now (the backend
             caps how many one account may own), so this is no longer a
             superuser button — but the right is revocable per account through
             negative RBAC, and the backend refuses a denied one, so the button
             goes away with it rather than offering a guaranteed 403. */
          canUseCapability("workspace.self_create") ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="size-3.5" aria-hidden />
              Create workspace
            </Button>
          ) : null
        }
      />

      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <AdminDataTable<Workspace>
            columns={columns}
            initialPageSize={PAGE_SIZE}
            searchPlaceholder="Search workspaces…"
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            emptyMessage="No workspaces yet. Use “Create workspace” to add the first one."
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <WorkspaceIcon workspace={row.original} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{row.original.name}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    {row.original.slug}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {row.original.is_active ? "Active" : "Inactive"} ·{" "}
                    {row.original.is_hidden ? "Hidden" : "Listed"}
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
              const result = paginateResults(
                sortArray(matching, sortField, sortDir),
                page,
                pageSize
              );
              // The inspector pages through the rows currently on screen, and
              // the table owns the fetch, so this is where that page is seen.
              setPageRows(result.results);
              return result;
            }}
          />
        </div>

        <AdminInspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow?.name ?? ""}
          subtitle={openRow ? `#${openRow.id} · ${openRow.slug}` : undefined}
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
              <>
                {canManageOpen ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={`/admin/workspaces/${openRow.id}/general`}>
                      <Pencil aria-hidden className="size-3.5" />
                      Edit
                    </Link>
                  </Button>
                ) : null}
                {isSuperuser ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-danger"
                    onClick={() => setPendingDelete(openRow)}
                  >
                    <Trash2 aria-hidden className="size-3.5" />
                    Delete
                  </Button>
                ) : null}
              </>
            ) : null
          }
        >
          {openRow ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <InspectorField label="Status">
                  {openRow.is_active ? "Active" : "Inactive"}
                </InspectorField>
                <InspectorField label="Visibility">
                  {openRow.is_hidden ? "Hidden from the public list" : "Listed"}
                </InspectorField>
                <InspectorField label="Timezone">{openRow.timezone}</InspectorField>
                <InspectorField label="Branding">
                  {openRow.branding_enabled ? "Custom" : "Platform default"}
                </InspectorField>
                <InspectorField label="Subdomain">{openRow.subdomain ?? "—"}</InspectorField>
                <InspectorField label="Custom domain">
                  {openRow.custom_domain
                    ? `${openRow.custom_domain}${openRow.custom_domain_verified_at ? "" : " (unverified)"}`
                    : "—"}
                </InspectorField>
                <InspectorField label="Discord guild">
                  {openRow.discord_guild_id ?? "—"}
                </InspectorField>
                <InspectorField label="Newcomers">
                  {openRow.newcomer_scope === "global" ? "Any workspace" : "This workspace"}
                </InspectorField>
                <InspectorField label="Owner">
                  <WorkspaceOwnerValue workspaceId={openRow.id} />
                </InspectorField>
              </div>

              <div>
                <p className={EYEBROW_CLASS}>Description</p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {openRow.description || "No description."}
                </p>
              </div>
            </div>
          ) : null}
        </AdminInspector>
      </div>

      <CreateWorkspaceDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={invalidate}
      />

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: "Delete workspace",
          description: `Deleting “${pendingDelete?.name ?? "this workspace"}” permanently removes every tournament, team, player, match and member inside it. This cannot be undone.`,
          confirmLabel: "Delete workspace",
          tone: "danger",
          cascade: [
            "All tournaments in this workspace",
            "All teams, players, matches, and statistics",
            "All workspace members"
          ],
          requireTyped: pendingDelete?.name
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
