import type { ReactNode } from "react";

import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { TONE_TEXT, type Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { cn } from "@/lib/utils";

const VALUE_SIZE = {
  sm: "text-body font-medium",
  default: "text-heading font-semibold"
} as const;

/**
 * Label/value facts as plain text, not KPI tiles (DESIGN §14): an eyebrow over
 * a tabular value. One wrapping row by default; `className` swaps it for a grid.
 * A pair stacks with its value at the bottom, so a row's values stay on one
 * baseline when one label wraps. `tone` colours the value: set it only for a
 * number that needs attention.
 */
export function FactList({
  facts,
  size = "default",
  className
}: Readonly<{
  facts: ReadonlyArray<{ label: string; value: ReactNode; tone?: Tone }>;
  size?: "sm" | "default";
  className?: string;
}>) {
  return (
    <dl className={cn("flex flex-wrap gap-x-8 gap-y-3", className)}>
      {facts.map((fact) => (
        <div key={fact.label} className="flex min-w-0 flex-col justify-between gap-1">
          <dt className={eyebrowClass("muted")}>{fact.label}</dt>
          <dd className={cn("tabular-nums", VALUE_SIZE[size], fact.tone && TONE_TEXT[fact.tone])}>
            {fact.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
