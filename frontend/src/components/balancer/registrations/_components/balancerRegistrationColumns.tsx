"use client";

import type { ColumnDef, Row, SortingFn } from "@tanstack/react-table";
import { useFormatter, useTranslations, type DateTimeFormatOptions } from "next-intl";

import { adminColumnMeta } from "@/components/admin-data-table";
import { InlineEditText } from "@/components/admin/InlineEditText";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { TONE_CLASS, TONE_TEXT } from "@/components/admin/tone";
import { Badge } from "@/components/ui/badge";
import {
  AdmissionStatusBadge,
  SubscriptionStatusBadge,
  BalancerStatusBadge,
  CheckInStatusBadge,
  ProfileStatusBadge,
  RegistrationStatusBadge,
} from "@/components/status/RegistrationBadges";
import {
  ADMISSION_ORDER,
  ADMISSION_SEARCH_TEXT,
  formatAdmissionReason,
  primaryAdmissionReason,
} from "@/lib/admission";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, getRoleIconName, getSubroleLabel } from "@/lib/roles";
import type {
  AdminRegistration,
  AdminRegistrationRole,
} from "@/types/balancer-admin.types";
import type { CustomFieldDefinition, SubroleCatalog } from "@/types/registration.types";
import { renderCustomFieldValue } from "@/components/registration/customFieldValue";

/**
 * The slice of next-intl's formatter the timestamp cells need. These helpers are
 * plain functions, so they cannot call `useFormatter()` themselves — and an
 * `en-GB` literal here printed English dates into the `ru` default UI. The cell
 * components below supply the formatter instead.
 */
interface DateFormatter {
  dateTime: (value: Date, options?: DateTimeFormatOptions) => string;
}

/**
 * Locale-aware compare shared by every text column. Sorting used to live in one
 * `switch` in the table; the options here are the ones that switch used, so the
 * order organizers are used to does not change.
 */
const localeTextSort: SortingFn<AdminRegistration> = (rowA, rowB, columnId) =>
  String(rowA.getValue(columnId) ?? "").localeCompare(
    String(rowB.getValue(columnId) ?? ""),
    undefined,
    { sensitivity: "base", numeric: true },
  );

