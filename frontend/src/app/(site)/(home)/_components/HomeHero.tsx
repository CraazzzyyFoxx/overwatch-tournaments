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
    <HeroFrame
      // Half-strength glow: the hairline and bloom stay, but quieter than PageHero's.
      tint="color-mix(in srgb, var(--aqt-teal) 55%, transparent)"
      className="bg-[linear-gradient(135deg,var(--aqt-bg-2),var(--aqt-bg))]"
    >
      <div className="px-[clamp(20px,3.2vw,40px)] py-[clamp(24px,3.2vw,40px)]">
        <p className={EYEBROW_CLASS}>{t("eyebrow")}</p>
        <h1
          id="home-hero-title"
          className={cn(
            HERO_TITLE_SIZE_CLASS,
            "mt-3 max-w-[22em] text-balance font-display font-semibold leading-[1.08] tracking-[-0.02em] text-[color:var(--aqt-fg)]"
          )}
        >
          {t.rich("title", {
            accent: (chunks) => <span className="text-[color:var(--aqt-teal)]">{chunks}</span>
          })}
        </h1>
        <p className={cn(LEDE_CLASS, "mt-3")}>{t("lede")}</p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <PlayerSearchCombobox
            size="lg"
            placeholder={t("searchPlaceholder")}
            className="min-w-0 max-w-[520px] flex-[1_1_280px] [&_input]:text-base sm:[&_input]:text-ui"
          />
          <Link
            href="/tournaments"
            prefetch={false}
            className={owtButton({ variant: "primary", size: "lg", className: "w-full sm:w-auto" })}
          >
            {t("browseTournaments")}
          </Link>
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-x-6">
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
