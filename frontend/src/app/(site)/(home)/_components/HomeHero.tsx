import { Suspense } from "react";
import Link from "next/link";
import { Trophy } from "lucide-react";
import { useTranslations } from "next-intl";

import { PlayerSearchCombobox } from "@/components/PlayerSearchCombobox";
import { HeroFrame } from "@/components/site/PageHero";
import { LEDE_CLASS } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";

import { HeroFeed } from "./HeroFeed";
import { HeroFeedSkeleton } from "./HeroFeedRotator";
import { HomeProfileLink, TEXT_LINK_CLASS } from "./HomeProfileLink";

/**
 * The landing hero. Left, what the platform is, then the two things a visitor
 * comes for: a player, or the tournament list. Right (below on a phone), the
 * feed of the platform's latest results from real data. The copy waits on no
 * read; the feed streams in behind its own boundary.
 */
export function HomeHero() {
  const t = useTranslations("home.hero");
  const tSearch = useTranslations("nav.search");

  return (
    <HeroFrame
      // Half-strength glow: the hairline and bloom stay, but quieter than PageHero's.
      tint="color-mix(in srgb, var(--aqt-teal) 55%, transparent)"
      className="bg-[linear-gradient(135deg,var(--aqt-bg-2),var(--aqt-bg))]"
    >
      <div className="relative grid grid-cols-[minmax(0,1fr)] items-center gap-x-12 gap-y-8 px-[clamp(20px,3.2vw,40px)] py-[clamp(24px,3.2vw,40px)] min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,460px)]">
        {/* A dot field behind the feed, fading out toward the copy. */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(color-mix(in_srgb,var(--aqt-fg)_7%,transparent)_1px,transparent_1.5px)] bg-[length:22px_22px] [mask-image:radial-gradient(60%_70%_at_78%_50%,var(--aqt-bg),transparent_75%)]"
        />
        <div className="min-w-0 max-w-[620px]">
          <Eyebrow as="p">{t("eyebrow")}</Eyebrow>
          <h1
            id="home-hero-title"
            className="mt-3 text-balance font-display text-display font-bold text-[color:var(--aqt-fg)]"
          >
            {t.rich("title", {
              accent: (chunks) => <span className="text-[color:var(--aqt-teal)]">{chunks}</span>
            })}
          </h1>
          <p className={cn(LEDE_CLASS, "mt-3")}>{t("lede")}</p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <PlayerSearchCombobox
              size="lg"
              placeholder={tSearch("placeholder")}
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

        <Suspense fallback={<HeroFeedSkeleton />}>
          <HeroFeed />
        </Suspense>
      </div>
    </HeroFrame>
  );
}
