"use client";

import { ArrowRight, Check, Minus } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { AnswerValue } from "@/components/forms/AnswerValue";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { RegistrationNotesPanel } from "@/components/registration/RegistrationNotesPanel";
import { builtinAnswerLabel } from "@/components/balancer/registrations/_components/registrationsTranslator";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@craazzzyyfoxx/admin-kit/ui/table";
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
import type { SubroleCatalog } from "@/types/registration.types";

import { formatSubmittedAt } from "../registrationsTable.model";

/** Builtins whose answer is the player's own free text, read as a quote rather than a key–value row. */
const PROSE_BUILTINS: Record<string, true> = { public_notes: true, organizer_notes: true };

const DASH = <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;

const isBlank = (value: unknown) => value === null || value === undefined || value === "";

/** A `role_ranks` answer shown as a column beside the declared rank. */
interface RankColumn {
  key: string;
  label: string;
  ranks: Record<string, unknown>;
}

/**
 * Declared roles in priority order, one row each, with every `role_ranks` answer
 * as a column beside the declared rank: the organizer compares "declared 3500"
 * with "peak this season 3500" on one line instead of across two blocks.
 */
function RolesRanksTable({
  roles,
  rankColumns,
  discipline,
  ontology,
  catalog
}: Readonly<{
  roles: AdminRegistration["roles"];
  rankColumns: readonly RankColumn[];
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
  // still gets a row: it is exactly what an organizer cross-checks.
  const order = (code: string) => {
    const index = ontology?.roles.findIndex((role) => role.dimension === dimension && role.code === code) ?? -1;
    return index < 0 ? Infinity : index;
  };
  const answeredOnly = [
    ...new Set(
      rankColumns.flatMap((column) =>
        Object.keys(column.ranks).filter((code) => !isBlank(column.ranks[code]) && !declaredCodes.has(code))
      )
    )
  ].sort((left, right) => order(left) - order(right) || left.localeCompare(right));

  const rows: { key: string; ref: RoleRef; declared: AdminRegistration["roles"][number] | null }[] = [
    ...declared.map((role) => ({ key: `${role.role.dimension}:${role.role.role}`, ref: role.role, declared: role })),
    ...answeredOnly.map((code) => ({ key: `answer:${code}`, ref: { dimension, role: code }, declared: null }))
  ];
  if (rows.length === 0) return DASH;

  const answerCell = (value: unknown) => {
    if (isBlank(value)) return DASH;
    const rank = Number(value);
    return nativeLadder && Number.isFinite(rank) ? (
      <RankCrest rank={rank} grid={nativeLadder} size={18} showValue className="text-foreground" />
    ) : (
      <span className="tabular-nums text-foreground">{String(value)}</span>
    );
  };

  // The kit table, stripped to a plain grid: no row borders, hover or cell padding in a 348px panel.
  const head = "h-auto px-0 pb-1 pl-3 text-right font-normal whitespace-normal";
  const cell = "px-0 py-1 pl-3 align-top";
  return (
    <Table className="text-xs">
      {rankColumns.length > 0 ? (
        <TableHeader>
          <TableRow className="border-0 hover:bg-transparent">
            <TableHead scope="col" className={cn(head, "pl-0 text-left")}>
              {i18n("inspector.role")}
            </TableHead>
            <TableHead scope="col" className={head}>
              {i18n("inspector.declaredRank")}
            </TableHead>
            {rankColumns.map((column) => (
              <TableHead key={column.key} scope="col" className={head}>
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
      ) : null}
      <TableBody>
        {rows.map(({ key, ref, declared: role }) => {
          const known = ontology ? findRole(ontology, ref) : null;
          const name = known ? nameOf(known) : ref.role;
          // A leaf the dictionary knows is named by its own entry; the catalog label only covers one it does not.
          const subrole =
            subRoleSlugOf(ref) && !known ? getSubroleLabel(catalog, roleOf(ref), subRoleSlugOf(ref)!) : null;
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
          return (
            <TableRow key={key} className="border-0 hover:bg-transparent">
              <TableCell className={cn(cell, "pl-0 whitespace-normal")}>
                <span className={cn("flex min-w-0 items-center gap-1.5", role?.rank_value == null && "opacity-60")}>
                  <PlayerRoleIcon role={ref} ontology={ontology} size={16} />
                  <span className="truncate font-medium text-foreground" title={name}>
                    {name}
                  </span>
                  {subrole ? <span className="truncate text-[color:var(--aqt-fg-dim)]">{subrole}</span> : null}
                  {role?.is_primary ? (
                    <span className={cn("shrink-0 text-label", TONE_TEXT.accent)}>{tRows("primary")}</span>
                  ) : null}
                </span>
                {meta ? <span className="block pl-[22px] text-label text-[color:var(--aqt-fg-dim)]">{meta}</span> : null}
              </TableCell>
              <TableCell className={cell}>
                <span className="flex justify-end">
                  {!role ? (
                    DASH
                  ) : role.rank_value == null ? (
                    <span className={TONE_TEXT.warning}>{i18n("columns.noRank")}</span>
                  ) : (
                    <RankCrest rank={role.rank_value} grid={grid} size={18} showValue className="font-semibold text-foreground" />
                  )}
                </span>
              </TableCell>
              {rankColumns.map((column) => (
                <TableCell key={column.key} className={cell}>
                  <span className="flex justify-end">{answerCell(column.ranks[roleOf(ref)])}</span>
                </TableCell>
              ))}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
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

  // Grouped by what the answer is, not by schema order: ranks join the roles
  // table, yes/no answers collapse into one row of chips, free text reads as a
  // quote, and the rest are key–value rows.
  const rankColumns: RankColumn[] = asked.flatMap((field) => {
    const value = answer(field.key);
    // A `role_ranks` answer is `{ [roleCode]: rank }` (see `FieldKind`); anything else stays a plain row.
    return field.kind === "role_ranks" && typeof value === "object" && value !== null && !Array.isArray(value)
      ? [{ key: field.key, label: labelOf(field), ranks: value as Record<string, unknown> }]
      : [];
  });
  const rest = asked.filter((field) => !rankColumns.some((column) => column.key === field.key));
  const isFlag = (field: FormField) => field.kind === "checkbox" || typeof answer(field.key) === "boolean";
  const flags = rest.filter(isFlag);
  const prose = rest.filter((field) => !isFlag(field) && (field.kind === "textarea" || PROSE_BUILTINS[field.key]));
  const pairs = rest.filter((field) => !flags.includes(field) && !prose.includes(field));
  const hasQuestionnaire = rest.length > 0 || orphaned.length > 0;

  const blockers = registration.admission.blockers.flatMap((requirement) => requirement.reasons);

  const orphanRows = orphaned.map(([key, value]) => (
    <div key={key} className="flex items-start justify-between gap-3">
      <dt className="text-muted-foreground">{builtinAnswerLabel(key, i18n) || key}</dt>
      <dd className="flex min-w-0 justify-end text-right text-foreground">
        <AnswerValue value={value} labels={yesNo} ontology={ontology} />
      </dd>
    </div>
  ));

  return (
    <div className="space-y-5 text-sm">
      {blockers.length > 0 ? (
        <section className="space-y-1.5">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.admission")}</h3>
          {/* Behind check-in a blocker is spent, not fatal (see `AdmissionStatusBadge`): only a refusal reads red. */}
          <ul
            className={cn(
              "space-y-1 text-xs",
              registration.admission.decision === "not_admitted" ? "text-destructive" : "text-muted-foreground"
            )}
          >
            {blockers.map((reason) => (
              <li key={`${reason.code}-${reason.actor}`}>{formatAdmissionReason(t, reason)}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="space-y-1.5">
        <h3 className={eyebrowClass("muted")}>{i18n("inspector.rolesAndRanks")}</h3>
        <RolesRanksTable
          roles={registration.roles}
          rankColumns={rankColumns}
          catalog={catalog}
          discipline={discipline}
          ontology={ontology}
        />
      </section>

      {hasQuestionnaire ? (
        <section className="space-y-2.5">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.questionnaire")}</h3>
          {flags.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5">
              {flags.map((field) => {
                const value = answer(field.key);
                // A checkbox that round-tripped through a form encoding arrives as `"false"`.
                const on = value !== false && value !== "false";
                return (
                  <li
                    key={field.key}
                    className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs"
                  >
                    <span className="text-muted-foreground">{labelOf(field)}</span>
                    {on ? (
                      <Check className="size-3 text-[color:var(--aqt-emerald)]" aria-hidden />
                    ) : (
                      <Minus className="size-3 text-muted-foreground" aria-hidden />
                    )}
                    <span className={on ? "text-foreground" : "text-muted-foreground"}>
                      {on ? yesNo.yes : yesNo.no}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {prose.map((field) => (
            <figure key={field.key} className="space-y-0.5">
              <figcaption className="text-xs text-muted-foreground">{labelOf(field)}</figcaption>
              <blockquote className="whitespace-pre-wrap border-l-2 border-border pl-2 text-foreground">
                {String(answer(field.key))}
              </blockquote>
            </figure>
          ))}
          {pairs.length > 0 || (orphaned.length > 0 && !schemaKnown) ? (
            <dl className="space-y-1.5 text-xs">
              {pairs.map((field) => (
                <div key={field.key} className="flex items-start justify-between gap-3">
                  <dt className="text-muted-foreground">{labelOf(field)}</dt>
                  <dd className="flex min-w-0 justify-end text-right text-foreground">
                    <AnswerValue value={answer(field.key)} kind={field.kind} labels={yesNo} ontology={ontology} />
                  </dd>
                </div>
              ))}
              {/* Without the schema nothing can be called dropped: the leftovers are plain answers. */}
              {schemaKnown ? null : orphanRows}
            </dl>
          ) : null}
          {orphaned.length > 0 && schemaKnown ? (
            <div className="space-y-1.5">
              <p className="text-label text-[color:var(--aqt-fg-dim)]">{i18n("inspector.noLongerAskedTitle")}</p>
              <dl className="space-y-1.5 text-xs">{orphanRows}</dl>
            </div>
          ) : null}
          {registration.form_version_stale ? (
            <p className="text-xs text-muted-foreground">{i18n("inspector.olderForm")}</p>
          ) : null}
        </section>
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
      />

      <footer className="space-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
        <div className="flex items-center justify-between gap-3">
          <span>
            {registration.source === "google_sheets" ? i18n("columns.sheets") : i18n("columns.manual")}
            {" · "}
            {i18n("inspector.submitted")} {formatSubmittedAt(format, registration.submitted_at)}
          </span>
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
