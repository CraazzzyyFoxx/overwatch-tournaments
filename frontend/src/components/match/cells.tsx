import React from "react";
import { cn } from "@/lib/utils";

/**
 * Small match/encounter presentational primitives shared across pages
 * (player profile, encounters, teams). Styled with the global `aqt-*`
 * classes + `--aqt-*` tokens (promoted to :root), so they work anywhere.
 */

export type StageKind = "group" | "playoffs" | "finals" | "default";

export const StagePill = ({ children, kind = "default", className }: { children: React.ReactNode; kind?: StageKind; className?: string }) => {
  return <span className={cn("aqt-stage-pill", kind !== "default" && kind, className)}>{children}</span>;
};

export type ResTagKind = "w" | "l" | "d";

export const ResTag = ({ kind, className }: { kind: ResTagKind; className?: string }) => (
  <span className={cn("aqt-res-tag", kind, className)}>{kind.toUpperCase()}</span>
);

export type ScoreKind = "win" | "loss" | "draw";

export const ScoreCell = ({ kind, value, className }: { kind: ScoreKind; value: string; className?: string }) => (
  <span className={cn("aqt-score-cell", kind, className)}>{value}</span>
);

export type MvpRank = "gold" | "silver" | "bronze" | "default";

export const MvpPill = ({ rank, label, className }: { rank: MvpRank; label: string; className?: string }) => (
  <span className={cn("aqt-mvp-pill", rank !== "default" && rank, className)}>{label}</span>
);

/** Map a 1-based per-match performance placement to an MvpPill rank. */
export const mvpRank = (performance: number | null | undefined): MvpRank => {
  if (performance === 1) return "gold";
  if (performance === 2) return "silver";
  if (performance === 3) return "bronze";
  return "default";
};

/** English ordinal for a positive integer (1 → "1st", 2 → "2nd", …). */
export const ordinal = (n: number): string => {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
};
