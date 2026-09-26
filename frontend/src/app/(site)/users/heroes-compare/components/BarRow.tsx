import { memo } from "react";
import Link from "next/link";

import { HeroLeaderboardEntry } from "@/types/hero.types";
import { getPlayerSlug } from "@/lib/player";

import { StatColumnDef } from "../config/stat-columns";
import { teamDotBackground } from "../utils/teamColor";
import RankBadge from "./RankBadge";

/**
 * A stat column plus the value range used to scale its bars. Built once per
 * table render and shared by every row, so bars down a column are comparable
 * and `memo` below actually holds.
 */
export interface StatCellSpec {
  def: StatColumnDef;
  minValue: number;
  maxValue: number;
}

interface BarRowProps {
  entry: HeroLeaderboardEntry;
  rank: number;
  cells: StatCellSpec[];
  isHighlighted: boolean;
  onHoverUser: (userId: number | null) => void;
}

const CELL = "border-b border-[color:var(--aqt-border)] px-3.5 py-2";

const BarRow = ({ entry, rank, cells, isHighlighted, onHoverUser }: BarRowProps) => (
  <tr
    onMouseEnter={() => onHoverUser(entry.user_id)}
    onMouseLeave={() => onHoverUser(null)}
    className={
      isHighlighted
        ? "bg-[color-mix(in_srgb,var(--aqt-teal)_8%,transparent)]"
        : "transition-colors hover:bg-[hsl(0_0%_100%/0.025)]"
    }
  >
    <td className={CELL}>
      <RankBadge rank={rank} />
    </td>
    <td className={CELL}>
      <Link
        href={`/users/${getPlayerSlug(entry.username)}`}
        title={`${entry.username} · ${entry.team ?? "—"} · D${entry.div}`}
        onFocus={() => onHoverUser(entry.user_id)}
        onBlur={() => onHoverUser(null)}
        className="flex min-w-0 items-center gap-2 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
      >
        <span
          aria-hidden
          className="h-2 w-2 shrink-0 rounded-[2px]"
          style={{ background: teamDotBackground(entry.team, entry.team_id) }}
        />
        <span className="truncate text-caption font-medium text-[color:var(--aqt-fg)]">
          {entry.username}
        </span>
      </Link>
    </td>
    {cells.map(({ def, minValue, maxValue }, i) => {
      const value = def.getValue(entry);
      // Min-anchored scaling so the smallest value stays visible (matches mockup).
      const span = maxValue - minValue || 1;
      const barPct = Math.min(Math.max(18 + ((value - minValue) / span) * 82, 0), 100);

      return (
        <td key={`${def.key}-${i}`} className={CELL}>
          <div className="flex items-center gap-[9px]">
            <span className="w-[52px] shrink-0 text-right font-[family-name:var(--aqt-data)] text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]/90">
              {def.formatValue(value)}
            </span>
            <div className="relative h-5 min-w-0 flex-1 overflow-hidden rounded-[4px] bg-[hsl(0_0%_100%/0.03)] ring-1 ring-inset ring-[color:var(--aqt-border-2)]">
              <div
                className={`absolute inset-y-0 left-0 rounded-[4px] transition-[width] duration-500 ${def.barColor}`}
                style={{ width: `${barPct}%`, minWidth: "3px" }}
              />
            </div>
          </div>
        </td>
      );
    })}
  </tr>
);

// Memoized: hovering one player flips `isHighlighted` on only the matching
// row, so every other row skips re-render (`cells` is a memoized array from
// the parent and the remaining props are primitives / stable refs).
export default memo(BarRow);
