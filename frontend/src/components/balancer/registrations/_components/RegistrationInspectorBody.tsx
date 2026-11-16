"use client";

import type { ReactNode } from "react";
import { ArrowRight, Check, Circle, CircleAlert, CircleHelp, CircleX, Minus } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { AnswerValue } from "@/components/forms/AnswerValue";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { RegistrationNotesPanel } from "@/components/registration/RegistrationNotesPanel";
import {
  builtinAnswerLabel,
  localizedStatusMeta
} from "@/components/balancer/registrations/_components/registrationsTranslator";
import { BalancerStatusBadge } from "@/components/status/RegistrationBadges";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useRoleName } from "@/hooks/useRoleName";
import { useFormatter } from "@/lib/datetime/client";
import { formatAdmissionReason, type AdmissionTranslator } from "@/lib/registration/admission";
import { getSubroleLabel } from "@/lib/roster/roles";
import { findRole, ratedDimension, type LadderedOntology } from "@/lib/roster/ontology";
import { roleOf, subRoleSlugOf, type RoleRef } from "@/lib/roster/role-ref";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { FormField } from "@/types/forms.types";
import type { RequirementVerdict, SubroleCatalog } from "@/types/registration.types";

import type { CareerUserSignals } from "@/types/career-signals.types";

import { formatSubmittedAt } from "../registrationsTable.model";
import RegistrationCareerSection from "./RegistrationCareerSection";

/** Builtins whose answer is the player's own free text: read under its question, full width. */
const PROSE_BUILTINS: Record<string, true> = { public_notes: true, organizer_notes: true };

const DASH = <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;

const isBlank = (value: unknown) => value === null || value === undefined || value === "";

const STATUS_ICON = "mt-px size-3.5 shrink-0";

/** One line of the status checklist: what, its state as an icon, and why under it. */
function StatusRow({
  icon,
  label,
  value,
  detail
}: Readonly<{ icon: ReactNode; label: string; value?: ReactNode; detail?: ReactNode }>) {
  return (
    <li className="flex items-start gap-2">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <span className="text-foreground">{label}</span>
          {value}
        </div>
        {detail ? <p className="text-label text-[color:var(--aqt-fg-dim)]">{detail}</p> : null}
      </div>
    </li>
  );
}

/**
 * Where the registration stands, one line per thing that can hold it up: each
 * admission requirement by name, check-in, the balancer pool. A refusal names
 * its reason and who can fix it, so "not admitted" never stands alone.
 */
