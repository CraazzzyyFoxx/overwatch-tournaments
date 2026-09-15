"use client";

import { useMemo, useState } from "react";
import { Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import { AdminDataTable, type AdminDataTableGroup, adminColumnMeta, createKebabColumn } from "@/components/admin-data-table";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { ConfirmDialog, type ConfirmIntent } from "@/components/admin/kit/ConfirmDialog";
import { useAdminFilters, type FilterDef } from "@/components/admin/kit/useAdminFilters";
import {
  EMPTY_STATUS_FORM,
  StatusForm,
  type StatusFormState
} from "@/components/admin/statuses/StatusForm";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  BalancerCustomStatus,
  BalancerCustomStatusCreateInput,
  BalancerCustomStatusUpdateInput
} from "@/types/balancer-admin.types";
import type { StatusScope } from "@/types/registration.types";

const SCOPE_LABELS: Record<StatusScope, string> = {
  registration: "Registration",
  balancer: "Balancer"
};

const FILTER_DEFS: FilterDef[] = [
  {
    key: "scope",
    label: "Scope",
    kind: "single",
    options: [
      { value: "registration", label: "Registration" },
      { value: "balancer", label: "Balancer" }
    ]
  }
];

/** `StatusMetaBadge` renders from the shared `StatusMeta` shape, which the
 *  catalog row nearly is: it carries no `value`, and its edit/delete grants are
 *  a property of the kind rather than of the row. */
function badgeMeta(row: BalancerCustomStatus) {
  const isBuiltin = row.kind === "builtin";
  return {
    value: row.slug,
    scope: row.scope,
    is_builtin: isBuiltin,
    kind: row.kind,
    is_override: row.is_override,
    can_edit: true,
    can_delete: !isBuiltin,
    can_reset: isBuiltin && row.can_reset,
    icon_slug: row.icon_slug,
    icon_color: row.icon_color,
    name: row.name,
    description: row.description,
    excludes_from_balancer: row.excludes_from_balancer,
    excludes_from_ready: row.excludes_from_ready
  };
}

/**
 * Workspace status catalog: the registration and balancer statuses every
 * tournament in the workspace shares.
 *
 * One table, two groups. The screen used to be four hand-rolled tables — a
 * system/custom pair per scope — which meant a status's row looked different
 * depending on which of the four it landed in, and the scope was structural
 * rather than something you could filter by.
 */
export default function WorkspaceStatusesSettingsPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const filters = useAdminFilters(FILTER_DEFS);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingStatus, setEditingStatus] = useState<BalancerCustomStatus | null>(null);
  const [pendingStatus, setPendingStatus] = useState<BalancerCustomStatus | null>(null);
  const [form, setForm] = useState<StatusFormState>(EMPTY_STATUS_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  // D12: page is readable with team.read; mutations follow the server matrix (team.update).
  const canManageStatuses = canAccessPermission("team.update", workspaceId);

  const statusesQuery = useQuery({
    queryKey: ["balancer-admin", "status-catalog", workspaceId],
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });

  const invalidateStatuses = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["balancer-admin", "status-catalog", workspaceId]
    });
  };

  const createMutation = useMutation({
    mutationFn: (data: BalancerCustomStatusCreateInput) =>
      balancerAdminService.createCustomStatus(workspaceId as number, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setCreateOpen(false);
      setForm(EMPTY_STATUS_FORM);
      notify.success("Custom status created");
    },
    onError: (error) => {
      notify.apiError(error, { title: "Could not create the status" });
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ statusId, data }: { statusId: number; data: BalancerCustomStatusUpdateInput }) =>
      balancerAdminService.updateCustomStatus(workspaceId as number, statusId, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setEditingStatus(null);
      setForm(EMPTY_STATUS_FORM);
      notify.success("Custom status updated");
    },
    onError: (error) => {
      notify.apiError(error, { title: "Could not save the status" });
    }
  });

  const updateBuiltinMutation = useMutation({
    mutationFn: ({
      scope,
      slug,
      data
    }: {
      scope: StatusScope;
      slug: string;
      data: BalancerCustomStatusUpdateInput;
    }) =>
      balancerAdminService.upsertBuiltinStatusOverride(workspaceId as number, scope, slug, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setEditingStatus(null);
      setForm(EMPTY_STATUS_FORM);
      notify.success("System status updated");
    },
    onError: (error) => {
      notify.apiError(error, { title: "Could not save the system status override" });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (statusId: number) =>
      balancerAdminService.deleteCustomStatus(workspaceId as number, statusId),
    onSuccess: async () => {
      await invalidateStatuses();
      setPendingStatus(null);
      notify.success("Custom status deleted");
    },
    onError: (error) => {
      notify.apiError(error, { title: "Could not delete the status" });
    }
  });

  const resetBuiltinMutation = useMutation({
    mutationFn: ({ scope, slug }: { scope: StatusScope; slug: string }) =>
      balancerAdminService.resetBuiltinStatusOverride(workspaceId as number, scope, slug),
    onSuccess: async () => {
      await invalidateStatuses();
      setPendingStatus(null);
      notify.success("System status reset");
    },
    onError: (error) => {
      notify.apiError(error, { title: "Could not reset the system status" });
    }
  });

  const scopeFilter = typeof filters.values.scope === "string" ? filters.values.scope : "";
  const rows = useMemo(() => {
    const all = statusesQuery.data ?? [];
    return scopeFilter ? all.filter((row) => row.scope === scopeFilter) : all;
  }, [statusesQuery.data, scopeFilter]);

  const openEdit = (statusRow: BalancerCustomStatus) => {
    setEditingStatus(statusRow);
    setForm({
      scope: statusRow.scope,
      icon_slug: statusRow.icon_slug ?? "",
      icon_color: statusRow.icon_color ?? "",
      name: statusRow.name,
      description: statusRow.description ?? "",
      excludes_from_balancer: statusRow.excludes_from_balancer,
      excludes_from_ready: statusRow.excludes_from_ready
    });
  };

  const columns = useMemo<ColumnDef<BalancerCustomStatus>[]>(
    () => [
      {
        id: "status",
        accessorFn: (row) => row.name,
        header: "Status",
        meta: adminColumnMeta<BalancerCustomStatus>({
          category: "core",
          mandatory: true,
          searchValue: (row) => `${row.name} ${row.slug}`
        }),
        cell: ({ row }) => (
          <StatusMetaBadge meta={badgeMeta(row.original)} fallbackValue={row.original.slug} />
        )
      },
      {
        id: "scope",
        accessorFn: (row) => SCOPE_LABELS[row.scope],
        header: "Scope",
        meta: adminColumnMeta<BalancerCustomStatus>({
          category: "core",
          searchValue: (row) => SCOPE_LABELS[row.scope]
        }),
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{SCOPE_LABELS[row.original.scope]}</span>
        )
      },
      {
        id: "slug",
        accessorFn: (row) => row.slug,
        header: "Slug",
        meta: adminColumnMeta<BalancerCustomStatus>({
          category: "meta",
          searchValue: (row) => row.slug
        }),
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.slug}</span>
      },
      {
        id: "description",
        accessorFn: (row) => row.description ?? "",
        header: "Description",
        enableSorting: false,
        meta: adminColumnMeta<BalancerCustomStatus>({ category: "core" }),
        cell: ({ row }) => (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>{row.original.description ?? "—"}</span>
            {row.original.excludes_from_balancer ? (
              <StatusPill tone="warning">Excludes pool</StatusPill>
            ) : null}
            {row.original.excludes_from_ready ? (
              <StatusPill tone="warning">Blocks ready</StatusPill>
            ) : null}
          </div>
        )
      },
      createKebabColumn<BalancerCustomStatus>(
        (row) => [
          {
            label: "Edit",
            icon: Pencil,
            hidden: !canManageStatuses,
            onSelect: () => openEdit(row)
          },
          {
            label: "Reset to default",
            icon: RotateCcw,
            hidden: !canManageStatuses || row.kind !== "builtin" || !row.can_reset,
            onSelect: () => setPendingStatus(row)
          },
          {
            label: "Delete",
            icon: Trash2,
            destructive: true,
            hidden: !canManageStatuses || row.kind === "builtin",
            onSelect: () => setPendingStatus(row)
          }
        ],
        {
          rowLabel: (row) =>
            `the ${row.name} ${row.kind === "builtin" ? "system" : "custom"} status`
        }
      )
    ],
    [canManageStatuses]
  );

  /** System first: those exist in every workspace, so they are the reference a
   *  custom status is read against. */
  const groupRows = (
    pageRows: Row<BalancerCustomStatus>[]
  ): AdminDataTableGroup<BalancerCustomStatus>[] =>
    [
      { key: "builtin", label: "System", rows: pageRows.filter((r) => r.original.kind === "builtin") },
      { key: "custom", label: "Custom", rows: pageRows.filter((r) => r.original.kind !== "builtin") }
    ].filter((group) => group.rows.length > 0);

  const submitCreate = () => {
    if (!form.name.trim()) {
      setFormError("Give the status a name before creating it.");
      return;
    }
    setFormError(null);
    createMutation.mutate({
      scope: form.scope,
      icon_slug: form.icon_slug || null,
      icon_color: form.icon_color || null,
      name: form.name,
      description: form.description || null,
      excludes_from_balancer: form.scope === "balancer" ? form.excludes_from_balancer : false,
      excludes_from_ready: form.scope === "balancer" ? form.excludes_from_ready : false
    });
  };

  const submitEdit = () => {
    if (!editingStatus) return;
    if (!form.name.trim()) {
      setFormError("Give the status a name before saving it.");
      return;
    }
    setFormError(null);
    if (editingStatus.kind === "builtin") {
      updateBuiltinMutation.mutate({
        scope: editingStatus.scope,
        slug: editingStatus.slug,
        data: {
          icon_slug: form.icon_slug || null,
          icon_color: form.icon_color || null,
          name: form.name,
          description: form.description || null
        }
      });
      return;
    }
    updateMutation.mutate({
      statusId: editingStatus.id,
      data: {
        icon_slug: form.icon_slug || null,
        icon_color: form.icon_color || null,
        name: form.name,
        description: form.description || null,
        excludes_from_balancer:
          editingStatus.scope === "balancer" ? form.excludes_from_balancer : false,
        excludes_from_ready: editingStatus.scope === "balancer" ? form.excludes_from_ready : false
      }
    });
  };

  // Resetting a built-in and deleting a custom status are different promises:
  // one restores a default that is still there, the other removes a label the
  // workspace invented. Same dialog, swapped intent.
  const isReset = pendingStatus?.kind === "builtin";
  const confirmIntent: ConfirmIntent = isReset
    ? {
        title: "Reset system status",
        tone: "warning",
        confirmLabel: "Reset status",
        description: `“${pendingStatus?.name}” goes back to its default built-in name, icon and color. The workspace override is discarded.`
      }
    : {
        title: "Delete custom status",
        tone: "danger",
        confirmLabel: "Delete status",
        description: `“${pendingStatus?.name}” is removed from the catalog. Registrations already using it keep the raw slug, and the server refuses the delete if the status is still in use.`
      };

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace in the sidebar to manage its registration and balancer statuses."
      />
    );
  }

  if (statusesQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load the status catalog"
        onAction={() => void statusesQuery.refetch()}
        actionLabel="Try again"
      />
    );
  }

  return (
    <div className="space-y-4">
      <AdminDataTable<BalancerCustomStatus>
        rows={rows}
        isLoading={statusesQuery.isLoading}
        columns={columns}
        getRowId={(row) => `${row.kind}:${row.scope}:${row.slug}`}
        filterKey={filters.filterKey}
        groupRows={groupRows}
        searchPlaceholder="Search statuses"
        emptyMessage="No statuses match this scope."
        initialPageSize={25}
        columnsStorageKey="workspace-statuses-table-columns"
        toolbar={
          <AdminFilterBar
            defs={FILTER_DEFS}
            filters={filters}
            trailing={
              canManageStatuses ? (
                <Button
                  size="sm"
                  onClick={() => {
                    setForm({
                      ...EMPTY_STATUS_FORM,
                      // The scope chip is the admin's current context, so a new
                      // status starts in the scope they are looking at.
                      scope: scopeFilter === "balancer" ? "balancer" : "registration"
                    });
                    setCreateOpen(true);
                  }}
                >
                  <Plus className="mr-2 size-4" aria-hidden />
                  Add status
                </Button>
              ) : null
            }
          />
        }
      />

      <p className="text-xs text-muted-foreground">
        System statuses stay system-controlled: an edit here is a workspace override of their
        name, icon and color, and can be reset. Custom statuses add extra labels this workspace
        owns.
      </p>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) setFormError(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create custom status</DialogTitle>
            <DialogDescription>
              The slug is generated automatically from the name and stays stable after edits.
            </DialogDescription>
          </DialogHeader>
          <StatusForm value={form} onChange={setForm} />
          {formError && <p className="text-sm text-danger">{formError}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={submitCreate}
              disabled={createMutation.isPending || !canManageStatuses}
            >
              {createMutation.isPending ? "Creating…" : "Create status"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingStatus !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditingStatus(null);
            setForm(EMPTY_STATUS_FORM);
            setFormError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingStatus?.kind === "builtin" ? "Edit system status" : "Edit custom status"}
            </DialogTitle>
            <DialogDescription>
              {editingStatus?.kind === "builtin"
                ? "Save a workspace override for this system status without changing its slug or workflow."
                : "Update visual metadata without changing the stored slug."}
            </DialogDescription>
          </DialogHeader>
          <StatusForm
            value={form}
            onChange={setForm}
            disableScope
            isBuiltin={editingStatus?.kind === "builtin"}
          />
          {formError && <p className="text-sm text-danger">{formError}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingStatus(null)}>
              Cancel
            </Button>
            <Button
              onClick={submitEdit}
              disabled={
                updateMutation.isPending || updateBuiltinMutation.isPending || !canManageStatuses
              }
            >
              {updateMutation.isPending || updateBuiltinMutation.isPending
                ? "Saving…"
                : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={pendingStatus !== null}
        onOpenChange={(open) => !open && setPendingStatus(null)}
        intent={confirmIntent}
        pending={deleteMutation.isPending || resetBuiltinMutation.isPending}
        onConfirm={() => {
          if (!pendingStatus) return;
          if (pendingStatus.kind === "builtin") {
            resetBuiltinMutation.mutate({
              scope: pendingStatus.scope,
              slug: pendingStatus.slug
            });
            return;
          }
          deleteMutation.mutate(pendingStatus.id);
        }}
      />
    </div>
  );
}