function parseValidDate(dateString: string | null | undefined): Date | null {
  if (!dateString) {
    return null;
  }

  const date = new Date(dateString);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTimestamp(format: DateFormatter, dateString: string | null | undefined): string | null {
  const date = parseValidDate(dateString);
  if (!date) {
    return null;
  }

  return format.dateTime(date, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatFullTimestamp(format: DateFormatter, dateString: string | null | undefined): string | null {
  const date = parseValidDate(dateString);
  if (!date) {
    return null;
  }

  return format.dateTime(date, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ParticipantCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  const primary =
    registration.battle_tag ??
    registration.display_name ??
    `Registration #${registration.id}`;

  const secondaryParts = [
    registration.battle_tag && registration.display_name && registration.display_name !== registration.battle_tag
      ? registration.display_name
      : null,
    registration.discord_nick,
    registration.twitch_nick,
    registration.boosty_nick,
    registration.source_record_key,
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-1">
      <div className="truncate font-medium text-[color:var(--aqt-fg)]" title={primary}>
        {primary}
      </div>
      <div
        className="truncate text-xs text-[color:var(--aqt-fg-dim)]"
        title={secondaryParts.length > 0 ? secondaryParts.join(" · ") : undefined}
      >
        {secondaryParts.length > 0
          ? secondaryParts.join(" · ")
          : registration.source === "google_sheets"
            ? "Google Sheets import"
            : "Manual registration"}
      </div>
    </div>
  );
}

function RolesCell({
  roles,
  catalog,
}: Readonly<{
  roles: AdminRegistrationRole[];
  catalog?: SubroleCatalog;
}>) {
  if (!roles || roles.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const sortedRoles = roles
    .filter((role) => role.is_active)
    .slice()
    .sort((left, right) => left.priority - right.priority);

  if (sortedRoles.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  return (
    <div className="flex flex-wrap items-start justify-center gap-x-1 gap-y-2">
      {sortedRoles.map((role) => {
        const subroleLabel = role.subrole ? getSubroleLabel(catalog, role.role, role.subrole) : null;
        return (
          <div
            key={`${role.role}-${role.subrole ?? "base"}-${role.priority}`}
            className="inline-flex min-w-8 flex-col items-center gap-0.5"
            title={[
              ROLE_LABELS[role.role] ?? role.role,
              subroleLabel,
              role.rank_value != null ? `${role.rank_value}` : null,
              role.is_primary ? "Primary" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          >
            <span
              className={cn(
                "relative inline-flex h-8 w-8 items-center justify-center p-1",
                role.is_primary
                  ? "after:absolute after:bottom-0 after:left-1/2 after:h-0.5 after:w-4 after:-translate-x-1/2 after:rounded-full after:bg-emerald-300/90"
                  : "text-[color:var(--aqt-fg-muted)]",
              )}
            >
              <PlayerRoleIcon role={getRoleIconName(role.role)} size={20} />
            </span>
            <span className="text-center text-label font-semibold uppercase leading-none tracking-label text-[color:var(--aqt-fg-dim)]">
              {subroleLabel ?? role.rank_value ?? ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SourceCell({ source }: Readonly<{ source: AdminRegistration["source"] }>) {
  const isSheets = source === "google_sheets";
  return (
    <Badge
      variant="outline"
      className={cn("font-medium", isSheets ? TONE_CLASS.info : TONE_CLASS.neutral)}
    >
      {isSheets ? "Sheets" : "Manual"}
    </Badge>
  );
}

function CompactListCell({ values }: Readonly<{ values: string[] }>) {
  if (values.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const visibleValues = values.slice(0, 2);
  const hiddenCount = values.length - visibleValues.length;

  return (
    <div className="max-w-[220px] space-y-1">
      {visibleValues.map((value, index) => (
        <div key={`${value}-${index}`} className="truncate text-xs text-[color:var(--aqt-fg-muted)]" title={value}>
          {value}
        </div>
      ))}
      {hiddenCount > 0 ? (
        <div className={cn("text-xs font-medium", TONE_TEXT.success)}>
          +{hiddenCount} more
        </div>
      ) : null}
    </div>
  );
}

function TextBlockCell({ value }: Readonly<{ value: string | null | undefined }>) {
  if (!value) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  return (
    <span className="block max-w-[240px] truncate text-xs text-[color:var(--aqt-fg-muted)]" title={value}>
      {value}
    </span>
  );
}



function SubmittedCell({ submittedAt }: Readonly<{ submittedAt: string | null }>) {
  const format = useFormatter();
  const shortValue = formatTimestamp(format, submittedAt);
  const fullValue = formatFullTimestamp(format, submittedAt);

  return (
    <span title={fullValue ?? undefined} className="whitespace-nowrap text-xs tabular-nums text-[color:var(--aqt-fg-muted)]">
      {shortValue ?? "—"}
    </span>
  );
}

function ReviewedCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  const format = useFormatter();
  const reviewedAt = formatTimestamp(format, registration.reviewed_at);
  if (!reviewedAt && !registration.reviewed_by_username) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const summary = [registration.reviewed_by_username, reviewedAt].filter(Boolean).join(" · ");
  return (
    <span className="block max-w-[220px] truncate text-xs text-[color:var(--aqt-fg-muted)]" title={summary}>
      {summary}
    </span>
  );
}

function ExclusionCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  if (registration.balancer_status !== "excluded") {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const reason = registration.exclude_reason ?? "Excluded";
  return (
    <StatusPill tone="warning" className="max-w-[220px]" title={reason}>
      <span className="truncate">{reason}</span>
    </StatusPill>
  );
}

/**
 * The reason behind one row's admission verdict.
 *
 * Amber for a blocker, muted for a requirement that is merely failing open — the
 * second is not keeping anybody out today, but it will keep doing so silently
 * until somebody looks, so it must be visible without reading as a refusal.
 */
function AdmissionReasonCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  const t = useTranslations();
  const reason = primaryAdmissionReason(registration.admission);
  if (!reason) {
    return <span className="text-[color:var(--aqt-fg-faint)]">—</span>;
  }

  const text = formatAdmissionReason(t, reason);
  const isBlocking = registration.admission.blockers.length > 0;
  return (
    <span
      className={cn(
        "block max-w-[240px] truncate text-xs",
        isBlocking ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-fg-dim)]",
      )}
      title={text}
    >
      {text}
    </span>
  );
}

export function buildBalancerRegistrationColumns(
  subroleCatalog?: SubroleCatalog,
  /** Gates the presence of the Subscription chip column only. Admission itself
   *  is read off each row, so the old `requireOpenProfile` twin of this flag is
   *  gone: nothing outside that column needed either of them. */
  requireSubscription = false,
  customFields: CustomFieldDefinition[] = [],
  /** Values offered by the `status` header filter, as the endpoint reports them. */
  statusOptions: readonly { value: string; label: string }[] = [],
  /** Inline editing of the Admin Notes cell. Omitted, that column stays read-only;
   *  `canEdit` lives with the caller because it owns the row's edit permission. */
  adminNotesEdit?: {
    save: (registration: AdminRegistration, next: string) => Promise<unknown>;
    canEdit: (registration: AdminRegistration) => boolean;
  },
): ColumnDef<AdminRegistration>[] {
  // Built apart from the list below only to keep its old place between check-in
  // and admission instead of being appended after the admin columns.
  const subscriptionColumns: ColumnDef<AdminRegistration>[] = requireSubscription
    ? [
        {
          // ONE column with the COMPOSED outcome. One column per provider would
          // not scale, and under `any` mode a red provider cell next to a green
          // one reads as a failure when it is not.
          id: "subscription",
          header: "Subscription",
          // The old client-side sort had no case for this column.
          enableSorting: false,
          cell: ({ row }) => <SubscriptionStatusBadge outcome={row.original.subscription_outcome} />,
          meta: adminColumnMeta<AdminRegistration>({
            category: "meta",
            defaultHidden: false,
            responsive: "md",
            align: "center",
            searchValue: (registration) => registration.subscription_outcome ?? "unknown",
          }),
        },
      ]
    : [];

  // One column per organizer-defined field, same definitions the public
  // roster renders. Off by default: a form may define a dozen of them.
  const customFieldColumns: ColumnDef<AdminRegistration>[] = customFields.map((field) => ({
    id: `custom_${field.key}`,
    header: field.label,
    // Free-form answers: the old client-side sort had no case for them either.
    enableSorting: false,
    cell: ({ row }) =>
      renderCustomFieldValue(field, row.original.custom_fields_json?.[field.key] ?? null),
    meta: adminColumnMeta<AdminRegistration>({
      category: "admin",
      defaultHidden: true,
      responsive: "lg",
      searchValue: (registration) => {
        const value = registration.custom_fields_json?.[field.key];
        return value == null || value === "" ? null : String(value);
      },
    }),
  }));

  return [
    {
      id: "participant",
      header: "Participant",
      accessorFn: (registration) => registration.battle_tag || registration.display_name || "",
      sortingFn: localeTextSort,
      cell: ({ row }) => <ParticipantCell registration={row.original} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "core",
        defaultHidden: false,
        responsive: "always",
        sticky: true,
        className: "min-w-[240px]",
        searchValue: (registration) =>
          [
            registration.battle_tag,
            registration.display_name,
            registration.discord_nick,
            registration.twitch_nick,
            registration.boosty_nick,
            registration.source_record_key,
          ]
            .filter(Boolean)
            .join(" "),
      }),
    },
    {
      id: "smurfs",
      header: "Smurfs",
      accessorFn: (registration) => (registration.smurf_tags_json || []).join(" "),
      sortingFn: localeTextSort,
      cell: ({ row }) => <CompactListCell values={row.original.smurf_tags_json ?? []} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "admin",
        defaultHidden: false,
        responsive: "md",
        className: "min-w-[180px]",
        searchValue: (registration) => registration.smurf_tags_json.join(" "),
      }),
    },
    {
      id: "roles",
      header: "Roles",
      // Highest playable rank, so the strongest players sort together regardless
      // of which role they filled. Taken from the server's `best_rank` — maxing
      // the roles here computed the same number a second time, which is the one
      // way it could ever disagree with the engine.
      accessorFn: (registration) => registration.best_rank ?? 0,
      cell: ({ row }) => <RolesCell roles={row.original.roles} catalog={subroleCatalog} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "core",
        defaultHidden: false,
        responsive: "always",
        align: "center",
        searchValue: (registration) =>
          registration.roles
            .map((role) => [role.role, role.subrole, role.rank_value].filter(Boolean).join(" "))
            .join(" "),
      }),
    },
    {
      id: "status",
      header: "Status",
      accessorFn: (registration) => registration.status || "",
      sortingFn: localeTextSort,
      filterFn: (row: Row<AdminRegistration>, _columnId: string, values: string[]) =>
        values.length === 0 || values.includes(row.original.status),
      cell: ({ row }) => (
        <RegistrationStatusBadge status={row.original.status} meta={row.original.status_meta} />
      ),
      meta: adminColumnMeta<AdminRegistration>({
        category: "core",
        defaultHidden: false,
        responsive: "always",
        align: "center",
        filter: {
          param: "status",
          mode: "multi",
          options: statusOptions,
        },
        searchValue: (registration) => registration.status,
      }),
    },
    {
      id: "balancer",
      header: "Balancer",
      accessorFn: (registration) => registration.balancer_status || "",
      sortingFn: localeTextSort,
      // `excluded` keeps what the balancer drops, `included` keeps the pool.
      filterFn: (row: Row<AdminRegistration>, _columnId: string, values: string[]) => {
        if (values.length === 0) {
          return true;
        }

        const isExcluded = row.original.balancer_status_meta?.excludes_from_balancer === true;
        return values.includes("excluded") ? isExcluded : !isExcluded;
      },
      cell: ({ row }) => (
        <BalancerStatusBadge
          status={row.original.balancer_status}
          meta={row.original.balancer_status_meta}
        />
      ),
      meta: adminColumnMeta<AdminRegistration>({
        category: "core",
        defaultHidden: false,
        responsive: "always",
        align: "center",
        filter: {
          param: "inclusion",
          mode: "single",
          options: [
            { value: "included", label: "Included" },
            { value: "excluded", label: "Excluded" },
          ],
        },
        searchValue: (registration) => registration.balancer_status,
      }),
    },
    {
      id: "checkin",
      header: "Check-in",
      accessorFn: (registration) => (registration.checked_in ? 1 : 0),
      cell: ({ row }) => <CheckInStatusBadge checkedIn={row.original.checked_in} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "core",
        defaultHidden: false,
        responsive: "always",
        align: "center",
        searchValue: (registration) => (registration.checked_in ? "checked in" : "not checked in"),
      }),
    },
    ...subscriptionColumns,
    {
      id: "admission",
      header: "Admission",
      // D6: the sort is now projected from the same `decision` the cell renders.
      // The accessor this replaced was deliberately blind to the subscription
      // condition its own cell showed, so the column could order a refused
      // subscriber above an admitted one. That divergence existed only because
      // there was no single source of truth; ordering saved views change, and
      // that is the accepted cost of a column whose sort matches its contents.
      accessorFn: (registration) => ADMISSION_ORDER[registration.admission.decision],
      cell: ({ row }) => <AdmissionStatusBadge admission={row.original.admission} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "meta",
        defaultHidden: false,
        responsive: "md",
        align: "center",
        searchValue: (registration) =>
          ADMISSION_SEARCH_TEXT[registration.admission.decision],
      }),
    },
    {
      // Why a row is not admitted, or why it is only failing open. The organizer
      // used to have to open the OW-Profile and Subscriptions screens one row at
      // a time to learn this, because the badge showed that something was wrong
      // and never what.
      id: "reason",
      header: "Reason",
      accessorFn: (registration) =>
        primaryAdmissionReason(registration.admission)?.code ?? "",
      sortingFn: localeTextSort,
      cell: ({ row }) => <AdmissionReasonCell registration={row.original} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "meta",
        defaultHidden: false,
        responsive: "lg",
        className: "min-w-[180px]",
        searchValue: (registration) =>
          primaryAdmissionReason(registration.admission)?.code ?? null,
      }),
    },
    {
      // The raw `profiles_open` SIGNAL, not the decision. The comparisons here
      // and in `searchValue` below are a tri-state chip projection — open /
      // closed / not checked — and must not be consolidated with the admission
      // column above: whether the player is in comes from `admission.decision`
      // and nowhere else, and a closed profile an organizer has already checked
      // the player in past is still an admitted row.
      id: "profile",
      header: "Profile",
      accessorFn: (registration) =>
        registration.profiles_open === true ? 2 : registration.profiles_open === false ? 1 : 0,
      cell: ({ row }) =>
        row.original.profiles_open != null ? (
          <ProfileStatusBadge profilesOpen={row.original.profiles_open} />
        ) : (
          <span className="text-[color:var(--aqt-fg-faint)]">—</span>
        ),
      meta: adminColumnMeta<AdminRegistration>({
        category: "meta",
        defaultHidden: true,
        responsive: "lg",
        align: "center",
        searchValue: (registration) =>
          registration.profiles_open === false
            ? "profile closed"
            : registration.profiles_open === true
              ? "profile open"
              : "",
      }),
    },
    {
      id: "submitted",
      header: "Submitted",
      accessorFn: (registration) => parseValidDate(registration.submitted_at)?.getTime() ?? 0,
      cell: ({ row }) => <SubmittedCell submittedAt={row.original.submitted_at} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "meta",
        defaultHidden: false,
        responsive: "md",
        searchValue: (registration) => registration.submitted_at,
      }),
    },
    {
      id: "source",
      header: "Source",
      accessorFn: (registration) => registration.source || "",
      sortingFn: localeTextSort,
      filterFn: (row: Row<AdminRegistration>, _columnId: string, values: string[]) =>
        values.length === 0 || values.includes(row.original.source),
      cell: ({ row }) => <SourceCell source={row.original.source} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "admin",
        defaultHidden: true,
        responsive: "md",
        filter: {
          param: "source",
          mode: "single",
          options: [
            { value: "manual", label: "Manual" },
            { value: "google_sheets", label: "Google Sheets" },
          ],
        },
        searchValue: (registration) =>
          `${registration.source} ${registration.source_record_key ?? ""}`.trim(),
      }),
    },
    {
      id: "notes",
      header: "Notes",
      accessorFn: (registration) => registration.notes || "",
      sortingFn: localeTextSort,
      cell: ({ row }) => <TextBlockCell value={row.original.notes} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "admin",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[220px]",
        searchValue: (registration) => registration.notes,
      }),
    },
    {
      id: "admin_notes",
      header: "Admin Notes",
      accessorFn: (registration) => registration.admin_notes || "",
      sortingFn: localeTextSort,
      cell: ({ row }) =>
        adminNotesEdit ? (
          <InlineEditText
            value={row.original.admin_notes ?? ""}
            label="Admin notes"
            canEdit={adminNotesEdit.canEdit(row.original)}
            onSave={(next) => adminNotesEdit.save(row.original, next)}
          />
        ) : (
          <TextBlockCell value={row.original.admin_notes} />
        ),
      meta: adminColumnMeta<AdminRegistration>({
        category: "admin",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[220px]",
        searchValue: (registration) => registration.admin_notes,
      }),
    },
    {
      id: "reviewed",
      header: "Reviewed",
      accessorFn: (registration) => parseValidDate(registration.reviewed_at)?.getTime() ?? 0,
      cell: ({ row }) => <ReviewedCell registration={row.original} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "admin",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[180px]",
        searchValue: (registration) =>
          [registration.reviewed_by_username, registration.reviewed_at].filter(Boolean).join(" "),
      }),
    },
    {
      id: "excluded",
      header: "Exclusion",
      accessorFn: (registration) => (registration.balancer_status === "excluded" ? 1 : 0),
      cell: ({ row }) => <ExclusionCell registration={row.original} />,
      meta: adminColumnMeta<AdminRegistration>({
        category: "admin",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[180px]",
        searchValue: (registration) =>
          registration.balancer_status === "excluded"
            ? [registration.exclude_reason, "excluded from balancer"].filter(Boolean).join(" ")
            : null,
      }),
    },
    ...customFieldColumns,
  ];
}
