"use client";

import { useId, useMemo } from "react";

import FieldLabel from "@/components/forms/FieldLabel";
import FieldShell from "@/components/forms/FieldShell";
import type { FieldRendererProps } from "@/components/forms/types";
import { RankCrest } from "@/components/RankCrest";
import { NumberInput } from "@/components/ui/number-input";
import { useRoleName } from "@/hooks/useRoleName";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import { registrationRoles, showsRoles } from "@/lib/roster/ontology";
import type { DivisionGrid } from "@/types/workspace.types";

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
 *
 * The crest is read off the owner game's NATIVE ladder (its scoped metadata),
 * never the workspace's grid: what the registrant types is a rank of THAT game,
 * and it lands on the same native tier no matter what a workspace calls its own
 * divisions. A workspace grid here would rename the number under the registrant.
 * A game with no native ladder shows no crest, and no other game's ladder is
 * ever borrowed.
 */
export default function RoleRanksField({
  field,
  value,
  onChange,
  error,
  context,
}: Readonly<FieldRendererProps>) {
  const id = useId();
  const nameOf = useRoleName();
  const ranks = ranksOf(value);
  const roles = registrationRoles(context.metadata);
  // One role: the block's own label names its one field, and the block is that role's whatever was declared.
  const named = showsRoles(context.metadata);
  const nativeLadder = useMemo<DivisionGrid>(
    () => ({ tiers: [...(context.metadata?.native_ladder ?? [])] }),
    [context.metadata],
  );
  // Required per ROLE, not per block: the registrant must rate the roles they
  // signed up for, and may still rate the ones they did not.
  const declared = context.declaredRoles ?? [];

  const setRank = (role: string, rank: number | null) => {
    const next = { ...ranks };
    if (rank === null) delete next[role];
    else next[role] = rank;
    onChange(next);
  };

  return (
    <FieldShell
      id={id}
      label={field.label || field.key}
      required={field.required}
      help={field.help}
      error={error}
      layout="group"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {roles.map((role) => {
          const controlId = `${id}-${role.code}`;
          const rank = storedRank(ranks[role.code]);
          const division = resolveDivisionFromRank(nativeLadder, rank);
          // Only the blank cells the objection is ABOUT go red: a rank that is
          // filled in is not why the block was refused, and painting all three
          // made the answered roles look wrong too. With nothing declared the
          // block just needs a rank, so every blank cell is a candidate.
          const atFault =
            error !== null &&
            rank === null &&
            (!named || declared.length === 0 || declared.includes(role.code));
          return (
            <div key={role.code} className="space-y-2">
              {named ? (
                <FieldLabel
                  label={nameOf(role)}
                  htmlFor={controlId}
                  required={field.required && declared.includes(role.code)}
                />
              ) : null}
              <div className="relative">
                <NumberInput
                  id={controlId}
                  aria-label={named ? undefined : field.label || field.key}
                  integer
                  min={0}
                  placeholder={field.placeholder || "—"}
                  value={rank}
                  onValueChange={(next) => setRank(role.code, next)}
                  aria-invalid={atFault}
                  className={division != null ? "pr-11" : undefined}
                />
                {division != null ? (
                  <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center">
                    <RankCrest division={division} grid={nativeLadder} tooltip={false} />
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </FieldShell>
  );
}
