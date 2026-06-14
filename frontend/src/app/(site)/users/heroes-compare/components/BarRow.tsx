import Link from "next/link";

import { HeroLeaderboardEntry } from "@/types/hero.types";
import { toUserSlug } from "@/app/(site)/users/components/users-overview/utils";

import RankBadge from "./RankBadge";

interface BarRowProps {
  entry: HeroLeaderboardEntry;
  rank: number;
  value: number;
  maxValue: number;
  barColor: string;
  formatValue: (v: number) => string;
  isEven: boolean;
}

const BarRow = ({ entry, rank, value, maxValue, barColor, formatValue, isEven }: BarRowProps) => {
  const barPct = Math.max((value / maxValue) * 100, 0);
  return (
    <Link
      href={`/users/${toUserSlug(entry.username)}`}
      className={[
        "flex items-center gap-3 px-4 py-[9px]",
        "cursor-pointer transition-colors duration-150 hover:bg-muted/25",
        isEven ? "bg-muted/[0.06]" : "",
      ].join(" ")}
      title={entry.username}
    >
      <RankBadge rank={rank} />
      <span className="w-32 shrink-0 truncate text-right text-sm font-medium leading-normal">
        {entry.username}
      </span>
      <div className="relative h-[22px] flex-1 overflow-hidden rounded-[3px] bg-background/20 ring-1 ring-border/30">
        <div
          className={`absolute inset-y-0 left-0 rounded-[3px] transition-all duration-300 ${barColor}`}
          style={{ width: `${barPct}%`, minWidth: barPct > 0 ? "3px" : "0" }}
        />
      </div>
      <span className="w-14 shrink-0 text-left font-mono text-sm font-semibold tabular-nums text-foreground/85">
        {formatValue(value)}
      </span>
    </Link>
  );
};

export default BarRow;
