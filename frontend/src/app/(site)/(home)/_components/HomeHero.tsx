import Link from "next/link";
import { Trophy } from "lucide-react";
import { useTranslations } from "next-intl";

import { PlayerSearchCombobox } from "@/components/PlayerSearchCombobox";
import { HeroFrame } from "@/components/site/PageHero";
import { EYEBROW_CLASS, HERO_TITLE_SIZE_CLASS, LEDE_CLASS } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { cn } from "@/lib/utils";

import { HomeProfileLink, TEXT_LINK_CLASS } from "./HomeProfileLink";

/**
 * The landing hero: what the platform is, then the two things a visitor comes
 * for — a player, or the tournament list. Static; nothing here waits on a read.
 */
export function HomeHero() {
  const t = useTranslations("home.hero");

  return (
    <HeroFrame>
      <div className="p-[clamp(22px,2.6vw,36px)]">
        <p className={EYEBROW_CLASS}>{t("eyebrow")}</p>
        <h1
          id="home-hero-title"
          className={cn(
            HERO_TITLE_SIZE_CLASS,
            "mt-3 max-w-[22em] text-balance font-display font-semibold leading-[1.05] tracking-[-0.015em] text-[color:var(--aqt-fg)]"
          )}
        >
          {t.rich("title", {
            accent: (chunks) => <span className="text-[color:var(--aqt-teal)]">{chunks}</span>
          })}
        </h1>
        <p className={cn(LEDE_CLASS, "mt-3")}>{t("lede")}</p>

        <div className="mt-[22px] flex flex-wrap items-center gap-2.5">
          <PlayerSearchCombobox
            size="lg"
            placeholder={t("searchPlaceholder")}
            className="max-w-[520px] flex-[1_1_280px]"
          />
          <Link
            href="/tournaments"
            prefetch={false}
            className={owtButton({ variant: "primary", size: "lg" })}
          >
            {t("browseTournaments")}
          </Link>
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-[22px]">
          <HomeProfileLink />
          <Link href="/get-workspace" prefetch={false} className={TEXT_LINK_CLASS}>
            <Trophy aria-hidden />
            {t("hostTournament")}
          </Link>
        </div>
      </div>
    </HeroFrame>
  );
}
