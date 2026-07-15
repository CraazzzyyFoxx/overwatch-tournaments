"use client";

import Link from "next/link";
import { ChevronRight, CircleHelp, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import type { CompareScope } from "@/app/(site)/users/compare/types";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { UserCompareBaselineMode } from "@/types/user.types";

import { getComparePageHeroModel } from "./compare-page-hero.model";

interface ComparePageHeroProps {
  hasSubject: boolean;
  hasData: boolean;
  isLoading: boolean;
  isRefreshing: boolean;
  scope: CompareScope;
  baseline: UserCompareBaselineMode;
  baselineSummary: string;
  sampleSize?: number;
  metricCount: number;
}

const ComparePageHero = ({
  hasSubject,
  hasData,
  isLoading,
  isRefreshing,
  scope,
  baseline,
  baselineSummary,
  sampleSize,
  metricCount
}: ComparePageHeroProps) => {
  const t = useTranslations();
  const model = getComparePageHeroModel({
    hasSubject,
    hasData,
    isLoading,
    scope,
    baseline,
    sampleSize,
    metricCount
  });

  const baselineLabel = {
    global: t("users.compare.hero.global"),
    cohort: t("users.compare.hero.cohort"),
    target_user: t("users.compare.hero.target")
  }[model.baseline];

  const stats = [
    {
      label: t("users.compare.hero.scope"),
      value:
        model.scope === "hero" ? t("users.compare.hero.heroMap") : t("users.compare.hero.overall"),
      sub: t("users.compare.hero.activeView")
    },
    {
      label: t("users.compare.hero.baseline"),
      value: baselineLabel,
      sub: baselineSummary
    },
    {
      label: t("users.compare.hero.sample"),
      value: model.sampleSize,
      sub: t("users.compare.hero.players")
    },
    {
      label: t("users.compare.hero.metrics"),
      value: model.metricCount,
      sub: isRefreshing ? t("users.compare.hero.refreshing") : t("users.compare.hero.metricsReady"),
      refreshing: isRefreshing
    }
  ];

  return (
    <PageHero
      eyebrow={
        <HeroCoord className="inline-flex items-center gap-2">
          <Link href="/users" className="transition-colors hover:text-[color:var(--aqt-teal)]">
            {t("users.compare.hero.usersBreadcrumb")}
          </Link>
          <ChevronRight className="h-3 w-3 opacity-50" />
          <span>{t("users.compare.hero.breadcrumb")}</span>
        </HeroCoord>
      }
      title={t.rich("users.compare.hero.title", {
        em: (chunks) => <em>{chunks}</em>
      })}
      lede={t("users.compare.hero.lede")}
      actions={
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 text-xs font-semibold text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-border-strong)] hover:text-[color:var(--aqt-fg)]"
            >
              <CircleHelp className="h-4 w-4" />
              {t("users.compare.hero.guideAction")}
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-90 max-w-[calc(100vw-2rem)]">
            <div className="space-y-2">
              <div className="font-onest text-sm font-bold text-[color:var(--aqt-fg)]">
                {t("users.compare.guide.heading")}
              </div>
              <ol className="list-decimal space-y-1.5 pl-4 text-sm text-[color:var(--aqt-fg-muted)]">
                <li>{t("users.compare.guide.step1")}</li>
                <li>{t("users.compare.guide.step2")}</li>
                <li>{t("users.compare.guide.step3")}</li>
                <li>{t("users.compare.guide.step4")}</li>
                <li>{t("users.compare.guide.step5")}</li>
                <li>{t("users.compare.guide.step6")}</li>
              </ol>
            </div>
          </PopoverContent>
        </Popover>
      }
      aside={
        <div className="grid grid-cols-2 gap-x-7 gap-y-5 text-left lg:text-right">
          {stats.map((stat) => (
            <div key={stat.label} className="min-w-0 lg:flex lg:flex-col lg:items-end">
              <span className="text-[9.5px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                {stat.label}
              </span>
              <span className="mt-1 block max-w-full truncate font-onest text-[clamp(1.35rem,2vw,1.9rem)] font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">
                {stat.value}
              </span>
              <span className="mt-1 flex max-w-full items-center gap-1 truncate text-[10.5px] text-[color:var(--aqt-fg-dim)]">
                {stat.refreshing ? <RefreshCw className="h-3 w-3 shrink-0 animate-spin" /> : null}
                <span className="truncate">{stat.sub}</span>
              </span>
            </div>
          ))}
        </div>
      }
    />
  );
};

export default ComparePageHero;
