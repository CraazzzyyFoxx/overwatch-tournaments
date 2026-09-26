"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import type { AdminTableFilters } from "@/components/data-table";
import {
  useFilters,
  type FilterDef,
  type FilterState,
  type FilterValue
} from "@/components/kit/useFilters";
import { ROLE_LABELS } from "@/lib/roster/roles";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { AdmissionDecision } from "@/types/registration.types";

import {
  ADMISSION_LABELS,
  COLUMN_FILTER_KEYS,
  SUBSCRIPTION_LABELS,
  buildRegistrationFacets,
  filterRegistrations
} from "../registrationsTable.model";

interface UseRegistrationFiltersInput {
  registrations: AdminRegistration[];
  /** Gates the Subscription chip only; admission travels on each row. */
  requireSubscription: boolean;
  statusFilterOptions: { value: string; label: string }[];
}

interface RegistrationFilters {
  defs: FilterDef[];
  filters: FilterState;
  /** The subset the `AdminDataTable` resolves as column filters. */
  tableFilters: AdminTableFilters;
  onTableFiltersChange: (next: AdminTableFilters) => void;
  /** Rows left after the chips the table cannot resolve itself. */
  visibleRegistrations: AdminRegistration[];
}

/**
 * The chip bar and the two halves of the narrowing it drives, both reading the
 * same URL-backed store.
 */
export function useRegistrationFilters({
  registrations,
  requireSubscription,
  statusFilterOptions
}: UseRegistrationFiltersInput): RegistrationFilters {
  // The only translated strings on this screen: reason codes are shared with the
  // public participants page, so they live in the message catalogue rather than
  // as English literals like the rest of this admin table.
  const t = useTranslations();

  const facets = useMemo(() => buildRegistrationFacets(registrations), [registrations]);

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

  const defs: FilterDef[] = useMemo(
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
          { value: "excluded", label: "Excluded", count: facets.excluded },
          // A second axis on the same chip: the pool verdict says whether the
          // row is in the balancer, this says whether the registrant offered to
          // be called in. They go through the message catalogue because the
          // organizer reads them as words, not as key paths.
          { value: "reserve", label: t("common.reserve"), count: facets.reserve },
          { value: "not_reserve", label: t("common.notReserve"), count: facets.notReserve }
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
    [admissionOptions, roleOptions, requireSubscription, statusFilterOptions, facets, t]
  );

  const filters = useFilters(defs);
  const tableFilters = filters.toTableFilters();

  // With the header funnels gone the chips are the only thing a user can
  // change, but the table still calls back on a deep link, a back/forward and
  // its own "Clear filters". Routing those through `useFilters` keeps ONE
  // store for filter state (the URL) instead of a controlled prop that could
  // drift from it.
  const onTableFiltersChange = (next: AdminTableFilters) => {
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

  const visibleRegistrations = useMemo(
    () => filterRegistrations(registrations, admissionFilter, roleFilter, subscriptionFilter),
    [registrations, admissionFilter, roleFilter, subscriptionFilter]
  );

  return { defs, filters, tableFilters, onTableFiltersChange, visibleRegistrations };
}
