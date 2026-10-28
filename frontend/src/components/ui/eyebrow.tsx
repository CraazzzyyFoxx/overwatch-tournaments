import type { HTMLAttributes, ThHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * The eyebrow: the small uppercase label above a value, a column or a section
 * (design book `.eyebrow`) — label voice, `text-label`, semibold, `tracking-label`.
 *
 * `tone` picks the text step and nothing else: `faint` is the DESIGN §2 label
 * floor, `dim` the meta step, `muted` the admin surfaces' label.
 */
export type EyebrowTone = "faint" | "dim" | "muted";

const EYEBROW_TONE: Record<EyebrowTone, string> = {
  faint: "text-[color:var(--aqt-fg-faint)]",
  dim: "text-[color:var(--aqt-fg-dim)]",
  muted: "text-[color:var(--aqt-fg-muted)]"
};

/**
 * The eyebrow recipe as a class string, for elements `Eyebrow` cannot be (a `Link`, a `<tr>`, a composed
 * class). Merged with `cn`, so a `className` here may override the tone's colour.
 */
export function eyebrowClass(tone: EyebrowTone = "faint", className?: string) {
  return cn(
    "font-[family-name:var(--aqt-data)] text-label font-semibold uppercase tracking-label",
    EYEBROW_TONE[tone],
    className
  );
}

type EyebrowProps = HTMLAttributes<HTMLElement> &
  Pick<ThHTMLAttributes<HTMLTableCellElement>, "scope" | "colSpan"> & {
    /** Element to render; `span` by default. */
    as?: "span" | "p" | "div" | "dt" | "h2" | "h3" | "h4" | "label" | "th" | "legend";
    tone?: EyebrowTone;
    /** Only meaningful with `as="label"`. */
    htmlFor?: string;
  };

export function Eyebrow({ as: Comp = "span", tone, className, ...props }: Readonly<EyebrowProps>) {
  return <Comp className={eyebrowClass(tone, className)} {...props} />;
}
