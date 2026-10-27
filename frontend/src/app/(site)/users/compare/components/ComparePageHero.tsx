"use client";

import Link from "next/link";
import { ChevronRight, CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";

import type { CompareScope } from "@/app/(site)/users/compare/types";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { GameFilterHint } from "@/components/workspace/GameFilterHint";

interface ComparePageHeroProps {
  /**
   * Under "all games" the page shows one game it picked itself: its name, worn by a chip that opens the site's game
   * switcher. `null` when the switcher already names the game.
   */
  gameHint: string | null;
  scope: CompareScope;
  onScopeChange: (scope: CompareScope) => void;
}

/** The page's header (the comparison starts right under it): which game, and what is compared. */
const ComparePageHero = ({ gameHint, scope, onScopeChange }: ComparePageHeroProps) => {
  const t = useTranslations();

  return (
    <PageHero
      compact
      eyebrow={
        <HeroCoord className="inline-flex items-center gap-2">
          <Link href="/users" className="transition-colors hover:text-[color:var(--aqt-teal)]">
            {t("users.compare.hero.usersBreadcrumb")}
          </Link>
          <ChevronRight aria-hidden className="h-3 w-3 opacity-50" />
          <span>{t("users.compare.hero.breadcrumb")}</span>
        </HeroCoord>
      }
      title={t("users.compare.hero.title")}
      lede={t("users.compare.hero.lede")}
      actions={
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm">
              <CircleHelp aria-hidden />
              {t("users.compare.hero.guideAction")}
            </Button>
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
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center lg:justify-end">
          {gameHint ? (
            <GameFilterHint className="self-start sm:self-auto">
              {t("common.discipline.gameHint", { game: gameHint })}
            </GameFilterHint>
          ) : null}
          <ToggleGroup
            variant="pill"
            size="sm"
            value={scope}
            onValueChange={(value) => onScopeChange(value as CompareScope)}
            aria-label={t("users.compare.filters.compareScope")}
            className="w-full sm:w-auto"
          >
            <ToggleGroupItem value="overall" className="flex-1 whitespace-nowrap">
              {t("users.compare.filters.overallPerformance")}
            </ToggleGroupItem>
            <ToggleGroupItem value="hero" className="flex-1 whitespace-nowrap">
              {t("users.compare.filters.heroMapPerformance")}
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      }
    />
  );
};

export default ComparePageHero;
