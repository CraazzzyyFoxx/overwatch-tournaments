"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { useTranslations } from "next-intl";
import {
  ArrowRight,
  Check,
  Clock,
  History,
  Loader2,
  Pencil,
  ShieldX,
  Trash2,
  Undo2,
  UserPlus,
  X
} from "lucide-react";
import Link from "next/link";

import UnifiedRegistrationForm from "@/components/registration/UnifiedRegistrationForm";
import { renderCustomFieldValue } from "@/components/registration/customFieldValue";
import { buildBalancerRegistrationColumns } from "@/components/balancer/registrations/_components/balancerRegistrationColumns";
import {
  type RegistrationGroupingMode,
  groupRegistrations,
  normalizeRegistrationGroupingMode
} from "@/components/balancer/registrations/_components/registrationGrouping";
import { AdminDataTable, type AdminDataTableGroup, type AdminTableFilters, createKebabColumn, type KebabAction } from "@/components/admin-data-table";
import { useAuditTrail } from "@/components/admin/AuditTrailSheet";
import { BulkBar } from "@/components/admin/BulkBar";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { AdminInspector } from "@/components/admin/kit/AdminInspector";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import {
  useAdminFilters,
  type FilterDef,
  type FilterValue
} from "@/components/admin/kit/useAdminFilters";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useQueryParams } from "@/hooks/useQueryParams";
import { usePermissions } from "@/hooks/usePermissions";
import { mergeStatusOptions } from "@/lib/balancer-statuses";
import { notify } from "@/lib/notify";
import { formatAdmissionReason, type AdmissionTranslator } from "@/lib/admission";
import { ROLE_LABELS, getSubroleLabel } from "@/lib/roles";
import balancerAdminService from "@/services/balancer-admin.service";
import registrationService from "@/services/registration.service";
import type {
  AdminRegistration,
  AdminRegistrationCreateInput,
  AdminRegistrationUpdateInput
} from "@/types/balancer-admin.types";
import type { AdmissionDecision } from "@/types/registration.types";
import type { RegistrationForm, SubroleCatalog } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";

// Minimal fallback used only until the real registration form (with its
// workspace sub-role catalog) loads. Sub-role options are then data-driven.
const ADMIN_ROLE_FORM: RegistrationForm = {
  id: 0,
  tournament_id: 0,
  workspace_id: 0,
  is_open: true,
  built_in_fields: {
    primary_role: { enabled: true, required: true },
    additional_roles: { enabled: true, required: false }
  },
  custom_fields: []
};

const ADMISSION_LABELS: Record<AdmissionDecision, string> = {
  admitted: "Admitted",
  pending_check_in: "Check-in pending",
  not_admitted: "Not admitted"
};

const SUBSCRIPTION_LABELS = {
  satisfied: "Satisfied",
  refused: "Refused",
  undetermined: "Undetermined"
} as const;

/**
 * Chip keys the TABLE resolves, because a column declares them as a header
 * filter (`meta.filter`) — which in client mode is how a URL param is mapped
 * onto the column whose values it matches. The remaining chips narrow
 * `visibleRegistrations` below instead: "which role" is not a column value to
 * match against. Both halves read the same
 * URL-backed `useAdminFilters` store, so there is still exactly one place a
 * filter lives.
 */
const COLUMN_FILTER_KEYS = ["status", "inclusion", "source"] as const;

function formatSubmittedAt(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}

function RolesCell({
  roles,
  catalog
}: Readonly<{
  roles: AdminRegistration["roles"];
  catalog?: SubroleCatalog;
}>) {
  const active = roles.filter((role) => role.is_active);
  if (active.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <span className="flex flex-wrap gap-1.5">
      {active
        .slice()
        .sort((left, right) => left.priority - right.priority)
        .map((role) => {
          const subroleLabel = role.subrole
            ? getSubroleLabel(catalog, role.role, role.subrole)
            : null;
          return (
            <span
              key={`${role.role}-${role.subrole ?? "base"}-${role.priority}`}
              className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-xs"
            >
              <span className={cn(role.is_primary && "font-medium text-foreground")}>
                {ROLE_LABELS[role.role] ?? role.role}
              </span>
              {subroleLabel ? (
                <span className="text-muted-foreground">{subroleLabel}</span>
              ) : null}
              {role.rank_value != null ? (
                <span className="tabular-nums text-muted-foreground">{role.rank_value}</span>
              ) : null}
            </span>
          );
        })}
    </span>
  );
}

