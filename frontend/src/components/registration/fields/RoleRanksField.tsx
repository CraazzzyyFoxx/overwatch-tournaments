"use client";

import { useId } from "react";

import DivisionIcon from "@/components/DivisionIcon";
import type { FieldRendererProps } from "@/components/forms/types";
import { NumberInput } from "@/components/ui/number-input";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { ROLES } from "@/lib/roles";
import { cn } from "@/lib/utils";

import FieldLabel from "../FieldLabel";
import { fieldControlClass, fieldInvalidClass } from "../FormField";

/** The answer this control edits: `{ [roleCode]: rank }`, blanks absent. */
function ranksOf(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/**
 * One stored rank as a number.
 *
 * Spelled out rather than inlined as `Number(stored) || null`: `Number("")` is
 * `0`, and an answer written by an older build — or by a hand-edited document —
 * holds the rank as a string.
 */
function storedRank(stored: unknown): number | null {
  if (stored === null || stored === undefined || stored === "") return null;
  const rank = Number(stored);
  return Number.isFinite(rank) ? rank : null;
}

/**
 * A `role_ranks` question: one rank per registration role, each crested with
 * the division that number lands on as it is typed.
 *
 * Deliberately NOT wired to the `roles` answer — a schema may ask for several
 * of these (current rank, peak rank, …) and none of them says which roles the
 * registrant plays, so every role is offered and a blank one is simply absent
 * from the stored object.
 *
 * The number is what gets stored, not the division: a division covers an SR
 * range, so a picker over the ladder would round every answer to its tier and
 * the crest beside the field already says which tier that is.
 */
export default function RoleRanksField({
  field,
  value,
  onChange,
  error,
}: Readonly<FieldRendererProps>) {
  const id = useId();
  const errorId = `${id}-error`;
  const grid = useDivisionGrid();
  const ranks = ranksOf(value);

  const setRank = (role: string, rank: number | null) => {
    const next = { ...ranks };
    if (rank === null) delete next[role];
    else next[role] = rank;
    onChange(next);
  };

  return (
    <fieldset
      className="m-0 min-w-0 space-y-2 border-0 p-0"
      aria-invalid={Boolean(error)}
      aria-describedby={error ? errorId : undefined}
    >
      <legend className="contents">
        <FieldLabel label={field.label || field.key} required={field.required} />
      </legend>
      <div className="grid gap-3 sm:grid-cols-3">
        {ROLES.map((role) => {
          const controlId = `${id}-${role.code}`;
          const rank = storedRank(ranks[role.code]);
          const division = resolveDivisionFromRank(grid, rank);
          return (
            <div key={role.code} className="space-y-2">
              <FieldLabel label={role.display} htmlFor={controlId} />
              <div className="relative">
                <NumberInput
                  id={controlId}
                  integer
                  min={0}
                  placeholder={field.placeholder || "—"}
                  value={rank}
                  onValueChange={(next) => setRank(role.code, next)}
                  aria-invalid={Boolean(error)}
                  className={cn(
                    fieldControlClass,
                    "h-9",
                    division != null && "pr-11",
                    error && fieldInvalidClass,
                  )}
                />
                {division != null ? (
                  <span
                    className="pointer-events-none absolute inset-y-0 right-2 flex items-center"
                    title={getDivisionLabel(grid, division) ?? undefined}
                  >
                    <DivisionIcon
                      division={division}
                      width={22}
                      height={22}
                      className="size-[22px] object-contain"
                    />
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      {field.help ? (
        <p className="text-xs leading-5 text-[color:var(--aqt-fg-muted)]">{field.help}</p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
