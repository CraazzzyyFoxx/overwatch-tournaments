import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { Tone } from "@/components/kit/tone";

export interface StatusPillProps extends ComponentPropsWithoutRef<"span"> {
  tone: Tone;
  children: ReactNode;
  /**
   * Leading dot in the pill's own tone, for a live/running state. Decorative:
   * the label beside it carries the state, so the dot is `aria-hidden`.
   */
  dot?: boolean;
}

/**
 * The admin's one *state* marker: tournament status, version state, collector
 * run state, account active/disabled. `shape="pill"` + shared `tone` on `Badge`.
 *
 * `Badge` (rounded-md) stays for *categories* — a role name, a scope, a kind.
 * The distinction is the whole point: a pill means "where this thing is in its
 * lifecycle", a badge means "what kind of thing it is".
 */
export function StatusPill({
  tone,
  children,
  dot = false,
  className,
  ...props
}: Readonly<StatusPillProps>) {
  return (
    <Badge tone={tone} shape="pill" className={className} {...props}>
      {dot ? <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-current" /> : null}
      {children}
    </Badge>
  );
}
