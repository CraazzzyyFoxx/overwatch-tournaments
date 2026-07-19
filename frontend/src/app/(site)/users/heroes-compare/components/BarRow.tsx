import { memo } from "react";
import Link from "next/link";

import { HeroLeaderboardEntry } from "@/types/hero.types";
import { toUserSlug } from "@/app/(site)/users/components/users-overview/utils";

import { teamDotBackground } from "../utils/teamColor";
import RankBadge from "./RankBadge";

interface BarRowProps {
  entry: HeroLeaderboardEntry;
  rank: number;
  value: number;
  minValue: number;
  maxValue: number;
  barColor: string;
  formatValue: (v: number) => string;
  isHighlighted: boolean;
  onHoverUser: (userId: number | null) => void;
}

const BarRow = ({
  entry,
  rank,
  value,
  minValue,
  maxValue,
  barColor,
  formatValue,
  isHighlighted,
  onHoverUser,
}: BarRowProps) => {
  // Min-anchored scaling so the smallest value stays visible (matches mockup).
  const span = maxValue - minValue || 1;
  const barPct = Math.min(Math.max(18 + ((value - minValue) / span) * 82, 0), 100);

  return (
    <Link
      href={`/users/${toUserSlug(entry.username)}`}
      title={`${entry.username} · ${entry.team ?? "—"} · D${entry.div}`}
      onMouseEnter={() => onHoverUser(entry.user_id)}
      onMouseLeave={() => onHoverUser(null)}
      className={[
        "grid grid-cols-[26px_116px_1fr_52px] items-center gap-[9px] border-b border-[color:var(--aqt-border)] px-3.5 py-2",
        "cursor-pointer transition-colors",
        isHighlighted
          ? "bg-[color-mix(in_srgb,var(--aqt-teal)_8%,transparent)]"
          : "hover:bg-[hsl(0_0%_100%/0.025)]",
      ].join(" ")}
    >
      <RankBadge rank={rank} />
      <div className="flex min-w-0 items-center gap-2">
        <span
          className="h-2 w-2 shrink-0 rounded-[2px]"
          style={{ background: teamDotBackground(entry.team, entry.team_id) }}
        />
        <span className="truncate text-[13px] font-medium text-[var(--aqt-fg)]">
          {entry.username}
        </span>
      </div>
      <div className="relative h-5 overflow-hidden rounded-[4px] bg-[hsl(0_0%_100%/0.03)] ring-1 ring-inset ring-[var(--aqt-border-2)]">
        <div
          className={`absolute inset-y-0 left-0 rounded-[4px] transition-[width] duration-500 ${barColor}`}
          style={{ width: `${barPct}%`, minWidth: barPct > 0 ? "3px" : "0" }}
        />
      </div>
      <span className="text-right font-[family-name:var(--aqt-mono)] text-[12.5px] font-semibold tabular-nums text-[var(--aqt-fg)]/90">
        {formatValue(value)}
      </span>
    </Link>
  );
};

// Memoized: hovering one player flips `isHighlighted` on only the matching
// rows, so unchanged rows across all 5 columns skip re-render (props are
// stable refs / primitives from the module-level COL config).
export default memo(BarRow);
