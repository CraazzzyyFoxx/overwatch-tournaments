"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { useTranslations } from "next-intl";
import { Clock, UserPlus } from "lucide-react";

import { buildBalancerRegistrationColumns } from "@/components/balancer/registrations/_components/balancerRegistrationColumns";
import RegistrationBulkActions from "@/components/balancer/registrations/_components/RegistrationBulkActions";
import RegistrationFormDialogs from "@/components/balancer/registrations/_components/RegistrationFormDialogs";
import RegistrationInspectorBody from "@/components/balancer/registrations/_components/RegistrationInspectorBody";
import { buildRegistrationRowActions } from "@/components/balancer/registrations/_components/registrationRowActions";
import { builtinStatusName } from "@/components/balancer/registrations/_components/registrationsTranslator";
import {
  type RegistrationGroupingMode,
  groupRegistrations,
  normalizeRegistrationGroupingMode
} from "@/components/balancer/registrations/_components/registrationGrouping";
import { useRegistrationFilters } from "@/components/balancer/registrations/_hooks/useRegistrationFilters";
import { useRegistrationMutations } from "@/components/balancer/registrations/_hooks/useRegistrationMutations";
import { DataTable, type DataTableGroup, type TableCommand, createKebabColumn } from "@/components/data-table";
import { useAuditTrail } from "@/components/kit/AuditTrailSheet";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useQueryParams } from "@/hooks/useQueryParams";
import { usePermissions } from "@/hooks/usePermissions";
import { mergeStatusOptions } from "@/lib/registration/balancer-statuses";
import balancerAdminService from "@/services/balancer-admin.service";
import registrationService from "@/services/registration.service";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { RegistrationForm } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import adminService from "@/services/admin.service";

import { ADMISSION_LABELS, adminRoleForm } from "./registrationsTable.model";

