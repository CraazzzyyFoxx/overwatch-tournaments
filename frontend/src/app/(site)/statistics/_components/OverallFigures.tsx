import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import { HeroStat } from "@/components/site/PageHero";
import { OpenEmptyRow, OpenLoadError } from "@/components/site/open-layout";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { isTenantHost } from "@/lib/site/tenant-host";
import statisticsService from "@/services/statistics.service";
import type { TournamentOverall } from "@/types/statistics.types";

const FIGURES = [
  "tournaments",
  "players",
  "encounters",
  "maps",
  "hours",
  "days"
] as const satisfies readonly (keyof TournamentOverall)[];

const GRID_CLASS = "grid w-full grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6";

/** The platform's all-time totals under the page title: open figures, game-neutral. */
export async function OverallFigures() {
  const skipWorkspace = !(await isTenantHost());
  const [t, format, overall] = await Promise.all([
    getTranslations("statistics.figures"),
    getFormatter(),
    statisticsService.getOverallStatistics({ skipWorkspace }).catch(() => null)
  ]);

  if (overall === null) return <OpenLoadError what={t("what")} />;
  if (overall.tournaments === 0) return <OpenEmptyRow>{t("empty")}</OpenEmptyRow>;

  return (
    <div className={GRID_CLASS}>
      {FIGURES.map((key) => (
        <HeroStat key={key} label={t(key)} value={format.number(overall[key])} />
      ))}
    </div>
  );
}

export function OverallFiguresSkeleton() {
  const t = useTranslations("statistics.figures");
  return (
    <div aria-hidden className={GRID_CLASS}>
      {FIGURES.map((key) => (
        <HeroStat key={key} label={t(key)} value={<Skeleton className="h-8 w-20" />} />
      ))}
    </div>
  );
}
