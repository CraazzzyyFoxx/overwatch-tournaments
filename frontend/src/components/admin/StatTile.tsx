import type { ElementType, ReactNode } from "react";

import { cn } from "@/lib/utils";
import { TONE_TEXT, type Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";

interface StatTileProps {
  /** Uppercase eyebrow naming what is measured. */
  label: string;
  value: string | number;
  /** Optional second line qualifying the value (scope, breakdown). */
  detail?: string;
  icon?: ElementType;
  /**
   * Colours the value, and only for `warning` / `danger`: a number that needs
   * attention. Every other tone renders neutral, because a green "8/8" or a
   * teal "3" is decoration (§0 rule 5).
   */
  tone?: Tone;
  /** One control the tile owns (a bulk re-enable beside an outage count). */
  action?: ReactNode;
  className?: string;
}

/**
 * The admin's single status/metric tile.
 *
 * Replaces seven independent implementations that had drifted to three
 * eyebrow specs and three value scales. `value` carries `tabular-nums`
 * unconditionally because every consumer feeds it a refetching number.
 */
export function StatTile({
  label,
  value,
  detail,
  icon: Icon,
  tone = "neutral",
  action,
  className
}: Readonly<StatTileProps>) {
  const attention = tone === "warning" || tone === "danger";
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card/70 p-4",
        className
      )}
    >
      <div className="min-w-0 flex-1">
        <p className={eyebrowClass("muted")}>{label}</p>
        <p className={cn("mt-2 truncate font-display text-title font-semibold tabular-nums", attention && TONE_TEXT[tone])}>
          {value}
        </p>
        {detail ? <p className="mt-1 text-xs text-muted-foreground">{detail}</p> : null}
        {action ? <div className="mt-3">{action}</div> : null}
      </div>
      {Icon ? <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden /> : null}
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
