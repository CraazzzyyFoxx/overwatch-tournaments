import React from "react";
import Image from "next/image";

import { Badge } from "@/components/ui/badge";
import { UserOverviewRow } from "@/types/user.types";

import { formatOptional, formatPlaytime, HERO_METRIC_LABELS } from "./utils";

const ExpandedUserRow = ({ user }: { user: UserOverviewRow }) => {
  return (
    <div className="space-y-4 rounded-lg border border-border/70 bg-background/35 p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Avg placement</p>
          <p className="font-medium">{formatOptional(user.averages.avg_placement)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Avg playoff</p>
          <p className="font-medium">{formatOptional(user.averages.avg_playoff_placement)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Avg group</p>
          <p className="font-medium">{formatOptional(user.averages.avg_group_placement)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Avg closeness</p>
          <p className="font-medium">{formatOptional(user.averages.avg_closeness)}</p>
        </div>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Top heroes details</p>
        <p className="mb-2 text-xs text-muted-foreground">Note: all hero metrics are averages per 10 minutes.</p>
        {user.top_heroes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No hero data.</p>
        ) : (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {user.top_heroes.map((heroRow) => (
              <div key={`${user.id}-${heroRow.hero.id}`} className="rounded-md border border-border/60 bg-background/45 p-2">
                <div className="mb-2 flex items-center gap-2">
                  <Image
                    src={heroRow.hero.image_path}
                    alt={heroRow.hero.name}
                    width={34}
                    height={34}
                    className="h-[34px] w-[34px] rounded-full border border-border/60 object-cover"
                  />
                  <div>
                    <p className="text-sm font-medium">{heroRow.hero.name}</p>
                    <p className="text-xs text-muted-foreground">Playtime: {formatPlaytime(heroRow.playtime_seconds)}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {heroRow.metrics.length === 0 ? (
                    <span className="text-xs text-muted-foreground">No metrics</span>
                  ) : (
                    heroRow.metrics.map((metric) => (
                      <Badge key={`${heroRow.hero.id}-${metric.name}`} variant="outline" className="text-[12px]">
                        {HERO_METRIC_LABELS[metric.name] ?? metric.name}: {metric.avg_10.toFixed(2)}
                      </Badge>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default React.memo(ExpandedUserRow);
