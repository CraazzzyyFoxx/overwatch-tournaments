"use client";

import { useId } from "react";

import type { FieldRendererProps } from "@/components/forms/types";
import { ROLES } from "@/lib/roles";

import FieldLabel from "../FieldLabel";
import TextField from "../FormField";

/** The answer this control edits: `{ [roleCode]: rank }`, blanks absent. */
function ranksOf(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/**
 * A `role_ranks` question: one rank per registration role.
 *
 * Deliberately NOT wired to the `roles` answer — a schema may ask for several
 * of these (current rank, peak rank, …) and none of them says which roles the
 * registrant plays, so every role is offered and a blank one is simply absent
 * from the stored object.
 */
export default function RoleRanksField({
  field,
  value,
  onChange,
  error,
}: Readonly<FieldRendererProps>) {
  const id = useId();
  const errorId = `${id}-error`;
  const ranks = ranksOf(value);

  const setRank = (role: string, typed: string) => {
    const next = { ...ranks };
    if (typed.trim() === "") delete next[role];
    else next[role] = typed;
    onChange(next);
  };

  return (
    <fieldset
      className="m-0 min-w-0 space-y-1.5 border-0 p-0"
      aria-invalid={Boolean(error)}
      aria-describedby={error ? errorId : undefined}
    >
      <legend className="contents">
        <FieldLabel label={field.label || field.key} required={field.required} />
      </legend>
      <div className="grid gap-3 sm:grid-cols-3">
        {ROLES.map((role) => (
          <TextField
            key={role.code}
            label={role.display}
            type="number"
            placeholder={field.placeholder || "—"}
            value={ranks[role.code] == null ? "" : String(ranks[role.code])}
            onChange={(typed) => setRank(role.code, typed)}
          />
        ))}
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
