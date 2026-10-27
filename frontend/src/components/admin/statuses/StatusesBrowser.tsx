"use client";

import { useCallback, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import type { Row } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { DataTable, type DataTableGroup, type TableCommand } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { useFilters } from "@/components/kit/useFilters";
import {
  EMPTY_STATUS_FORM,
  StatusForm,
  type StatusFormState
} from "@/components/admin/statuses/StatusForm";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  BalancerCustomStatus,
  BalancerCustomStatusCreateInput,
  BalancerCustomStatusUpdateInput
} from "@/types/balancer-admin.types";
import type { StatusScope } from "@/types/registration.types";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";

import { statusFilterDefs } from "./filters";
import { useStatusColumns } from "./useStatusColumns";

/**
 * Workspace status catalog: the registration and balancer statuses every
 * tournament in the workspace shares.
 *
 * One table, two groups. The screen used to be four hand-rolled tables — a
 * system/custom pair per scope — which meant a status's row looked different
 * depending on which of the four it landed in, and the scope was structural
 * rather than something you could filter by.
 */
export function StatusesBrowser({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const t = useTranslations("adminSettings.statuses");
  const filterDefs = statusFilterDefs(t);
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const filters = useFilters(filterDefs);
  const [dialogOpen, setDialogOpen] = useState(false);
  // `null` while the dialog creates; the status it edits otherwise.
  const [editingStatus, setEditingStatus] = useState<BalancerCustomStatus | null>(null);
  const [pendingStatus, setPendingStatus] = useState<BalancerCustomStatus | null>(null);
  const [form, setForm] = useState<StatusFormState>(EMPTY_STATUS_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  // D12: page is readable with team.read; mutations follow the server matrix (team.update).
  const canManageStatuses = canAccessPermission("team.update", workspaceId);

  const statusesQuery = useQuery({
    queryKey: balancerQueryKeys.statusCatalog(workspaceId),
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId)
  });

  const invalidateStatuses = async () => {
    await queryClient.invalidateQueries({
      queryKey: balancerQueryKeys.statusCatalog(workspaceId)
    });
  };

  const createMutation = useMutation({
    mutationFn: (data: BalancerCustomStatusCreateInput) =>
      balancerAdminService.createCustomStatus(workspaceId, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setDialogOpen(false);
      notify.success(t("toast.customCreated"));
    },
    onError: (error) => {
      notify.apiError(error, { title: t("errors.create") });
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ statusId, data }: { statusId: number; data: BalancerCustomStatusUpdateInput }) =>
      balancerAdminService.updateCustomStatus(workspaceId, statusId, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setDialogOpen(false);
      notify.success(t("toast.customUpdated"));
    },
    onError: (error) => {
      notify.apiError(error, { title: t("errors.save") });
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
      balancerAdminService.upsertBuiltinStatusOverride(workspaceId, scope, slug, data),
    onSuccess: async () => {
      await invalidateStatuses();
      setDialogOpen(false);
      notify.success(t("toast.systemUpdated"));
    },
    onError: (error) => {
      notify.apiError(error, { title: t("errors.systemSave") });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (statusId: number) =>
      balancerAdminService.deleteCustomStatus(workspaceId, statusId),
    onSuccess: async () => {
      await invalidateStatuses();
      setPendingStatus(null);
      notify.success(t("toast.customDeleted"));
    },
    onError: (error) => {
      notify.apiError(error, { title: t("errors.delete") });
    }
  });

  const resetBuiltinMutation = useMutation({
    mutationFn: ({ scope, slug }: { scope: StatusScope; slug: string }) =>
      balancerAdminService.resetBuiltinStatusOverride(workspaceId, scope, slug),
    onSuccess: async () => {
      await invalidateStatuses();
      setPendingStatus(null);
      notify.success(t("toast.systemReset"));
    },
    onError: (error) => {
      notify.apiError(error, { title: t("errors.reset") });
    }
  });

  const scopeFilter = typeof filters.values.scope === "string" ? filters.values.scope : "";
  const rows = useMemo(() => {
    const all = statusesQuery.data ?? [];
    return scopeFilter ? all.filter((row) => row.scope === scopeFilter) : all;
  }, [statusesQuery.data, scopeFilter]);

  const openEdit = useCallback((statusRow: BalancerCustomStatus) => {
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
    setFormError(null);
    setDialogOpen(true);
  }, []);

  const columns = useStatusColumns({
    canManageStatuses,
    showScope: !scopeFilter,
    onEdit: openEdit,
    onConfirm: setPendingStatus
  });

  /** System first: those exist in every workspace, so they are the reference a
   *  custom status is read against. */
  const groupRows = (
    pageRows: Row<BalancerCustomStatus>[]
  ): DataTableGroup<BalancerCustomStatus>[] =>
    [
      { key: "builtin", label: t("system"), rows: pageRows.filter((r) => r.original.kind === "builtin") },
      { key: "custom", label: t("custom"), rows: pageRows.filter((r) => r.original.kind !== "builtin") }
    ].filter((group) => group.rows.length > 0);

  const submitCreate = () => {
    if (!form.name.trim()) {
      setFormError(t("validation.createName"));
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
      setFormError(t("validation.saveName"));
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
        title: t("confirm.resetTitle"),
        tone: "warning",
        confirmLabel: t("confirm.reset"),
        description: t("confirm.resetDescription", { name: pendingStatus?.name ?? "" })
      }
    : {
        title: t("confirm.deleteTitle"),
        tone: "danger",
        confirmLabel: t("confirm.delete"),
        description: t("confirm.deleteDescription", { name: pendingStatus?.name ?? "" })
      };

  const commands: TableCommand[] = [
    {
      id: "add",
      label: t("add"),
      icon: Plus,
      primary: true,
      hidden: !canManageStatuses,
      onSelect: () => {
        setEditingStatus(null);
        setForm({
          ...EMPTY_STATUS_FORM,
          // The scope chip is the admin's current context, so a new
          // status starts in the scope they are looking at.
          scope: scopeFilter === "balancer" ? "balancer" : "registration"
        });
        setFormError(null);
        setDialogOpen(true);
      }
    }
  ];

  if (statusesQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError.title")}
        onAction={() => void statusesQuery.refetch()}
        actionLabel={t("tryAgain")}
      />
    );
  }

  return (
    <div className="space-y-4">
      <DataTable<BalancerCustomStatus>
        rows={rows}
        isLoading={statusesQuery.isLoading}
        columns={columns}
        getRowId={(row) => `${row.kind}:${row.scope}:${row.slug}`}
        filterKey={filters.filterKey}
        groupRows={groupRows}
        searchPlaceholder={t("search")}
        emptyMessage={t("empty")}
        initialPageSize={25}
        columnsStorageKey="workspace-statuses-table-columns"
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        commands={commands}
      />

      <p className="max-w-prose text-xs text-muted-foreground">{t("note")}</p>

      <EntityFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title={
          editingStatus === null
            ? t("createTitle")
            : editingStatus.kind === "builtin"
              ? t("editSystemTitle")
              : t("editCustomTitle")
        }
        description={
          editingStatus === null
            ? t("createDescription")
            : editingStatus.kind === "builtin"
              ? t("editSystemDescription")
              : t("editCustomDescription")
        }
        onSubmit={editingStatus === null ? submitCreate : submitEdit}
        submitLabel={editingStatus === null ? t("create") : t("save")}
        submittingLabel={editingStatus === null ? t("creating") : t("saving")}
        isSubmitting={
          createMutation.isPending || updateMutation.isPending || updateBuiltinMutation.isPending
        }
        isReadOnly={!canManageStatuses}
        errorMessage={formError ?? undefined}
        contentClassName="max-w-lg"
      >
        <StatusForm
          value={form}
          onChange={setForm}
          disableScope={editingStatus !== null}
          isBuiltin={editingStatus?.kind === "builtin"}
        />
      </EntityFormDialog>

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
