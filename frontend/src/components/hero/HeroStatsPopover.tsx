import React from "react";
import Image from "next/image";
import { UserMapHeroStats } from "@/types/user.types";
import { Progress } from "@/components/ui/progress";
import { getWinrateColor } from "@/utils/colors";
import { formatPercent, formatSeconds } from "@/app/(site)/users/components/user-maps-explorer/utils";

/**
 * Reusable hero-stats popover body (winrate / games / record / playtime share).
 * Pass as the `popover` prop of <HeroImage> to attach stats to a hero avatar —
 * this is the standard way to surface per-hero stats (as on the Maps tab).
 */
export const HeroStatsPopover = ({ stats }: { stats: UserMapHeroStats }) => {
  const winrateColor = getWinrateColor(stats.win_rate);
  const shareValue = Math.max(0, Math.min(100, stats.playtime_share_on_map * 100));

  return (
    <>
      <div className="flex items-start gap-3">
        <div className="h-12 w-12 shrink-0">
          <Image
            src={stats.hero.image_path}
            alt={stats.hero.name}
            width={48}
            height={48}
            className="h-full w-full object-contain select-none"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{stats.hero.name}</div>
          <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
            <div className="rounded-md border border-border/50 bg-muted/10 px-2 py-1">
              <div className="text-muted-foreground">Winrate</div>
              <div className="font-semibold tabular-nums" style={{ color: winrateColor }}>
                {formatPercent(stats.win_rate, 0)}
              </div>
            </div>
            <div className="rounded-md border border-border/50 bg-muted/10 px-2 py-1">
              <div className="text-muted-foreground">Games</div>
              <div className="font-semibold tabular-nums">{stats.games}</div>
            </div>
            <div className="rounded-md border border-border/50 bg-muted/10 px-2 py-1">
              <div className="text-muted-foreground">Record</div>
              <div className="font-semibold tabular-nums">
                {stats.win}-{stats.loss}-{stats.draw}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Playtime on this map</span>
          <span className="tabular-nums">
            {formatSeconds(stats.playtime_seconds)} | {shareValue.toFixed(0)}%
          </span>
        </div>
        <div className="mt-2">
          <Progress value={shareValue} aria-label="Playtime share on this map" />
        </div>
        <div className="mt-2 text-[11px] text-muted-foreground">
          Games counted when hero time played is &gt; 60s.
        </div>
      </div>
    </>
  );
};

export default HeroStatsPopover;
