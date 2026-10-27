import { memo } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { HandleLabel } from "@/components/HandleLabel";
import { TableCell, TableRow } from "@/components/ui/table";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { formatSeconds } from "@/lib/format";
import { getPlayerSlug } from "@/lib/player";
import { cn } from "@/lib/utils";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

import { beatsShare, heatTier, type RankedEntry } from "./board";
import RankBadge from "./RankBadge";
import { StatColumnDef } from "./stat-columns";

/**
 * A stat column plus its values over every ranked player (ascending), so a cell's tint reads as the share of the
 * board it beats. Built once per table render and shared by every row, so `memo` below holds.
 */
export interface StatCellSpec {
  def: StatColumnDef;
  sorted: number[];
}

/** The cells carry the hairline: the table is `border-separate` (for the sticky columns), where row borders draw nothing. */
export const CELL = "border-b border-[color:var(--aqt-border)] px-3 py-2";
/** The rank and player columns stay put while a phone scrolls the stat columns under them. */
export const STICKY_RANK = "sticky left-0 z-[1]";
export const STICKY_PLAYER = "sticky left-[52px] z-[1] max-lg:shadow-[inset_-1px_0_0_var(--aqt-border)]";
/** Opaque, so the scrolled columns never show through the sticky ones. */
const ROW_BG = "bg-[color:var(--aqt-card)]";
const ROW_HIGHLIGHT = "bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,var(--aqt-card))]";

/** The heat map: one hue, deeper the more of the board a value beats; the bottom tenth fades instead. */
const HEAT: Record<0 | 1 | 2 | 3 | 4, string> = {
  4: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_30%,transparent)] font-semibold text-[color:color-mix(in_srgb,var(--aqt-teal)_40%,var(--aqt-fg))]",
  3: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_17%,transparent)] font-semibold text-[color:var(--aqt-fg)]",
  2: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,transparent)] font-semibold text-[color:var(--aqt-fg)]",
  1: "font-semibold text-[color:var(--aqt-fg)]",
  0: "font-medium text-[color:var(--aqt-fg-faint)]"
};

/** The player's division crest on the grid the number belongs to, its tier name in the tooltip (DESIGN.md); none without a division. */
const DivisionCrest = ({
  division,
  grid,
  discipline
}: Readonly<{ division: number | null; grid: DivisionGridVersion | DivisionGrid; discipline: string }>) => {
  const t = useTranslations();
  if (division === null) return null;
  const name = getDivisionLabel(grid, division) ?? t("common.divisionWithId", { id: String(division) });
  return (
    <span title={name} className="inline-flex size-5 shrink-0 items-center justify-center">
      <DivisionIcon division={division} tournamentGrid={grid} discipline={discipline} width={20} height={20} />
    </span>
  );
};

interface LeaderboardRowProps {
  ranked: RankedEntry;
  cells: StatCellSpec[];
  /** The grid this row's `div` is a number on: its own version, else the read's grid. */
  grid: DivisionGridVersion | DivisionGrid;
  discipline: string;
  isHighlighted: boolean;
  onHoverUser: (userId: number | null) => void;
}

const LeaderboardRow = ({
  ranked: { entry, rank },
  cells,
  grid,
  discipline,
  isHighlighted,
  onHoverUser
}: LeaderboardRowProps) => {
  const t = useTranslations();
  const bg = isHighlighted ? ROW_HIGHLIGHT : ROW_BG;

  return (
    <TableRow onMouseEnter={() => onHoverUser(entry.user_id)} onMouseLeave={() => onHoverUser(null)}>
      <TableCell className={cn(CELL, STICKY_RANK, bg)}>
        <RankBadge rank={rank} />
      </TableCell>
      <TableCell className={cn(CELL, STICKY_PLAYER, bg)}>
        <div className="flex min-w-0 items-center gap-2">
          <DivisionCrest division={entry.div} grid={grid} discipline={discipline} />
          <Link
            href={`/users/${getPlayerSlug(entry.username)}`}
            title={entry.team ? `${entry.username} · ${entry.team}` : entry.username}
            onFocus={() => onHoverUser(entry.user_id)}
            onBlur={() => onHoverUser(null)}
            className="min-w-0 truncate rounded-sm text-caption font-semibold text-[color:var(--aqt-fg)] outline-hidden hover:text-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          >
            <HandleLabel handle={entry.username} />
          </Link>
        </div>
      </TableCell>
      <TableCell className={cn(CELL, "text-right leading-tight", bg)}>
        <span className="block text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]">
          {entry.games_played}
        </span>
        <span className="block text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
          {formatSeconds(entry.playtime_seconds)}
        </span>
      </TableCell>
      {cells.map(({ def, sorted }, i) => {
        const value = def.getValue(entry);
        const share = beatsShare(sorted, value, def.ascending);
        return (
          <TableCell
            key={`${def.key}-${i}`}
            title={t("users.heroesCompare.table.beats", { value: Math.round(share * 100) })}
            className={cn(CELL, "text-center", isHighlighted && ROW_HIGHLIGHT)}
          >
            <span
              className={cn(
                "inline-block min-w-[68px] rounded-md px-2.5 py-1 text-right text-caption tabular-nums",
                HEAT[heatTier(share)]
              )}
            >
              {def.formatValue(value)}
            </span>
          </TableCell>
        );
      })}
    </TableRow>
  );
};

// Memoized: hovering one player flips `isHighlighted` on only the matching
// row, so every other row skips re-render (`cells` is a memoized array from
// the parent and the remaining props are primitives / stable refs).
export default memo(LeaderboardRow);
