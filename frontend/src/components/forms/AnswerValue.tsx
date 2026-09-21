import type { ReactNode } from "react";
import { Check, ExternalLink, Minus } from "lucide-react";

import { ROLE_LABELS, ROLES } from "@/lib/roles";
import type { FieldKind } from "@/types/forms.types";

/**
 * One stored answer, rendered for a table cell or an inspector row.
 *
 * Shared by the public participants roster, the admin registrations table and
 * the live draft's player inspector: all three read the same flat `answers`
 * document off the same schema, and a second copy of this switch would drift
 * the moment a kind is added.
 *
 * Deliberately hook-free, with the boolean wording passed in: the public roster
 * sits inside a next-intl provider and the admin table renders plain English,
 * and next-intl's translator type is keyed on the message catalogue so it
 * cannot be widened to a plain `(key: string) => string` here.
 */
export interface AnswerValueProps {
  value: unknown;
  /** The field's kind. Omit for a value whose field is unknown (a stale answer). */
  kind?: FieldKind;
  labels?: { yes: string; no: string };
  /** BCP-47 tag for `date`. Defaults to the host's locale. */
  locale?: string;
}

const EMPTY = <span className="text-[color:var(--aqt-fg-dim)]">&mdash;</span>;

const MUTED = "text-[color:var(--aqt-fg-muted)]";

const CHIP =
  "inline-flex items-center rounded-md border border-[color:var(--aqt-border-2)] " +
  "bg-[color:var(--aqt-overlay-3)] px-1.5 py-0.5 text-xs font-medium text-[color:var(--aqt-fg-muted)]";

/** Sort key for a `role_ranks` entry: known roles first, in `ROLES` order. */
function roleRank(code: string): number {
  const index = ROLES.findIndex((role) => role.code === code);
  return index < 0 ? ROLES.length : index;
}

export function AnswerValue({
  value,
  kind,
  labels = { yes: "Yes", no: "No" },
  locale,
}: Readonly<AnswerValueProps>): ReactNode {
  if (value === null || value === undefined || value === "") return EMPTY;
  if (Array.isArray(value)) {
    if (value.length === 0) return EMPTY;
    return (
      <span className="flex flex-wrap gap-1">
        {value.map((item) => (
          <span key={String(item)} className={CHIP}>
            {String(item)}
          </span>
        ))}
      </span>
    );
  }

  // `role_ranks` is the one answer that is an OBJECT, so it is read before the
  // generic `String(value)` tail turns it into "[object Object]". Keyed on the
  // VALUE, not on `kind`: an answer whose question was since deleted arrives
  // here with no kind at all, and it is still ranks. Roles sort in `ROLES`
  // order so one table column does not reorder itself row by row.
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, rank]) => rank !== null && rank !== undefined && rank !== "")
      .sort(([a], [b]) => roleRank(a) - roleRank(b));
    if (entries.length === 0) return EMPTY;
    return (
      <span className="flex flex-wrap gap-1">
        {entries.map(([role, rank]) => (
          <span key={role} className={CHIP}>
            {ROLE_LABELS[role] ?? role} {String(rank)}
          </span>
        ))}
      </span>
    );
  }

  // A checkbox that round-tripped through a form encoding arrives as the string
  // `"false"`, which must read as No rather than as a truthy non-empty string.
  if (typeof value === "boolean" || kind === "checkbox") {
    const on = value !== false && value !== "false";
    return (
      <span className={`inline-flex items-center gap-1 ${MUTED}`}>
        {on ? (
          <Check className="size-3.5 text-[color:var(--aqt-emerald)]" aria-hidden />
        ) : (
          <Minus className="size-3.5" aria-hidden />
        )}
        {on ? labels.yes : labels.no}
      </span>
    );
  }

  if (kind === "url") {
    return (
      <a
        href={String(value)}
        target="_blank"
        rel="noopener noreferrer"
        className={`inline-flex items-center gap-1 ${MUTED} underline decoration-[color:var(--aqt-border-3)] hover:text-[color:var(--aqt-fg)]`}
      >
        <span className="max-w-[120px] truncate">{String(value)}</span>
        <ExternalLink className="size-3 shrink-0" aria-hidden />
      </a>
    );
  }

  if (kind === "date") {
    // An unparseable answer is shown verbatim: a stored string the organizer
    // can see is more useful than "Invalid Date".
    const parsed = new Date(String(value));
    const text = Number.isNaN(parsed.getTime())
      ? String(value)
      : parsed.toLocaleDateString(locale);
    return <span className={MUTED}>{text}</span>;
  }

  if (kind === "select") return <span className={CHIP}>{String(value)}</span>;

  return <span className={MUTED}>{String(value)}</span>;
}

export default AnswerValue;