export default function RegistrationsTable({
  tournamentId
}: Readonly<{
  tournamentId: number | null;
}>) {
  // The only translated strings on this screen: reason codes are shared with the
  // public participants page, so they live in the message catalogue rather than
  // as English literals like the rest of this admin table.
  const t = useTranslations();
  const tRegistrations = useTranslations("registrationsAdmin");
  // `id` (the inspector) is navigation, not narrowing: it must not drop the
  // filters the way a narrowing change does.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const { canAccessPermission } = usePermissions();
  const { open: openAuditTrail } = useAuditTrail();
  // Catalogs follow the opened tournament, not the public viewing filter.
  const workspaceId = useCurrentWorkspaceId();
  const tournamentQuery = useQuery({
    queryKey: adminQueryKeys.tournament(tournamentId),
    queryFn: () => adminService.getTournament(tournamentId!),
    enabled: tournamentId !== null
  });

  const [groupBy, setGroupBy] = useState<RegistrationGroupingMode>(
    normalizeRegistrationGroupingMode(searchParams?.get("group") ?? null)
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [editingRegistration, setEditingRegistration] = useState<AdminRegistration | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AdminRegistration | null>(null);

  // The whole pool in one request: a tournament's registrations are a few
  // hundred rows at most, and filtering them locally keeps the pending count
  // honest — it used to be computed over an already status-filtered list, so
  // filtering to "approved" reported zero pending.
  const registrationsQuery = useQuery({
    queryKey: balancerQueryKeys.registrations(tournamentId),
    queryFn: () =>
      balancerAdminService.listRegistrations(tournamentId as number, {
        include_deleted: false
      }),
    enabled: tournamentId !== null
  });

  const formQuery = useQuery({
    queryKey: balancerQueryKeys.registrationForm(tournamentId),
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  const publicFormQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationFormPublic(tournamentId),
    queryFn: () => registrationService.getForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  // Adapt the admin form into the public RegistrationForm shape used by the
  // shared RoleStep / sub-role catalog, so admin role editing is data-driven.
  // Without a questionnaire the organizer still edits against the opened tournament's own owner scope; with
  // neither loaded there is no form to offer (the dialogs wait rather than ask for another game's roles).
  const tournament = tournamentQuery.data;
  const roleForm = useMemo<RegistrationForm | null>(
    () => publicFormQuery.data ?? (tournament ? adminRoleForm(tournament) : null),
    [publicFormQuery.data, tournament]
  );
  const subroleCatalog = roleForm?.subrole_catalog;
  // The opened tournament's own game: role names, glyphs and the role filter come from its dictionary.
  const ontology =
    useDisciplineMetadata(tournament?.workspace_id ?? "all", tournament?.discipline ?? null).data ?? null;

  // `require_open_profile` is deliberately NOT read here any more: admission is
  // resolved server-side and travels on each row. This flag survives only
  // because the Subscription chip column exists or does not exist per tournament.
  const requireSubscription = formQuery.data?.require_subscription ?? false;
  // The questions the CURRENT schema asks, flattened in render order. A row
  // filed against an older version is still read through these: answers are
  // keyed, not positional. What the current schema no longer asks has no column
  // — the inspector shows those beside the row's stale-version notice.
  const schemaFields = useMemo(
    () => roleForm?.form_schema.sections.flatMap((section) => section.fields) ?? [],
    [roleForm]
  );

  // Whether the tournament's real schema is in hand. NOT `schemaFields.length`:
  // a schema may legitimately ask nothing (a section is allowed to be empty),
  // and the inspector must still be able to say that a stale answer's question
  // is gone. `data` rather than a loading flag, so a failed form query also
  // reads as "unknown" instead of "asks nothing".
  const schemaLoaded = publicFormQuery.data != null;

  const customStatusesQuery = useQuery({
    queryKey: balancerQueryKeys.statusCatalog(workspaceId),
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });
  const registrationStatusOptions = useMemo(
    () => mergeStatusOptions("registration", customStatusesQuery.data),
    [customStatusesQuery.data]
  );
  const statusFilterOptions = useMemo(
    () =>
      [...registrationStatusOptions.system, ...registrationStatusOptions.custom].map((option) => ({
        value: option.value,
        label: option.is_builtin ? builtinStatusName(option.value, tRegistrations) : option.name
      })),
    [registrationStatusOptions, tRegistrations]
  );

  const registrations = useMemo(() => registrationsQuery.data ?? [], [registrationsQuery.data]);

  const {
    defs: filterDefs,
    filters,
    tableFilters,
    onTableFiltersChange,
    visibleRegistrations
  } = useRegistrationFilters({ registrations, requireSubscription, statusFilterOptions, ontology });

  const {
    patchRegistrationInCache,
    createMutation,
    updateMutation,
    approveMutation,
    rejectMutation,
    withdrawMutation,
    restoreMutation,
    deleteMutation,
    bulkApproveMutation,
    balancerInclusionMutation,
    checkInMutation,
    bulkAddToBalancerMutation
  } = useRegistrationMutations({
    tournamentId,
    editingRegistration,
    onCreated: () => setCreateOpen(false),
    onUpdated: () => setEditingRegistration(null),
    onDeleted: () => setPendingDelete(null)
  });

  const pendingCount = registrations.filter(
    (registration) => registration.status === "pending"
  ).length;
  const statusFilterValue = filters.values.status;
  const isPendingFilterOn = Array.isArray(statusFilterValue)
    ? statusFilterValue.includes("pending")
    : false;

  // `mutate` is observer-bound and stable across renders; the mutation objects
  // around it are not, so the column memo depends on these rather than on them.
  const approve = approveMutation.mutate;
  const reject = rejectMutation.mutate;
  const withdraw = withdrawMutation.mutate;
  const restore = restoreMutation.mutate;
  const setBalancerInclusion = balancerInclusionMutation.mutate;
  const setCheckIn = checkInMutation.mutate;

  const adminNotesEdit = useMemo(
    () => ({
      save: async (registration: AdminRegistration, next: string) => {
        patchRegistrationInCache(
          await balancerAdminService.updateRegistration(registration.id, { admin_notes: next })
        );
      },
      // Same gate as the row's Edit action: a withdrawn row is read-only.
      canEdit: (registration: AdminRegistration) => registration.status !== "withdrawn"
    }),
    [patchRegistrationInCache]
  );

  const columns: ColumnDef<AdminRegistration>[] = useMemo(
    () => [
      ...buildBalancerRegistrationColumns(
        tRegistrations,
        subroleCatalog,
        requireSubscription,
        schemaFields,
        statusFilterOptions,
        adminNotesEdit,
        ontology
      ),
      createKebabColumn<AdminRegistration>(
        (registration) =>
          buildRegistrationRowActions(
            registration,
            {
              canAccessPermission,
              openAuditTrail,
              approve,
              reject,
              withdraw,
              restore,
              setBalancerInclusion,
              setCheckIn,
              onEdit: setEditingRegistration,
              onDelete: setPendingDelete
            },
            tRegistrations
          ),
        {
          rowLabel: (registration) =>
            registration.primary_handle ??
            registration.display_name ??
            tRegistrations("table.rowFallback", { id: registration.id })
        }
      )
    ],
    [
      subroleCatalog,
      ontology,
      requireSubscription,
      schemaFields,
      statusFilterOptions,
      adminNotesEdit,
      approve,
      reject,
      withdraw,
      restore,
      setBalancerInclusion,
      setCheckIn,
      canAccessPermission,
      openAuditTrail,
      tRegistrations
    ]
  );

  const groupPageRows = (
    pageRows: Row<AdminRegistration>[]
  ): DataTableGroup<AdminRegistration>[] => {
    const rowsById = new Map(pageRows.map((row) => [row.original.id, row]));
    return groupRegistrations(
      pageRows.map((row) => row.original),
      groupBy,
      (key) => t(`registrationsAdmin.grouping.${key}`)
    ).map((group) => ({
      key: group.key,
      label: (
        <>
          <span className="text-foreground">{group.label}</span>
          <span className="ml-2 font-normal normal-case text-muted-foreground">
            {t("registrationsAdmin.table.registrationCount", { count: group.registrations.length })}
          </span>
        </>
      ),
      rows: group.registrations.flatMap((registration) => {
        const row = rowsById.get(registration.id);
        return row ? [row] : [];
      })
    }));
  };

  const openId = searchParams?.get("id") ?? null;
  const inspected = openId
    ? (registrations.find((registration) => String(registration.id) === openId) ?? null)
    : null;

  const commands: TableCommand[] = [
    {
      id: "create",
      label: t("registrationsAdmin.table.create"),
      icon: UserPlus,
      onSelect: () => setCreateOpen(true),
      hidden: !canAccessPermission("registration.create", workspaceId)
    }
  ];

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>{t("registrationsAdmin.table.selectTournament")}</AlertTitle>
        <AlertDescription>
          {t("registrationsAdmin.table.selectTournamentDescription")}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div
      className={cn(
        "grid min-w-0 items-start gap-4",
        inspected && "lg:grid-cols-[minmax(0,1fr)_380px]"
      )}
    >
      <div className="flex min-h-0 min-w-0 flex-col gap-4">
        <DataTable<AdminRegistration>
          rows={visibleRegistrations}
          isLoading={registrationsQuery.isFetching}
          columns={columns}
          getRowId={(registration) => String(registration.id)}
          filters={tableFilters}
          onFiltersChange={onTableFiltersChange}
          filterKey={filters.filterKey}
          initialSort={{ field: "submitted", dir: "desc" }}
          paging="all"
          cellAlign="top"
          searchPlaceholder={t("registrationsAdmin.table.search")}
          emptyMessage={t("registrationsAdmin.table.empty")}
          columnsStorageKey="balancer-registrations-table-columns"
          enableRowSelection={(row) => row.original.status === "pending"}
          inspectorId={openId}
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          groupRows={groupBy === "none" ? undefined : groupPageRows}
          toolbar={
            <FilterBar
              defs={filterDefs}
              filters={filters}
              extraFilters={
                pendingCount > 0 ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0 gap-1.5 text-warning"
                    aria-pressed={isPendingFilterOn}
                    onClick={() => filters.set("status", isPendingFilterOn ? [] : ["pending"])}
                    title={
                      isPendingFilterOn
                        ? t("registrationsAdmin.table.clearPending")
                        : t("registrationsAdmin.table.showPending", { count: pendingCount })
                    }
                  >
                    <Clock className="h-3.5 w-3.5" aria-hidden />
                    {t("registrationsAdmin.table.pending", { count: pendingCount })}
                  </Button>
                ) : null
              }
            />
          }
          groupBy={{
            label: t("registrationsAdmin.table.groupAria"),
            value: groupBy,
            options: [
              { value: "none", label: t("registrationsAdmin.table.noGrouping") },
              { value: "check_in", label: t("registrationsAdmin.table.groupCheckIn") },
              { value: "balancer_status", label: t("registrationsAdmin.table.groupBalancer") },
              { value: "admission", label: t("registrationsAdmin.table.groupAdmission") }
            ],
            onChange: (value) => setGroupBy(value as RegistrationGroupingMode)
          }}
          summary={t("registrationsAdmin.table.registrationCount", { count: registrations.length })}
          commands={commands}
          bulkActions={(selected, clearSelection) => (
            <RegistrationBulkActions
              selected={selected}
              clearSelection={clearSelection}
              onApprove={bulkApproveMutation.mutate}
              approvePending={bulkApproveMutation.isPending}
              onAddToBalancer={bulkAddToBalancerMutation.mutate}
              addToBalancerPending={bulkAddToBalancerMutation.isPending}
            />
          )}
        />
      </div>

      <Inspector
        openId={inspected ? openId : null}
        onClose={() => setParams({ id: null })}
        title={
          inspected?.primary_handle ??
          inspected?.display_name ??
          t("registrationsAdmin.table.registration")
        }
        subtitle={
          inspected
            ? `${inspected.status} · ${ADMISSION_LABELS[inspected.admission.decision]}`
            : undefined
        }
      >
        {inspected && tournamentQuery.data ? (
          <RegistrationInspectorBody
            registration={inspected}
            discipline={tournamentQuery.data.discipline}
            ontology={ontology}
            catalog={subroleCatalog}
            schemaFields={schemaFields}
            schemaKnown={schemaLoaded}
            t={t}
          />
        ) : null}
      </Inspector>

      <RegistrationFormDialogs
        tournamentId={tournamentId}
        form={roleForm}
        createOpen={createOpen}
        onCreateOpenChange={setCreateOpen}
        onCreate={createMutation.mutateAsync}
        createPending={createMutation.isPending}
        editingRegistration={editingRegistration}
        onEditingChange={setEditingRegistration}
        onUpdate={updateMutation.mutateAsync}
        updatePending={updateMutation.isPending}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => (open ? undefined : setPendingDelete(null))}
        intent={{
          title: t("registrationsAdmin.table.deleteTitle"),
          description: t("registrationsAdmin.table.deleteDescription", {
            name:
              pendingDelete?.primary_handle ??
              pendingDelete?.display_name ??
              t("registrationsAdmin.table.registration")
          }),
          confirmLabel: t("registrationsAdmin.table.deleteConfirm"),
          tone: "danger"
        }}
        pending={deleteMutation.isPending}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
