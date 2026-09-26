import type { DateFormatter } from "@/components/kit/format-time";
import type { AdmissionDecision, RegistrationForm } from "@/types/registration.types";
import type { AdminRegistration } from "@/types/balancer-admin.types";

// Minimal fallback used only until the real registration form loads. Its schema
// is EMPTY on purpose: the questions this tournament asks are the ones the
// server sends, and inventing a plausible set here would render a form nobody
// configured. The sub-role catalog rides along on the same query.
export const ADMIN_ROLE_FORM: RegistrationForm = {
  id: 0,
  tournament_id: 0,
  workspace_id: 0,
  is_open: true,
  form_schema: { schema_version: 1, sections: [] },
  version_id: 0,
  version_number: 0
};

export const ADMISSION_LABELS: Record<AdmissionDecision, string> = {
  admitted: "Admitted",
  pending_check_in: "Check-in pending",
  not_admitted: "Not admitted"
};

export const SUBSCRIPTION_LABELS = {
  satisfied: "Satisfied",
  refused: "Refused",
  undetermined: "Undetermined"
} as const;

/**
 * Chip keys the TABLE resolves, because a column declares them as a header
 * filter (`meta.filter`) — which in client mode is how a URL param is mapped
 * onto the column whose values it matches. The remaining chips narrow the row
 * list instead: "which role" is not a column value to match against. Both
 * halves read the same URL-backed `useFilters` store, so there is still exactly
 * one place a filter lives.
 */
export const COLUMN_FILTER_KEYS = ["status", "inclusion", "source"] as const;

export function formatSubmittedAt(
  format: DateFormatter,
  value: string | null | undefined
): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "-"
    : format.dateTime(date, { dateStyle: "medium", timeStyle: "short" });
}

/** Every facet count the chip bar shows, each one counted exactly the way its
 *  own filter narrows the pool. */
export interface RegistrationFacets {
  role: Map<string, number>;
  status: Map<string, number>;
  subscription: Map<string, number>;
  source: Map<string, number>;
  included: number;
  excluded: number;
  reserve: number;
  notReserve: number;
}

/**
 * Options are read off the pool rather than hard-coded: a workspace's roles are
 * configuration, and a chip offering a value no row has is a dead end. One pass
 * counts every facet, so the chip counts cannot disagree with the result.
 *
 * No Division facet: `AdminRegistrationRole` carries a rank, not a division,
 * and turning one into the other needs the workspace division grid — a query
 * the hub deliberately does not run on every page load.
 */
export function buildRegistrationFacets(
  registrations: readonly AdminRegistration[]
): RegistrationFacets {
  const role = new Map<string, number>();
  const status = new Map<string, number>();
  const subscription = new Map<string, number>();
  const source = new Map<string, number>();
  let included = 0;
  let reserve = 0;
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
    // Consent, not pool membership: a reserve is counted on its own axis so the
    // chip can answer "who agreed to sub in" without the pool verdict blurring it.
    if (registration.answers?.reserve === true) reserve += 1;
  }
  return {
    role,
    status,
    subscription,
    source,
    included,
    excluded: registrations.length - included,
    reserve,
    notReserve: registrations.length - reserve
  };
}

/**
 * The chips the table cannot resolve as column filters. Everything but a
 * deleted row is listed (`include_deleted: false` on the query); withdrawn rows
 * stay visible and are narrowed by the Status chip instead.
 */
export function filterRegistrations(
  registrations: readonly AdminRegistration[],
  admissionFilter: string,
  roleFilter: string,
  subscriptionFilter: string
): AdminRegistration[] {
  return registrations.filter((registration) => {
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
  });
}