function StatusChecklist({ registration, t }: Readonly<{ registration: AdminRegistration; t: AdmissionTranslator }>) {
  const i18n = useTranslations("registrationsAdmin");
  const tRoot = useTranslations();
  const format = useFormatter();
  const { admission } = registration;
  const keysOf = (verdicts: RequirementVerdict[]) => new Set(verdicts.map((verdict) => verdict.key));
  const blocking = keysOf(admission.blockers);
  const overridden = keysOf(admission.overridden);

  const nameOf = (key: string) => {
    // The requirement registry is server-side and open-ended: an unknown key reads as itself.
    const messageKey = `admission.requirement.${key}` as never;
    return tRoot.has(messageKey) ? tRoot(messageKey) : key;
  };
  const why = (verdict: RequirementVerdict) =>
    verdict.reasons
      .map((reason) => `${formatAdmissionReason(t, reason)} · ${i18n(`inspector.actor.${reason.actor}`)}`)
      .join("; ");

  const requirementRow = (verdict: RequirementVerdict) => {
    const label = nameOf(verdict.key);
    if (verdict.state === "satisfied") {
      return <StatusRow key={verdict.key} label={label} icon={<Check className={cn(STATUS_ICON, "text-[color:var(--aqt-emerald)]")} aria-hidden />} />;
    }
    if (verdict.state === "undetermined") {
      // Fails open by design (see `RequirementState`): shown, never as a refusal.
      return (
        <StatusRow
          key={verdict.key}
          label={label}
          icon={<CircleHelp className={cn(STATUS_ICON, "text-muted-foreground")} aria-hidden />}
          detail={[i18n("inspector.undetermined"), why(verdict)].filter(Boolean).join(" · ")}
        />
      );
    }
    if (overridden.has(verdict.key)) {
      return (
        <StatusRow
          key={verdict.key}
          label={label}
          icon={<CircleAlert className={cn(STATUS_ICON, TONE_TEXT.warning)} aria-hidden />}
          detail={`${tRoot("common.admissionStatus.overridden")} · ${why(verdict)}`}
        />
      );
    }
    if (blocking.has(verdict.key)) {
      return (
        <StatusRow
          key={verdict.key}
          label={label}
          icon={<CircleX className={cn(STATUS_ICON, "text-destructive")} aria-hidden />}
          detail={why(verdict)}
        />
      );
    }
    // Blocked, but its gate (check-in) has not come yet: nothing is refused so far.
    return (
      <StatusRow
        key={verdict.key}
        label={label}
        icon={<Circle className={cn(STATUS_ICON, "text-muted-foreground")} aria-hidden />}
        detail={`${i18n("inspector.atCheckIn")} · ${why(verdict)}`}
      />
    );
  };

  return (
    <section className="space-y-1.5">
      <h3 className={eyebrowClass("muted")}>{i18n("inspector.status")}</h3>
      <ul className="space-y-1.5 text-xs">
        {admission.requirements.filter((verdict) => verdict.state !== "not_applicable").map(requirementRow)}
        <StatusRow
          label={i18n("inspector.checkIn")}
          icon={
            registration.checked_in ? (
              <Check className={cn(STATUS_ICON, "text-[color:var(--aqt-emerald)]")} aria-hidden />
            ) : (
              <Circle className={cn(STATUS_ICON, "text-muted-foreground")} aria-hidden />
            )
          }
          detail={
            registration.checked_in
              ? [
                  registration.checked_in_at ? formatSubmittedAt(format, registration.checked_in_at) : null,
                  registration.checked_in_by_username
                ]
                  .filter(Boolean)
                  .join(" · ")
              : i18n("inspector.notCheckedIn")
          }
        />
        <StatusRow
          label={i18n("inspector.balancer")}
          // The badge carries the state; an icon beside it would claim a pass/fail the pool has no notion of.
          icon={<span className={STATUS_ICON} aria-hidden />}
          value={
            <BalancerStatusBadge
              status={registration.balancer_status}
              meta={localizedStatusMeta(registration.balancer_status_meta, i18n)}
            />
          }
        />
      </ul>
    </section>
  );
}

/** A `role_ranks` answer: shown under each role it ranks. */
interface RankSource {
  key: string;
  label: string;
  ranks: Record<string, unknown>;
}

/**
 * One line per role, its declared rank on the right; under it what that rank
 * rests on: where it came from, the live game rank, and every `role_ranks`
 * answer for the same role. A list rather than a roles × sources table: with a
 * single role the table was mostly empty headers.
 */
