"use client";

import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
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

/** Builtins whose answer is the player's own free text: read under its question, full width. */
const PROSE_BUILTINS: Record<string, true> = { public_notes: true, organizer_notes: true };

const DASH = <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;

const isBlank = (value: unknown) => value === null || value === undefined || value === "";

/** A `role_ranks` answer: one row of the roles table under the declared ranks. */
interface RankSource {
  key: string;
  label: string;
  ranks: Record<string, unknown>;
}

/**
 * Roles across, rank sources down: the declared rank first, then every
 * `role_ranks` answer. Transposed because a game has two or three roles but a
 * question's label runs long: as column headers the labels pushed the table
 * past the panel's width.
 */
function RolesRanksTable({
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

  const columns = [
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
  if (columns.length === 0) return DASH;

  // Where each declared rank came from and the live game rank: one footnote per
  // role, since a narrow column has no room for it.
  const footnotes = columns.flatMap(({ key, name, role }) => {
    if (!role) return [];
    const meta = [
      role.rank_source && role.rank_source !== "none" ? tRows(`source.${role.rank_source}`) : null,
      role.ow_rank_value != null && role.ow_rank_value !== role.rank_value
        ? tRows("gameRank", { rank: role.ow_rank_value })
        : null
    ]
      .filter(Boolean)
      .join(" · ");
    return meta ? [{ key, text: `${name}: ${meta}` }] : [];
  });

  const answerCell = (value: unknown) => {
    if (isBlank(value)) return DASH;
    const rank = Number(value);
    return nativeLadder && Number.isFinite(rank) ? (
      <RankCrest rank={rank} grid={nativeLadder} size={16} showValue className="text-foreground" />
    ) : (
      <span className="tabular-nums text-foreground">{String(value)}</span>
    );
  };

  // The kit table, stripped to a plain grid: no row borders, hover or cell padding in a narrow panel.
  const row = "border-0 hover:bg-transparent";
  const rowHead = "h-auto px-0 py-1 text-left align-top font-normal whitespace-normal text-muted-foreground";
  const cell = "px-0 py-1 pl-3 align-top";
  return (
    <div className="space-y-1.5">
      <Table className="text-xs">
        <TableHeader>
          <TableRow className={row}>
            <TableHead className="h-auto px-0" />
            {columns.map(({ key, ref, role, name, subrole }) => (
              <TableHead
                key={key}
                scope="col"
                className={cn("h-auto px-0 pb-1.5 pl-3 text-right align-bottom font-normal", role?.rank_value == null && "opacity-60")}
              >
                <span className="inline-flex flex-col items-end">
                  <span className="inline-flex items-center gap-1 font-medium text-foreground">
                    <PlayerRoleIcon role={ref} ontology={ontology} size={14} />
                    {name}
                  </span>
                  {subrole ? <span className="text-label text-[color:var(--aqt-fg-dim)]">{subrole}</span> : null}
                  {role?.is_primary ? <span className={cn("text-label", TONE_TEXT.accent)}>{tRows("primary")}</span> : null}
                </span>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow className={row}>
            <TableHead scope="row" className={rowHead}>
              {i18n("inspector.declaredRank")}
            </TableHead>
            {columns.map(({ key, role }) => (
              <TableCell key={key} className={cell}>
                <span className="flex justify-end">
                  {!role ? (
                    DASH
                  ) : role.rank_value == null ? (
                    <span className={TONE_TEXT.warning}>{i18n("columns.noRank")}</span>
                  ) : (
                    <RankCrest rank={role.rank_value} grid={grid} size={16} showValue className="font-semibold text-foreground" />
                  )}
                </span>
              </TableCell>
            ))}
          </TableRow>
          {rankSources.map((source) => (
            <TableRow key={source.key} className={row}>
              <TableHead scope="row" className={rowHead}>
                {source.label}
              </TableHead>
              {columns.map(({ key, ref }) => (
                <TableCell key={key} className={cell}>
                  <span className="flex justify-end">{answerCell(source.ranks[roleOf(ref)])}</span>
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {footnotes.map((note) => (
        <p key={note.key} className="text-label text-[color:var(--aqt-fg-dim)]">
          {note.text}
        </p>
      ))}
    </div>
  );
}

/** One answer as a row: the question wraps on the left, a short answer sits right; free text goes under its question. */
function AnswerRow({ label, children, block = false }: Readonly<{ label: string; children: ReactNode; block?: boolean }>) {
  return block ? (
    <div className="space-y-0.5 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="whitespace-pre-wrap text-foreground">{children}</dd>
    </div>
  ) : (
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
  const hasQuestionnaire = questions.length > 0 || orphaned.length > 0;

  const blockers = registration.admission.blockers.flatMap((requirement) => requirement.reasons);

  const orphanRows = orphaned.map(([key, value]) => (
    <AnswerRow key={key} label={builtinAnswerLabel(key, i18n) || key}>
      <AnswerValue value={value} labels={yesNo} ontology={ontology} />
    </AnswerRow>
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
          rankSources={rankSources}
          catalog={catalog}
          discipline={discipline}
          ontology={ontology}
        />
      </section>

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
                    {Array.isArray(value) ? value.join(", ") : String(value)}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ) : null}

      {hasQuestionnaire ? (
        <section className="space-y-1.5">
          <h3 className={eyebrowClass("muted")}>{i18n("inspector.questionnaire")}</h3>
          {questions.length > 0 || (orphaned.length > 0 && !schemaKnown) ? (
            <dl className="divide-y divide-dashed divide-border text-xs">
              {questions.map((field) => {
                const prose = field.kind === "textarea" || PROSE_BUILTINS[field.key] === true;
                return (
                  <AnswerRow key={field.key} label={labelOf(field)} block={prose}>
                    {prose ? (
                      String(answer(field.key))
                    ) : (
                      <AnswerValue value={answer(field.key)} kind={field.kind} labels={yesNo} ontology={ontology} />
                    )}
                  </AnswerRow>
                );
              })}
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
