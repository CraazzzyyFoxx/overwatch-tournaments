"use client";

import type { ReactNode } from "react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Label } from "@/components/ui/label";

/**
 * One setting: what it is and why on the left, the control on the right.
 *
 * Lived inside `RegistrationFormBuilder` until the registration policy moved
 * into the settings rail; three sections now build rows from it, and a second
 * copy of a 12-line layout primitive is how two settings pages start drifting
 * apart visually.
 */
export function SettingRow({
  htmlFor,
  label,
  hint,
  children
}: Readonly<{ htmlFor?: string; label: string; hint?: ReactNode; children: ReactNode }>) {
  return (
    <div className="grid gap-3 py-4 first:pt-0 last:pb-0 md:grid-cols-2 md:items-center">
      <div className="min-w-0">
        <Label htmlFor={htmlFor} className="text-sm font-medium text-foreground">
          {label}
        </Label>
        {hint ? <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <div className="flex min-w-0 items-center md:justify-end">{children}</div>
    </div>
  );
}

/** A group of rows under an eyebrow; groups are separated by a hairline. */
export function SettingGroup({
  title,
  description,
  children
}: Readonly<{ title: string; description?: ReactNode; children: ReactNode }>) {
  return (
    <section className="border-t border-border pt-5 first:border-t-0 first:pt-0">
      <h2 className={EYEBROW_CLASS}>{title}</h2>
      {description ? (
        <p className="mt-1 max-w-prose text-xs text-muted-foreground">{description}</p>
      ) : null}
      <div className="mt-3 divide-y divide-border/60">{children}</div>
    </section>
  );
}