function RolesRanksList({
  roles,
  rankSources,
  discipline,
  ontology,
  catalog
}: Readonly<{
  roles: AdminRegistration["roles"];
  rankSources: readonly RankSource[];
  discipline: string;
  ontology: LadderedOntology | null;
  catalog?: SubroleCatalog;
}>) {
  const i18n = useTranslations("registrationsAdmin");
  const tRows = useTranslations("common.roleRankRows");
  const nameOf = useRoleName();
  const grid = useDivisionGrid(discipline);
  // A `role_ranks` answer is on the game's own scale, so its crest comes off the
  // native ladder, never the workspace grid (see `AnswerValue`).
  const nativeLadder = ontology?.native_ladder.length ? { tiers: [...ontology.native_ladder] } : undefined;
  const dimension = ontology ? (ratedDimension(ontology)?.code ?? "") : "";

  // Declared, not playable: a rankless role must stay visible (see `RolesCell`
  // in registrationColumnCells.tsx).
  const declared = roles
    .filter((role) => role.is_declared_active)
    .sort((left, right) => left.priority - right.priority);
  const declaredCodes = new Set(declared.map((role) => roleOf(role.role)));
  // Answer keys are parent role codes. One the player ranked but did not declare
  // still gets a column: it is exactly what an organizer cross-checks.
  const order = (code: string) => {
    const index = ontology?.roles.findIndex((role) => role.dimension === dimension && role.code === code) ?? -1;
    return index < 0 ? Infinity : index;
  };
  const answeredOnly = [
    ...new Set(
      rankSources.flatMap((source) =>
        Object.keys(source.ranks).filter((code) => !isBlank(source.ranks[code]) && !declaredCodes.has(code))
      )
    )
  ].sort((left, right) => order(left) - order(right) || left.localeCompare(right));

  const rows = [
    ...declared.map((role) => ({ key: `${role.role.dimension}:${role.role.role}`, ref: role.role, role })),
    ...answeredOnly.map((code) => ({ key: `answer:${code}`, ref: { dimension, role: code } as RoleRef, role: null }))
  ].map((column) => {
    const known = ontology ? findRole(ontology, column.ref) : null;
    const slug = subRoleSlugOf(column.ref);
    return {
      ...column,
      name: known ? nameOf(known) : column.ref.role,
      // A leaf the dictionary knows is named by its own entry; the catalog label only covers one it does not.
      subrole: slug && !known ? getSubroleLabel(catalog, roleOf(column.ref), slug) : null
    };
  });
  if (rows.length === 0) return DASH;

  const answerRank = (value: unknown) => {
    const rank = Number(value);
    return nativeLadder && Number.isFinite(rank) ? (
      <RankCrest rank={rank} grid={nativeLadder} size={16} showValue className="text-foreground" />
    ) : (
      <span className="tabular-nums text-foreground">{String(value)}</span>
    );
  };

  return (
    <ul className="space-y-2.5 text-xs">
      {rows.map(({ key, ref, role, name, subrole }) => {
        const meta = role
          ? [
              role.rank_source && role.rank_source !== "none" ? tRows(`source.${role.rank_source}`) : null,
              role.ow_rank_value != null && role.ow_rank_value !== role.rank_value
                ? tRows("gameRank", { rank: role.ow_rank_value })
                : null
            ]
              .filter(Boolean)
              .join(" · ")
          : "";
        const answers = rankSources.filter((source) => !isBlank(source.ranks[roleOf(ref)]));
        return (
          <li key={key} className="space-y-1">
            <div className="flex items-center justify-between gap-3">
              <span
                className={cn(
                  "inline-flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm font-medium text-foreground",
                  role?.rank_value == null && "opacity-60"
                )}
              >
                <PlayerRoleIcon role={ref} ontology={ontology} size={16} />
                {name}
                {subrole ? <span className="font-normal text-muted-foreground">· {subrole}</span> : null}
                {role?.is_primary ? <span className={cn("text-label font-normal", TONE_TEXT.accent)}>{tRows("primary")}</span> : null}
              </span>
              {!role ? (
                DASH
              ) : role.rank_value == null ? (
                <span className={TONE_TEXT.warning}>{i18n("columns.noRank")}</span>
              ) : (
                <RankCrest rank={role.rank_value} grid={grid} size={18} showValue className="text-sm font-semibold text-foreground" />
              )}
            </div>
            {meta ? <p className="pl-5.5 text-label text-[color:var(--aqt-fg-dim)]">{meta}</p> : null}
            {answers.map((source) => (
              <div key={source.key} className="flex items-center justify-between gap-3 pl-5.5 text-muted-foreground">
                <span className="min-w-0">{source.label}</span>
                {answerRank(source.ranks[roleOf(ref)])}
              </div>
            ))}
          </li>
        );
      })}
    </ul>
  );
}

/** One answer as a row: the question wraps on the left, a short answer sits right. */
function AnswerRow({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <dt className="min-w-0 text-muted-foreground">{label}</dt>
      {/* `AnswerValue` paints its value muted, as a table cell wants; here the answer must outweigh its question. */}
      <dd className="flex max-w-[60%] shrink-0 justify-end text-right text-foreground [&>span]:text-foreground">
        {children}
      </dd>
    </div>
  );
}

