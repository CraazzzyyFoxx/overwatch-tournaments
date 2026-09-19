import type { ElementType } from "react";

import { cn } from "@/lib/utils";
import { EYEBROW_CLASS, TONE_CLASS, type Tone } from "@/components/kit/tone";

interface StatTileProps {
  /** Uppercase eyebrow naming what is measured. */
  label: string;
  value: string | number;
  /** Optional second line qualifying the value (scope, breakdown). */
  detail?: string;
  icon?: ElementType;
  tone?: Tone;
  className?: string;
}

/**
 * The admin's single status/metric tile.
 *
 * Replaces seven independent implementations that had drifted to three
 * eyebrow specs (`text-xs`, `11px`, `tracking-wider`) and three value
 * scales (`text-2xl`, `text-xl`, `text-lg`). `value` carries `tabular-nums`
 * unconditionally because every consumer feeds it a refetching number.
 */
export function StatTile({
  label,
  value,
  detail,
  icon: Icon,
  tone = "neutral",
  className
}: Readonly<StatTileProps>) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card/70 p-4",
        className
      )}
    >
      <div className="min-w-0">
        <p className={EYEBROW_CLASS}>{label}</p>
        <p className="mt-2 truncate text-2xl font-semibold tabular-nums">{value}</p>
        {detail ? <p className="mt-1 text-xs text-muted-foreground">{detail}</p> : null}
      </div>
      {Icon ? (
        <span className={cn("shrink-0 rounded-lg border p-2", TONE_CLASS[tone])}>
          <Icon className="size-4" aria-hidden />
        </span>
      ) : null}
    </div>
  );
}

/** Standard tile row. Holds four across from `xl` up, two from `md`. */
export function StatTileGrid({
  children,
  className
}: Readonly<{ children: React.ReactNode; className?: string }>) {
  return (
    <div className={cn("grid gap-3 md:grid-cols-2 xl:grid-cols-4", className)}>{children}</div>
  );
}
