"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { AnswerValue } from "@/components/forms/AnswerValue";
import { BUILTIN_ANSWER_LABELS } from "@/components/balancer/registrations/_components/registrationColumnCells";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import { formatAdmissionReason, type AdmissionTranslator } from "@/lib/registration/admission";
import { ROLE_LABELS, getSubroleLabel } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { FormField } from "@/types/forms.types";
import type { SubroleCatalog } from "@/types/registration.types";

import {
  ADMISSION_LABELS,
  SUBSCRIPTION_LABELS,
  formatSubmittedAt
} from "../registrationsTable.model";

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

/** Everything about one row that the table has no column for. */
export default function RegistrationInspectorBody({
  registration,
  catalog,
  schemaFields,
  schemaKnown,
  t
}: Readonly<{
  registration: AdminRegistration;
  catalog?: SubroleCatalog;
  schemaFields: FormField[];
  /** Whether the tournament's schema has actually been read. While it has not,
   *  no answer may be called dropped — there is nothing to have dropped it. */
  schemaKnown: boolean;
  t: AdmissionTranslator;
}>) {
  const format = useFormatter();
  // Answered questions of the CURRENT schema, then whatever the row still
  // carries that the current schema no longer asks. The second list is the
  // whole reason a stale registration is readable at all: its answers were
  // filed against an older version, and the table has no column for a question
  // that version asked and this one does not.
  const asked = schemaFields.filter(
    (field) =>
      field.key !== "battle_tag" &&
      field.key !== "roles" &&
      (registration.answers?.[field.key] ?? null) !== null
  );
  const askedKeys: Record<string, true> = Object.fromEntries(
    schemaFields.map((field) => [field.key, true] as const)
  );
  const orphaned = Object.entries(registration.answers ?? {}).filter(
    ([key, value]) =>
      askedKeys[key] !== true &&
      key !== "battle_tag" &&
      key !== "roles" &&
      (value ?? null) !== null
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

      {asked.length > 0 || orphaned.length > 0 ? (
        <section className="space-y-1.5">
          <h3 className={EYEBROW_CLASS}>Questionnaire</h3>
          <dl className="space-y-2 text-xs">
            {asked.map((field) => (
              <div key={field.key}>
                <dt className="text-muted-foreground">
                  {field.label || BUILTIN_ANSWER_LABELS[field.key] || field.key}
                </dt>
                <dd className="mt-0.5 text-foreground">
                  <AnswerValue value={registration.answers?.[field.key]} kind={field.kind} />
                </dd>
              </div>
            ))}
            {orphaned.map(([key, value]) => (
              <div key={key}>
                <dt className="text-muted-foreground">
                  {BUILTIN_ANSWER_LABELS[key] || key}
                  {schemaKnown ? (
                    <span className="ml-1 text-[color:var(--aqt-fg-dim)]">· no longer asked</span>
                  ) : null}
                </dt>
                <dd className="mt-0.5 text-foreground">
                  <AnswerValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
          {registration.form_version_stale ? (
            <p className="text-xs text-muted-foreground">
              Answered on an older version of this form. Editing the registration re-files it
              against the current one.
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="space-y-1.5">
        <h3 className={EYEBROW_CLASS}>Details</h3>
        <dl className="space-y-2 text-xs text-muted-foreground">
          <div className="flex justify-between gap-3">
            <dt>Source</dt>
            <dd className="text-right">{registration.source}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Submitted</dt>
            <dd className="text-right">{formatSubmittedAt(format, registration.submitted_at)}</dd>
          </div>
          {registration.reviewed_at ? (
            <div className="flex justify-between gap-3">
              <dt>Reviewed</dt>
              <dd className="text-right">
                {formatSubmittedAt(format, registration.reviewed_at)}
                {registration.reviewed_by_username ? ` · ${registration.reviewed_by_username}` : ""}
              </dd>
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