/** Everything about one row that the table has no column for. */
export default function RegistrationInspectorBody({
  registration,
  discipline,
  ontology,
  catalog,
  schemaFields,
  schemaKnown,
  canWriteNotes,
  canModerateNotes,
  careerSignals,
  t
}: Readonly<{
  registration: AdminRegistration;
  discipline: string;
  /** The tournament owner's role dictionary and native ladder: role names, glyphs, answer crests. `null` while it loads. */
  ontology: LadderedOntology | null;
  catalog?: SubroleCatalog;
  schemaFields: FormField[];
  /** Whether the tournament's schema has actually been read. While it has not,
   *  no answer may be called dropped — there is nothing to have dropped it. */
  schemaKnown: boolean;
  /** `registration.update`: add organizer notes. */
  canWriteNotes: boolean;
  /** `registration.delete`: remove other organizers' notes. */
  canModerateNotes: boolean;
  /** The registrant's game-career signals; absent when the game collects none, the viewer may not read them or they are not in yet. */
  careerSignals?: CareerUserSignals | null;
  t: AdmissionTranslator;
}>) {
  const i18n = useTranslations("registrationsAdmin");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const answer = (key: string) => registration.answers?.[key];
  const labelOf = (field: FormField) => field.label || builtinAnswerLabel(field.key, i18n) || field.key;
  const yesNo = { yes: tCommon("yes"), no: tCommon("no") };

  // Answered questions of the CURRENT schema, then whatever the row still
  // carries that the current schema no longer asks. The second list is the
  // whole reason a stale registration is readable at all: its answers were
  // filed against an older version, and the table has no column for a question
  // that version asked and this one does not.
  const asked = schemaFields.filter((field) => field.key !== "roles" && !isBlank(answer(field.key)));
  const askedKeys: Record<string, true> = Object.fromEntries(
    schemaFields.map((field) => [field.key, true] as const)
  );
  const orphaned = Object.entries(registration.answers ?? {}).filter(
    ([key, value]) => askedKeys[key] !== true && key !== "roles" && !isBlank(value)
  );

  // Ranks join the roles table and handles get their own block; everything
  // else keeps the form's order as plain question–answer rows.
  const rankSources: RankSource[] = asked.flatMap((field) => {
    const value = answer(field.key);
    // A `role_ranks` answer is `{ [roleCode]: rank }` (see `FieldKind`); anything else stays a plain row.
    return field.kind === "role_ranks" && typeof value === "object" && value !== null && !Array.isArray(value)
      ? [{ key: field.key, label: labelOf(field), ranks: value as Record<string, unknown> }]
      : [];
  });
  const rest = asked.filter((field) => !rankSources.some((source) => source.key === field.key));
  const accounts = rest.filter((field) => field.key.startsWith("identity_"));
  const questions = rest.filter((field) => !accounts.includes(field));
  // Yes/no answers read as a checklist, the player's free text as quotes; the rest stays question–answer rows.
  const flags = questions.filter((field) => field.kind === "checkbox" || typeof answer(field.key) === "boolean");
  const prose = questions.filter(
    (field) => !flags.includes(field) && (field.kind === "textarea" || PROSE_BUILTINS[field.key] === true)
  );
  const plain = questions.filter((field) => !flags.includes(field) && !prose.includes(field));
  const hasQuestionnaire =
    flags.length > 0 || plain.length > 0 || orphaned.length > 0 || registration.form_version_stale;

  const orphanRows = orphaned.map(([key, value]) => (
    <AnswerRow key={key} label={builtinAnswerLabel(key, i18n) || key}>
      <AnswerValue value={value} labels={yesNo} ontology={ontology} />
    </AnswerRow>
  ));

  return (
    <div className="space-y-5 text-sm">
      <StatusChecklist registration={registration} t={t} />

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.rolesAndRanks")}</h3>
          {/* The chart itself lives on the person: a 380px panel is the wrong
              canvas for a time series, and the person page already draws it. */}
          {registration.user_id != null ? (
            <Button asChild variant="link" size="sm" className="h-auto shrink-0 gap-1 p-0 text-xs">
              <Link href={`/admin/people/${registration.user_id}`}>
                {i18n("inspector.openRankHistory")}
                <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </Button>
          ) : null}
        </div>
        <RolesRanksList
          roles={registration.roles}
          rankSources={rankSources}
          catalog={catalog}
          discipline={discipline}
          ontology={ontology}
        />
      </section>

      {careerSignals ? (
        <RegistrationCareerSection ontology={ontology} signals={careerSignals} />
      ) : null}

      {hasQuestionnaire ? (
        <section className="space-y-1.5">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.questionnaire")}</h3>
          {flags.length > 0 ? (
            <ul className="space-y-1 text-xs">
              {flags.map((field) => {
                const value = answer(field.key);
                // A checkbox that round-tripped through a form encoding arrives as `"false"` (see `AnswerValue`).
                const on = value !== false && value !== "false";
                const label = labelOf(field);
                return (
                  <li key={field.key} className={cn("flex items-start gap-2", on ? "text-foreground" : "text-muted-foreground")}>
                    {on ? (
                      <Check className="mt-px size-3.5 shrink-0 text-[color:var(--aqt-emerald)]" aria-hidden />
                    ) : (
                      <Minus className="mt-px size-3.5 shrink-0" aria-hidden />
                    )}
                    {/* The question is the label: a long one is clamped, its full wording stays in the tooltip and to screen readers. */}
                    <span className="line-clamp-2" title={label}>
                      {label}
                    </span>
                    <span className="sr-only">: {on ? yesNo.yes : yesNo.no}</span>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {plain.length > 0 || (orphaned.length > 0 && !schemaKnown) ? (
            <dl className="divide-y divide-dashed divide-border text-xs">
              {plain.map((field) => (
                <AnswerRow key={field.key} label={labelOf(field)}>
                  <AnswerValue value={answer(field.key)} kind={field.kind} labels={yesNo} ontology={ontology} />
                </AnswerRow>
              ))}
              {/* Without the schema nothing can be called dropped: the leftovers are plain answers. */}
              {schemaKnown ? null : orphanRows}
            </dl>
          ) : null}
          {orphaned.length > 0 && schemaKnown ? (
            <div className="space-y-0.5 pt-1">
              <p className="text-label text-[color:var(--aqt-fg-dim)]">{i18n("inspector.noLongerAskedTitle")}</p>
              <dl className="divide-y divide-dashed divide-border text-xs">{orphanRows}</dl>
            </div>
          ) : null}
          {registration.form_version_stale ? (
            <p className="text-xs text-muted-foreground">{i18n("inspector.olderForm")}</p>
          ) : null}
        </section>
      ) : null}

      {accounts.length > 0 ? (
        <section className="space-y-1.5">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.accounts")}</h3>
          <dl className="space-y-1 text-xs">
            {accounts.map((field) => {
              // An identity answer is a list, primary handle first (see `identityHandles`).
              const value = answer(field.key);
              return (
                <div key={field.key} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3">
                  <dt className="text-muted-foreground">{labelOf(field)}</dt>
                  <dd className="break-words text-foreground">
                    {(Array.isArray(value) ? value : [value]).map((handle) => (
                      <span key={String(handle)} className="block">
                        {String(handle)}
                      </span>
                    ))}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ) : null}

      {/* The player's own words, attributed so they never pass for the organizers' notes below. */}
      {prose.length > 0 ? (
        <div className="space-y-3">
          {prose.map((field) => (
            <figure key={field.key} className="space-y-1">
              <blockquote className="whitespace-pre-wrap border-l-2 border-border pl-3 text-xs text-foreground">
                {String(answer(field.key))}
              </blockquote>
              <figcaption className="pl-3.5 text-label text-[color:var(--aqt-fg-dim)]">
                {labelOf(field)} · {i18n("inspector.fromPlayer")}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : null}

      {registration.admin_notes ? (
        <section className="space-y-1.5">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.adminNotes")}</h3>
          <p className="whitespace-pre-wrap text-xs text-foreground">{registration.admin_notes}</p>
        </section>
      ) : null}

      <RegistrationNotesPanel
        key={registration.id}
        tournamentId={registration.tournament_id}
        target={{ registrationId: registration.id }}
        canWrite={canWriteNotes}
        canModerate={canModerateNotes}
        subject={registration.primary_handle ?? registration.display_name ?? undefined}
      />

      <footer className="space-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
        <p>
          {registration.source === "google_sheets" ? i18n("columns.sheets") : i18n("columns.manual")}
          {" · "}
          {i18n("inspector.submitted")} {formatSubmittedAt(format, registration.submitted_at)}
        </p>
        {registration.reviewed_at ? (
          <p>
            {i18n("inspector.reviewed")} {formatSubmittedAt(format, registration.reviewed_at)}
            {registration.reviewed_by_username ? ` · ${registration.reviewed_by_username}` : ""}
          </p>
        ) : null}
      </footer>
    </div>
  );
}
