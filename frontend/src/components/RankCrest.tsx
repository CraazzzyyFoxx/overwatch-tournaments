"use client";

import type { ReactNode } from "react";

import DivisionIcon from "@/components/DivisionIcon";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

/**
 * A division crest with the tier's name in its tooltip, from a `division` or a
 * `rank` resolved through `grid`. Renders nothing when neither lands on a tier,
 * unless `showValue` asks for the rank (an em dash without one) after it.
 *
 * `tooltip={false}` is for a crest inside a control or a cell whose own title
 * already names the tier: the bare crest, no second hover target.
 */
export function RankCrest({
  rank,
  division,
  grid,
  size = 22,
  showValue = false,
  tooltip = true,
  className
}: Readonly<{
  /** Resolved through `grid`; only read for the crest when `division` is not given. */
  rank?: number | null;
  division?: number | null;
  grid: DivisionGrid | DivisionGridVersion;
  /** Edge of the crest's square, px. */
  size?: number;
  /** The rank, rounded, after the crest. */
  showValue?: boolean;
  tooltip?: boolean;
  className?: string;
}>) {
  const tier = division ?? resolveDivisionFromRank(grid, rank);
  let crest: ReactNode = null;
  if (tier != null) {
    const crestClass = cn("inline-flex shrink-0", !showValue && className);
    const icon = (
      <span className={tooltip ? "inline-flex" : crestClass} style={{ width: size, height: size }}>
        <DivisionIcon
          division={tier}
          tournamentGrid={grid}
          width={size}
          height={size}
          className="size-full object-contain"
        />
      </span>
    );
    crest = tooltip ? (
      <IconTooltip label={getDivisionLabel(grid, tier) ?? String(tier)} className={crestClass}>
        {icon}
      </IconTooltip>
    ) : (
      icon
    );
  }
  if (!showValue) return crest;
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      {crest}
      <span className="tabular-nums">{rank == null ? "\u2014" : Math.round(rank)}</span>
    </span>
  );
}
