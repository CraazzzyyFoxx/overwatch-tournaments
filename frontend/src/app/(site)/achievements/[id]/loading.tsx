import { useTranslations } from "next-intl";

import { CardSurface } from "@/components/profile/atoms";
import { HeroFrame } from "@/components/site/PageHero";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Mirrors the detail page: the crest hero (`AchievementDetailHeader`), "How to
 * earn" with its canvas, then the earners list in its own loading rows.
 */
export default function Loading() {
  const t = useTranslations();
  return (
    <div aria-busy className="aqt-player space-y-6">
      <HeroFrame>
        <div className="flex flex-col gap-7 px-6 py-8 md:px-10 md:py-9 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-start">
            <Skeleton className="aspect-square w-[clamp(96px,12vw,132px)] shrink-0 rounded-2xl" />
            <div className="flex min-w-0 flex-col gap-3">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-10 w-72 max-w-full" />
              <Skeleton className="h-4 w-96 max-w-full" />
              <div className="mt-1 flex gap-2">
                <Skeleton className="h-6 w-20 rounded-full" />
                <Skeleton className="h-6 w-24 rounded-full" />
              </div>
            </div>
          </div>
          <div className="flex shrink-0 gap-x-10 gap-y-5 border-t border-[color:var(--aqt-border)] pt-6 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-10">
            <Skeleton className="h-12 w-20" />
            <Skeleton className="h-12 w-20" />
          </div>
        </div>
      </HeroFrame>

      <CardSurface title={t("achievements.conditionText.title")}>
        <div className="space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
        <Skeleton className="mt-5 h-[420px] w-full rounded-lg" />
      </CardSurface>

      <CardSurface className="min-w-0" title={t("achievements.detail.earnedBy")} flush>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="grid grid-cols-[34px_1fr_auto] items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-4.5 py-2.75 last:border-b-0">
            <Skeleton className="h-4 w-5 justify-self-end" />
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-8 justify-self-end" />
          </div>
        ))}
      </CardSurface>
    </div>
  );
}
