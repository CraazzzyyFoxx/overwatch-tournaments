import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroFrame } from "@/components/site/PageHero";
import { EYEBROW_CLASS, LEDE_CLASS, SECTION_TITLE_CLASS } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { cn } from "@/lib/utils";

/** The page's one organizer CTA (mock `.org`). */
export function OrganizerBanner() {
  const t = useTranslations("home.organizer");

  return (
    <HeroFrame variant="plain">
      <div className="grid grid-cols-1 items-center gap-x-10 gap-y-6 px-[clamp(20px,4vw,48px)] py-[clamp(28px,3.5vw,44px)] md:grid-cols-[minmax(0,1fr)_auto]">
        <div>
          <p className={cn(EYEBROW_CLASS, "normal-case tracking-normal")}>{t("eyebrow")}</p>
          <h2 id="home-org-title" className={cn(SECTION_TITLE_CLASS, "mt-3 font-semibold")}>
            {t("title")}
          </h2>
          <p className={cn(LEDE_CLASS, "mt-3")}>{t("lede")}</p>
        </div>
        <Link
          href="/get-workspace"
          prefetch={false}
          className={cn(owtButton({ variant: "primary", size: "lg" }), "w-full justify-self-start sm:w-auto")}
        >
          {t("cta")}
          <ArrowRight aria-hidden />
        </Link>
      </div>
    </HeroFrame>
  );
}
