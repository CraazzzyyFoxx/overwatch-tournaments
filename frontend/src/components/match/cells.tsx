import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Small match/encounter presentational primitives shared across pages
 * (player profile, encounters, teams). A game's own placement/badge rules
 * live in its discipline module.
 */

export type ResTagKind = "w" | "l" | "d";

/** Results are their own meaning (DESIGN §2): win emerald, loss rose, draw amber. */
const RES_TAG_FILL: Record<ResTagKind, string> = {
  w: "bg-[color:var(--aqt-emerald)]",
  l: "bg-[color:var(--aqt-rose)]",
  d: "bg-[color:var(--aqt-amber)]"
};

/**
 * The W/L/D square: a form streak, a match row's result, a map pip. The letter
 * is always there (never colour alone); pass `children` for a translated one.
 */
export const ResTag = ({
  kind,
  className,
  children,
  ...props
}: { kind: ResTagKind } & React.HTMLAttributes<HTMLSpanElement>) => (
  <span
    className={cn(
      "inline-flex size-4.5 shrink-0 items-center justify-center rounded-sm font-display text-label leading-none font-extrabold text-[color:var(--aqt-bg)]",
      RES_TAG_FILL[kind],
      className
    )}
    {...props}
  >
    {children ?? kind.toUpperCase()}
  </span>
);

export type ScoreKind = "win" | "loss" | "draw";

const SCORE_TEXT: Record<ScoreKind, string> = {
  win: "text-[color:var(--aqt-emerald)]",
  loss: "text-[color:var(--aqt-rose)]",
  draw: "text-[color:var(--aqt-amber)]"
};

export const ScoreCell = ({
  kind,
  value,
  className
}: {
  kind: ScoreKind;
  value: string;
  className?: string;
}) => <span className={cn("aqt-tnum text-ui font-bold", SCORE_TEXT[kind], className)}>{value}</span>;
