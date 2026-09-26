"use client";

import type { ColumnDef, Row } from "@tanstack/react-table";

import { adminColumnMeta } from "@/components/data-table";
import { InlineEditText } from "@/components/kit/InlineEditText";
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
  primaryAdmissionReason,
} from "@/lib/registration/admission";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";
import type { FormField } from "@/types/forms.types";
import { AnswerValue } from "@/components/forms/AnswerValue";
import { answerSearchText } from "@/lib/forms/answers";
import { identityProvider } from "@/lib/forms/builtin-keys";

import {
  AdmissionReasonCell,
  BUILTIN_ANSWER_LABELS,
  DEFAULT_VISIBLE_ANSWER_KEYS,
  ExclusionCell,
  ParticipantCell,
  ReserveBadge,
  ReviewedCell,
  RolesCell,
  SourceCell,
  SubmittedCell,
  TextBlockCell,
  identityHandles,
  localeTextSort,
  parseValidDate,
} from "./registrationColumnCells";


export function buildBalancerRegistrationColumns(
  subroleCatalog?: SubroleCatalog,
  /** Gates the presence of the Subscription chip column only. Admission itself
   *  is read off each row, so the old `requireOpenProfile` twin of this flag is
   *  gone: nothing outside that column needed either of them. */
  requireSubscription = false,
  /** Every question the tournament's CURRENT schema asks. `battle_tag` and
   *  `roles` are dropped here — they keep their own columns — and the rest
   *  become one column each. A row filed against an OLDER version still renders
   *  in these columns (its answers are read by key); an answer whose question
   *  the current schema no longer asks has no column to live in and is shown in
   *  the row's inspector instead, under its stale-version notice. */
  fields: FormField[] = [],
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

  const answerFields = fields.filter(
    (field) => field.key !== "battle_tag" && field.key !== "roles",
  );
  const identityKeys = answerFields
    .map((field) => field.key)
    .filter((key) => identityProvider(key) !== null);

  // One column per question, all reading the same flat `answers` document
  // through the same renderer — the organizer-defined ones and the builtins
  // alike, since a schema knows no difference between them.
  const answerColumns: ColumnDef<AdminRegistration>[] = answerFields.map((field) => ({
    id: `answer_${field.key}`,
    header: field.label || BUILTIN_ANSWER_LABELS[field.key] || field.key,
    // Free-form answers: the old client-side sort had no case for them either.
    enableSorting: false,
    cell: ({ row }) => (
      <AnswerValue value={row.original.answers?.[field.key] ?? null} kind={field.kind} />
    ),
    meta: adminColumnMeta<AdminRegistration>({
      category: "admin",
      defaultHidden: DEFAULT_VISIBLE_ANSWER_KEYS[field.key] !== true,
      responsive: "lg",
      className: "min-w-[180px]",
      searchValue: (registration) => answerSearchText(registration.answers?.[field.key]),
    }),
  }));

  return [
    {
      id: "participant",
      header: "Participant",
      accessorFn: (registration) => registration.battle_tag || registration.display_name || "",
      sortingFn: localeTextSort,
      cell: ({ row }) => <ParticipantCell registration={row.original} identityKeys={identityKeys} />,
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
            ...identityHandles(registration, identityKeys),
            registration.source_record_key,
          ]
            .filter(Boolean)
            .join(" "),
      }),
    },
    ...answerColumns,
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
        // Fits three role chips (32px each + gaps) plus cell padding on one
        // line. Without a floor the column shrinks to one chip — flex-wrap
        // then stacks the roles and the whole row grows to ~200px tall.
        className: "min-w-[136px]",
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
      // Two axes on ONE chip, deliberately: `included`/`excluded` is the pool
      // verdict, `reserve`/`not_reserve` is the registrant's own "you can call
      // me in". They are independent — a player who offered is in the pool like
      // anybody else — so the offer must not be answerable by the pool clause.
      filterFn: (row: Row<AdminRegistration>, _columnId: string, values: string[]) => {
        const [value] = values;
        if (!value) {
          return true;
        }

        if (value === "reserve" || value === "not_reserve") {
          return (row.original.answers?.reserve === true) === (value === "reserve");
        }

        const isExcluded = row.original.balancer_status_meta?.excludes_from_balancer === true;
        return value === "excluded" ? isExcluded : !isExcluded;
      },
      cell: ({ row }) => (
        <div className="flex flex-col items-center gap-1">
          <BalancerStatusBadge
            status={row.original.balancer_status}
            meta={row.original.balancer_status_meta}
          />
          {row.original.answers?.reserve === true ? <ReserveBadge /> : null}
        </div>
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
            { value: "reserve", label: "On call" },
            { value: "not_reserve", label: "Not on call" },
          ],
        },
        searchValue: (registration) =>
          `${registration.balancer_status}${registration.answers?.reserve === true ? " reserve" : ""}`,
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
  ];
}