export default function RegistrationsTable({
  tournamentId
}: Readonly<{
  tournamentId: number | null;
}>) {
  const queryClient = useQueryClient();
  // The only translated strings on this screen: reason codes are shared with the
  // public participants page, so they live in the message catalogue rather than
  // as English literals like the rest of this admin table.
  const t = useTranslations();
  // `id` (the inspector) is navigation, not narrowing: it must not drop the
  // filters the way a narrowing change does.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const { canAccessPermission } = usePermissions();
  const { open: openAuditTrail } = useAuditTrail();
  // D25: status/sub-role catalogs are read from the workspace store. In the hub
  // the store is already aligned to the tournament's workspace by
  // useSyncActiveWorkspace, so no extra wiring is needed here.
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

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
    queryKey: ["balancer-admin", "registrations", tournamentId],
    queryFn: () =>
      balancerAdminService.listRegistrations(tournamentId as number, {
        include_deleted: false
      }),
    enabled: tournamentId !== null
  });

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  const publicFormQuery = useQuery({
    queryKey: ["registration-form-public", tournamentId],
    queryFn: () => registrationService.getForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  // Adapt the admin form into the public RegistrationForm shape used by the
  // shared RoleStep / sub-role catalog, so admin role editing is data-driven.
  const roleForm: RegistrationForm = publicFormQuery.data ?? ADMIN_ROLE_FORM;
  const subroleCatalog = roleForm.subrole_catalog;

  // `require_open_profile` is deliberately NOT read here any more: admission is
  // resolved server-side and travels on each row. This flag survives only
  // because the Subscription chip column exists or does not exist per tournament.
  const requireSubscription = formQuery.data?.require_subscription ?? false;
  const customFields = roleForm.custom_fields;

  const customStatusesQuery = useQuery({
    queryKey: ["balancer-admin", "status-catalog", workspaceId],
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
        label: option.name
      })),
    [registrationStatusOptions]
  );

  const registrations = useMemo(() => registrationsQuery.data ?? [], [registrationsQuery.data]);

  // Options are read off the pool rather than hard-coded: a workspace's roles
  // are configuration, and a chip offering a value no row has is a dead end.
  // The same pass counts every facet, each one exactly the way its filter
  // narrows the pool, so the chip counts cannot disagree with the result.
  //
  // No Division chip (F4 lists one): `AdminRegistrationRole` carries a rank,
  // not a division, and turning one into the other needs the workspace division
  // grid — a query the hub deliberately does not run on every page load.
  const facets = useMemo(() => {
    const role = new Map<string, number>();
    const status = new Map<string, number>();
    const subscription = new Map<string, number>();
    const source = new Map<string, number>();
    let included = 0;
    for (const registration of registrations) {
      // Per registration, not per role entry: the Role chip asks whether a row
      // has that role, so a row must count once for it.
      const codes = new Set<string>();
      for (const entry of registration.roles) {
        if (entry.is_active) codes.add(entry.role);
      }
      for (const code of codes) role.set(code, (role.get(code) ?? 0) + 1);
      status.set(registration.status, (status.get(registration.status) ?? 0) + 1);
      const outcome = registration.subscription_outcome ?? "undetermined";
      subscription.set(outcome, (subscription.get(outcome) ?? 0) + 1);
      source.set(registration.source, (source.get(registration.source) ?? 0) + 1);
      // Mirrors the inclusion column's own filter, which reads the meta flag
      // rather than comparing the status slug.
      if (!registration.balancer_status_meta.excludes_from_balancer) included += 1;
    }
    return {
      role,
      status,
      subscription,
      source,
      included,
      excluded: registrations.length - included
    };
  }, [registrations]);

  const roleOptions = useMemo(
    () =>
      [...facets.role.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([code, count]) => ({ value: code, label: ROLE_LABELS[code] ?? code, count })),
    [facets]
  );

  const admissionOptions = useMemo(() => {
    const counts = new Map<AdmissionDecision, number>();
    for (const registration of registrations) {
      const decision = registration.admission.decision;
      counts.set(decision, (counts.get(decision) ?? 0) + 1);
    }
    return (Object.keys(ADMISSION_LABELS) as AdmissionDecision[]).map((decision) => ({
      value: decision,
      label: ADMISSION_LABELS[decision],
      count: counts.get(decision) ?? 0
    }));
  }, [registrations]);

  const filterDefs: FilterDef[] = useMemo(
    () => [
      { key: "admission", label: "Admission", kind: "single", options: admissionOptions },
      { key: "role", label: "Role", kind: "single", options: roleOptions },
      ...(requireSubscription
        ? [
            {
              key: "subscription",
              label: "Subscription",
              kind: "single" as const,
              options: (
                Object.keys(SUBSCRIPTION_LABELS) as (keyof typeof SUBSCRIPTION_LABELS)[]
              ).map((value) => ({
                value,
                label: SUBSCRIPTION_LABELS[value],
                count: facets.subscription.get(value) ?? 0
              }))
            }
          ]
        : []),
      {
        key: "status",
        label: "Status",
        kind: "multi",
        options: statusFilterOptions.map((option) => ({
          ...option,
          count: facets.status.get(option.value) ?? 0
        }))
      },
      {
        key: "inclusion",
        label: "Participation",
        kind: "single",
        options: [
          { value: "included", label: "Included", count: facets.included },
          { value: "excluded", label: "Excluded", count: facets.excluded }
        ]
      },
      {
        key: "source",
        label: "Source",
        kind: "single",
        options: [
          { value: "manual", label: "Manual", count: facets.source.get("manual") ?? 0 },
          {
            value: "google_sheets",
            label: "Google Sheets",
            count: facets.source.get("google_sheets") ?? 0
          }
        ]
      }
    ],
    [admissionOptions, roleOptions, requireSubscription, statusFilterOptions, facets]
  );

  const filters = useAdminFilters(filterDefs);
  const tableFilters = filters.toTableFilters();

  // With the header funnels gone the chips are the only thing a user can
  // change, but the table still calls back on a deep link, a back/forward and
  // its own "Clear filters". Routing those through `useAdminFilters` keeps ONE
  // store for filter state (the URL) instead of a controlled prop that could
  // drift from it.
  const handleTableFiltersChange = (next: AdminTableFilters) => {
    const patch: Record<string, FilterValue | null> = {};
    for (const key of COLUMN_FILTER_KEYS) {
      const nextValue = next[key] ?? [];
      const currentValue = tableFilters[key] ?? [];
      if (nextValue.join(",") === currentValue.join(",")) continue;
      patch[key] = key === "status" ? nextValue : (nextValue[0] ?? null);
    }
    if (Object.keys(patch).length > 0) filters.setMany(patch);
  };

  const admissionFilter = String(filters.values.admission ?? "");
  const roleFilter = String(filters.values.role ?? "");
  const subscriptionFilter = String(filters.values.subscription ?? "");

  // Everything but a deleted row is listed (`include_deleted: false` on the
  // query); withdrawn rows stay visible and are narrowed by the Status chip.
  const visibleRegistrations = useMemo(
    () =>
      registrations.filter((registration) => {
        if (admissionFilter && registration.admission.decision !== admissionFilter) return false;
        if (
          roleFilter &&
          !registration.roles.some((role) => role.is_active && role.role === roleFilter)
        ) {
          return false;
        }
        if (
          subscriptionFilter &&
          (registration.subscription_outcome ?? "undetermined") !== subscriptionFilter
        ) {
          return false;
        }
        return true;
      }),
    [registrations, admissionFilter, roleFilter, subscriptionFilter]
  );

  // Patch a single row across every cached filter variant. The PATCH endpoints
  // already return the fully-serialized registration, so we never need to
  // re-fetch the whole pool just to reflect one edit.
  const patchRegistrationInCache = useCallback(
    (row: AdminRegistration) => {
      queryClient.setQueriesData<AdminRegistration[]>(
        { queryKey: ["balancer-admin", "registrations", tournamentId] },
        (old) => (old ? old.map((r) => (r.id === row.id ? row : r)) : old)
      );
    },
    [queryClient, tournamentId]
  );

  const removeRegistrationFromCache = (registrationId: number) => {
    queryClient.setQueriesData<AdminRegistration[]>(
      { queryKey: ["balancer-admin", "registrations", tournamentId] },
      (old) => (old ? old.filter((r) => r.id !== registrationId) : old)
    );
  };

  // Fire-and-forget reconcile. NOT awaited, so the spinner/modal closes
  // immediately after the mutation itself resolves.
  const revalidateRegistrations = () => {
    void queryClient.invalidateQueries({
      queryKey: ["balancer-admin", "registrations", tournamentId]
    });
  };

  const createMutation = useMutation({
    mutationFn: (payload: AdminRegistrationCreateInput) =>
      balancerAdminService.createManualRegistration(tournamentId as number, payload),
    onSuccess: () => {
      setCreateOpen(false);
      notify.success("Manual registration created");
      revalidateRegistrations();
    }
  });

  const updateMutation = useMutation({
    mutationFn: (payload: AdminRegistrationUpdateInput) => {
      if (!editingRegistration) {
        throw new Error("No registration selected");
      }
      return balancerAdminService.updateRegistration(editingRegistration.id, payload);
    },
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      setEditingRegistration(null);
      notify.success("Registration updated");
      revalidateRegistrations();
    }
  });

  const approveMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.approveRegistration(registrationId),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success("Registration approved");
      revalidateRegistrations();
    }
  });

  const rejectMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.rejectRegistration(registrationId),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success("Registration rejected");
      revalidateRegistrations();
    }
  });

  const withdrawMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.withdrawRegistration(registrationId),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success("Registration withdrawn");
      revalidateRegistrations();
    }
  });

  const restoreMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.restoreRegistration(registrationId),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success("Registration restored");
      revalidateRegistrations();
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.deleteRegistration(registrationId),
    onSuccess: (_, registrationId) => {
      removeRegistrationFromCache(registrationId);
      setPendingDelete(null);
      notify.success("Registration deleted");
      revalidateRegistrations();
    }
  });

  const bulkApproveMutation = useMutation({
    mutationFn: (registrationIds: number[]) =>
      balancerAdminService.bulkApproveRegistrations(tournamentId as number, registrationIds),
    onSuccess: (result, registrationIds) => {
      notify.success(`${result.approved} approved, ${result.skipped} skipped`, {
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            // Only pending rows are selectable, so `pending` is the prior
            // status of every id in the batch.
            void Promise.all(
              registrationIds.map((id) =>
                balancerAdminService.updateRegistration(id, { status: "pending" })
              )
            )
              .then(() => {
                revalidateRegistrations();
                notify.success("Approval undone");
              })
              .catch((error: unknown) => notify.apiError(error));
          }
        }
      });
      revalidateRegistrations();
    }
  });

  const balancerInclusionMutation = useMutation({
    mutationFn: ({ registrationId, include }: { registrationId: number; include: boolean }) =>
      include
        ? balancerAdminService.includeInBalancer(registrationId)
        : balancerAdminService.setBalancerStatus(registrationId, "excluded", "manual_exclusion"),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success("Balancer status updated");
      revalidateRegistrations();
    }
  });

  const checkInMutation = useMutation({
    mutationFn: ({ registrationId, checkedIn }: { registrationId: number; checkedIn: boolean }) =>
      balancerAdminService.checkInRegistration(registrationId, checkedIn),
    onSuccess: (updated, variables) => {
      patchRegistrationInCache(updated);
      notify.success(variables.checkedIn ? "Checked in" : "Check-in removed");
      revalidateRegistrations();
    }
  });

  const bulkAddToBalancerMutation = useMutation({
    // `previouslyExcluded` travels with the call because the undo needs the
    // pre-mutation inclusion state, which the refetched rows no longer carry.
    mutationFn: ({ ids }: { ids: number[]; previouslyExcluded: number[] }) =>
      balancerAdminService.bulkAddToBalancer(tournamentId as number, ids),
    onSuccess: (result, { previouslyExcluded }) => {
      notify.success(`${result.updated} added to balancer, ${result.skipped} skipped`, {
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            void (previouslyExcluded.length > 0
              ? balancerAdminService.bulkSetBalancerStatus(tournamentId as number, {
                  registration_ids: previouslyExcluded,
                  balancer_status: "excluded",
                  exclude_reason: "manual_exclusion"
                })
              : Promise.resolve()
            )
              .then(() => {
                revalidateRegistrations();
                notify.success("Balancer change undone");
              })
              .catch((error: unknown) => notify.apiError(error));
          }
        }
      });
      revalidateRegistrations();
    }
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

  const columns: ColumnDef<AdminRegistration>[] = useMemo(() => {
    const rowActions = (registration: AdminRegistration): KebabAction[] => {
      const inBalancer = !registration.balancer_status_meta.excludes_from_balancer;
      const isWithdrawn = registration.status === "withdrawn";
      const isPending = registration.status === "pending";
      // A custom status is organizer-defined and behaves like `approved` for
      // balancer inclusion, which is why both reach the same two actions.
      const isManageable =
        registration.status === "approved" || registration.status_meta.kind === "custom";

      return [
        {
          label: "Edit",
          icon: Pencil,
          hidden: isWithdrawn,
          onSelect: () => setEditingRegistration(registration)
        },
        {
          label: "Change history",
          icon: History,
          // The row carries its own workspace, which is the scope its edits were
          // authorized against — closer to the truth than the ambient selection.
          hidden: !canAccessPermission("audit.read", registration.workspace_id),
          onSelect: () =>
            openAuditTrail({
              entityType: "registration",
              entityId: registration.id,
              workspaceId: registration.workspace_id
            })
        },
        {
          label: "Approve",
          icon: Check,
          hidden: !isPending,
          onSelect: () => approve(registration.id)
        },
        { label: "Reject", icon: X, hidden: !isPending, onSelect: () => reject(registration.id) },
        {
          label: inBalancer ? "Remove from balancer" : "Add to balancer",
          icon: inBalancer ? ShieldX : Check,
          hidden: !isManageable,
          onSelect: () =>
            setBalancerInclusion({ registrationId: registration.id, include: !inBalancer })
        },
        {
          label: registration.checked_in ? "Uncheck-in" : "Check-in",
          icon: Check,
          hidden: !isManageable,
          onSelect: () =>
            setCheckIn({ registrationId: registration.id, checkedIn: !registration.checked_in })
        },
        {
          label: "Restore",
          icon: Undo2,
          hidden: !isWithdrawn,
          onSelect: () => restore(registration.id)
        },
        {
          label: "Withdraw",
          icon: Undo2,
          hidden: isWithdrawn,
          onSelect: () => withdraw(registration.id)
        },
        {
          label: "Delete",
          icon: Trash2,
          destructive: true,
          onSelect: () => setPendingDelete(registration)
        }
      ];
    };

    return [
      ...buildBalancerRegistrationColumns(
        subroleCatalog,
        requireSubscription,
        customFields,
        statusFilterOptions,
        adminNotesEdit
      ),
      createKebabColumn<AdminRegistration>(rowActions, {
        rowLabel: (registration) =>
          registration.battle_tag ?? registration.display_name ?? `registration ${registration.id}`
      })
    ];
  }, [
    subroleCatalog,
    requireSubscription,
    customFields,
    statusFilterOptions,
    adminNotesEdit,
    approve,
    reject,
    withdraw,
    restore,
    setBalancerInclusion,
    setCheckIn,
    canAccessPermission,
    openAuditTrail
  ]);

  const groupPageRows = (
    pageRows: Row<AdminRegistration>[]
  ): AdminDataTableGroup<AdminRegistration>[] => {
    const rowsById = new Map(pageRows.map((row) => [row.original.id, row]));
    return groupRegistrations(
      pageRows.map((row) => row.original),
      groupBy
    ).map((group) => ({
      key: group.key,
      label: (
        <>
          <span className="text-foreground">{group.label}</span>
          <span className="ml-2 font-normal normal-case text-muted-foreground">
            {group.registrations.length}{" "}
            {group.registrations.length === 1 ? "registration" : "registrations"}
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

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>
          Choose a tournament in the sidebar before managing registrations.
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
        <AdminDataTable<AdminRegistration>
          rows={visibleRegistrations}
          isLoading={registrationsQuery.isFetching}
          columns={columns}
          getRowId={(registration) => String(registration.id)}
          filters={tableFilters}
          onFiltersChange={handleTableFiltersChange}
          filterKey={filters.filterKey}
          initialSort={{ field: "submitted", dir: "desc" }}
          paging="all"
          cellAlign="top"
          searchPlaceholder="Search registrations"
          emptyMessage="No registrations yet."
          columnsStorageKey="balancer-registrations-table-columns"
          enableRowSelection={(row) => row.original.status === "pending"}
          inspectorId={openId}
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          groupRows={groupBy === "none" ? undefined : groupPageRows}
          toolbar={<AdminFilterBar defs={filterDefs} filters={filters} />}
          bulkActions={(selected, clearSelection) => (
            <BulkBar count={selected.length} unit="registrations" onClear={clearSelection}>
              <Button
                size="sm"
                onClick={() => {
                  bulkApproveMutation.mutate(
                    selected.map((registration) => registration.id),
                    { onSuccess: clearSelection }
                  );
                }}
                disabled={bulkApproveMutation.isPending}
              >
                {bulkApproveMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="mr-2 h-4 w-4" aria-hidden />
                )}
                Approve {selected.length}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  bulkAddToBalancerMutation.mutate(
                    {
                      ids: selected.map((registration) => registration.id),
                      previouslyExcluded: selected
                        .filter((registration) => registration.balancer_status_meta.excludes_from_balancer)
                        .map((registration) => registration.id)
                    },
                    { onSuccess: clearSelection }
                  );
                }}
                disabled={bulkAddToBalancerMutation.isPending}
              >
                {bulkAddToBalancerMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="mr-2 h-4 w-4" aria-hidden />
                )}
                Add to Balancer {selected.length}
              </Button>
            </BulkBar>
          )}
          actions={
            <>
              <span
                className="shrink-0 text-xs tabular-nums text-muted-foreground"
                title={`${registrations.length} registrations`}
              >
                {registrations.length}
              </span>
              {pendingCount > 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0 gap-1.5 text-warning"
                  aria-pressed={isPendingFilterOn}
                  onClick={() => filters.set("status", isPendingFilterOn ? [] : ["pending"])}
                  title={
                    isPendingFilterOn
                      ? "Clear the pending filter"
                      : `Show only the ${pendingCount} pending registrations`
                  }
                >
                  <Clock className="h-3.5 w-3.5" aria-hidden />
                  {pendingCount} pending
                </Button>
              ) : null}
              <Select
                value={groupBy}
                onValueChange={(value) => setGroupBy(value as RegistrationGroupingMode)}
              >
                <SelectTrigger className="h-8 w-[160px]" aria-label="Group registrations">
                  <SelectValue placeholder="Group by" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No grouping</SelectItem>
                  <SelectItem value="check_in">Group by check-in</SelectItem>
                  <SelectItem value="balancer_status">Group by balancer</SelectItem>
                  <SelectItem value="admission">Group by admission</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
                <UserPlus className="mr-2 h-4 w-4" aria-hidden />
                Create registration
              </Button>
            </>
          }
        />
      </div>

      <AdminInspector
        openId={inspected ? openId : null}
        onClose={() => setParams({ id: null })}
        title={inspected?.battle_tag ?? inspected?.display_name ?? "Registration"}
        subtitle={
          inspected
            ? `${inspected.status} · ${ADMISSION_LABELS[inspected.admission.decision]}`
            : undefined
        }
      >
        {inspected ? (
          <RegistrationInspectorBody
            registration={inspected}
            catalog={subroleCatalog}
            customFields={customFields}
            t={t}
          />
        ) : null}
      </AdminInspector>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-3xl gap-0 overflow-hidden border-border bg-popover p-0 text-[color:var(--aqt-fg)] shadow-2xl shadow-black/50 sm:rounded-xl">
          <DialogHeader className="border-b border-[color:var(--aqt-border-2)] px-4 py-3.5 text-left sm:px-5">
            <DialogTitle className="text-xl font-semibold tracking-tight text-[color:var(--aqt-fg)]">
              Create Manual Registration
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl text-sm leading-5 text-[color:var(--aqt-fg-muted)]">
              Registers a player on your behalf: every field stays available regardless of the
              public form config, and verified-account requirements are not enforced. Link a site
              account to prefill BattleTag, Discord and Twitch from its verified logins.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 py-3.5 sm:px-5">
            <UnifiedRegistrationForm
              mode="admin"
              tournamentId={tournamentId}
              workspaceId={workspaceId as number}
              formConfig={roleForm}
              onSubmit={async (payload) => {
                await createMutation.mutateAsync(payload);
              }}
              onCancel={() => setCreateOpen(false)}
              submitPending={createMutation.isPending}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingRegistration !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditingRegistration(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl gap-0 overflow-hidden border-border bg-popover p-0 text-[color:var(--aqt-fg)] shadow-2xl shadow-black/50 sm:rounded-xl">
          <DialogHeader className="border-b border-[color:var(--aqt-border-2)] px-4 py-3.5 text-left sm:px-5">
            <DialogTitle className="text-xl font-semibold tracking-tight text-[color:var(--aqt-fg)]">
              Edit Registration
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl text-sm leading-5 text-[color:var(--aqt-fg-muted)]">
              Update balancer-facing participant data in the fixed admin editor, while keeping the
              public multi-step look and hierarchy.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] space-y-4 overflow-y-auto px-4 py-3.5 sm:px-5">
            {editingRegistration && (
              // The change history used to sit here, inside this already-scrolling
              // dialog. It now lives in the row's "Change history" action, which
              // opens the shared drawer: a Radix sheet inside a Radix dialog
              // stacks two focus traps and two scroll locks on one screen.
              <UnifiedRegistrationForm
                mode="admin"
                tournamentId={tournamentId}
                workspaceId={workspaceId as number}
                formConfig={roleForm}
                initialData={editingRegistration}
                onSubmit={async (payload) => {
                  await updateMutation.mutateAsync(payload);
                }}
                onCancel={() => setEditingRegistration(null)}
                submitPending={updateMutation.isPending}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => (open ? undefined : setPendingDelete(null))}
        intent={{
          title: "Delete this registration?",
          description: `${pendingDelete?.battle_tag ?? pendingDelete?.display_name ?? "The registration"} is removed from the pool. Withdraw instead to keep the record.`,
          confirmLabel: "Delete registration",
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

/** Everything about one row that the table has no column for. */
function RegistrationInspectorBody({
  registration,
  catalog,
  customFields,
  t
}: Readonly<{
  registration: AdminRegistration;
  catalog?: SubroleCatalog;
  customFields: RegistrationForm["custom_fields"];
  t: AdmissionTranslator;
}>) {
  const answers = customFields.filter(
    (field) => (registration.custom_fields_json?.[field.key] ?? null) !== null
  );
  const blockers = registration.admission.blockers.flatMap(
    (requirement) => requirement.reasons
  );

  return (
    <div className="space-y-5 text-sm">
      <section className="space-y-1.5">
        <h3 className={EYEBROW_CLASS}>Admission</h3>
        <p className="text-foreground">{ADMISSION_LABELS[registration.admission.decision]}</p>
        {blockers.length > 0 ? (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {blockers.map((reason) => (
              <li key={`${reason.code}-${reason.actor}`}>{formatAdmissionReason(t, reason)}</li>
            ))}
          </ul>
        ) : null}
        {registration.subscription_outcome ? (
          <p className="text-xs text-muted-foreground">
            Subscription: {SUBSCRIPTION_LABELS[registration.subscription_outcome]}
          </p>
        ) : null}
      </section>

      <section className="space-y-1.5">
        <h3 className={EYEBROW_CLASS}>Declared roles</h3>
        <RolesCell roles={registration.roles} catalog={catalog} />
      </section>

      {answers.length > 0 ? (
        <section className="space-y-1.5">
          <h3 className={EYEBROW_CLASS}>Questionnaire</h3>
          <dl className="space-y-2 text-xs">
            {answers.map((field) => (
              <div key={field.key}>
                <dt className="text-muted-foreground">{field.label}</dt>
                <dd className="mt-0.5 text-foreground">
                  {renderCustomFieldValue(field, registration.custom_fields_json?.[field.key])}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <section className="space-y-1.5">
        <h3 className={EYEBROW_CLASS}>Details</h3>
        <dl className="space-y-2 text-xs text-muted-foreground">
          {(registration.smurf_tags_json?.length ?? 0) > 0 ? (
            <div className="flex justify-between gap-3">
              <dt>Smurfs</dt>
              <dd className="text-right">{registration.smurf_tags_json?.join(", ")}</dd>
            </div>
          ) : null}
          {registration.discord_nick || registration.twitch_nick || registration.boosty_nick ? (
            <div className="flex justify-between gap-3">
              <dt>Contact</dt>
              <dd className="text-right">
                {[registration.discord_nick, registration.twitch_nick, registration.boosty_nick]
                  .filter(Boolean)
                  .join(" · ")}
              </dd>
            </div>
          ) : null}
          <div className="flex justify-between gap-3">
            <dt>Source</dt>
            <dd className="text-right">{registration.source}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Submitted</dt>
            <dd className="text-right">{formatSubmittedAt(registration.submitted_at)}</dd>
          </div>
          {registration.reviewed_at ? (
            <div className="flex justify-between gap-3">
              <dt>Reviewed</dt>
              <dd className="text-right">
                {formatSubmittedAt(registration.reviewed_at)}
                {registration.reviewed_by_username ? ` · ${registration.reviewed_by_username}` : ""}
              </dd>
            </div>
          ) : null}
          {registration.notes ? (
            <div>
              <dt>Notes</dt>
              <dd className="mt-0.5">{registration.notes}</dd>
            </div>
          ) : null}
          {registration.admin_notes ? (
            <div>
              <dt>Admin notes</dt>
              <dd className="mt-0.5">{registration.admin_notes}</dd>
            </div>
          ) : null}
        </dl>
      </section>

      {/* The chart itself lives on the person: a 380px panel is the wrong
          canvas for a time series, and the person page already draws it. */}
      {registration.user_id != null ? (
        <Button asChild variant="outline" size="sm" className="w-fit">
          <Link href={`/admin/people/${registration.user_id}`}>
            Open rank history
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </Button>
      ) : null}
    </div>
  );
}
