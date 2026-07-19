import React from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { UserOverviewRow } from "@/types/user.types";

import { formatOptional, formatPlaytime, HERO_METRIC_LABEL_KEYS } from "./utils";

const ExpandedUserRow = ({ user }: { user: UserOverviewRow }) => {
  const t = useTranslations();

  return (
    <div className="space-y-4 rounded-lg border border-border/70 bg-background/35 p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">{t("users.list.expanded.avgPlacement")}</p>
          <p className="font-medium">{formatOptional(user.averages.avg_placement)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t("users.list.expanded.avgPlayoff")}</p>
          <p className="font-medium">{formatOptional(user.averages.avg_playoff_placement)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t("users.list.expanded.avgGroup")}</p>
          <p className="font-medium">{formatOptional(user.averages.avg_group_placement)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t("users.list.expanded.avgCloseness")}</p>
          <p className="font-medium">{formatOptional(user.averages.avg_closeness)}</p>
        </div>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">{t("users.list.expanded.topHeroesDetails")}</p>
        <p className="mb-2 text-xs text-muted-foreground">{t("users.list.expanded.metricsNote")}</p>
        {user.top_heroes.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("users.list.expanded.noHeroData")}</p>
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
                    <p className="text-xs text-muted-foreground">
                      {t("users.list.expanded.playtime", { value: formatPlaytime(heroRow.playtime_seconds, t) })}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {heroRow.metrics.length === 0 ? (
                    <span className="text-xs text-muted-foreground">{t("users.list.expanded.noMetrics")}</span>
                  ) : (
                    heroRow.metrics.map((metric) => {
                      const metricKey = HERO_METRIC_LABEL_KEYS[metric.name];
                      const metricLabel = metricKey ? t(metricKey) : metric.name;
                      return (
                        <Badge key={`${heroRow.hero.id}-${metric.name}`} variant="outline" className="text-[12px]">
                          {metricLabel}: {metric.avg_10.toFixed(2)}
                        </Badge>
                      );
                    })
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
