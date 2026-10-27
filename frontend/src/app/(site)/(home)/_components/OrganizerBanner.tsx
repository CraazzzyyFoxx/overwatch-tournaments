import Link from "next/link";
import { ArrowRight, ChartColumn, ClipboardList, Network, Scale } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";

import { LEDE_CLASS, SECTION_TITLE_CLASS } from "@/components/site/open-layout";
import { OrganizerTabs } from "@/components/site/OrganizerTabs";
import { owtButton } from "@/components/site/owt-button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";

import { FEATURES } from "./PlatformFeatures";

/** The tabs, in order, each with its icon; the screenshot is the features block's own. */
const TABS = [
  ["registration", ClipboardList],
  ["balancer", Scale],
  ["brackets", Network],
  ["matches", ChartColumn]
] as const;

/**
 * The page's one organizer CTA (mock O2a): the pitch and its button beside
 * four feature tabs, each showing the real screenshot of what it names.
 */
export async function OrganizerBanner() {
  const [t, locale] = await Promise.all([getTranslations("home"), getLocale()]);
  const language = locale === "ru" ? "ru" : "en";
  const tabs = TABS.flatMap(([key, Icon]) => {
    const feature = FEATURES.find((candidate) => candidate.key === key);
    return feature
      ? [
          {
            key,
            icon: <Icon aria-hidden />,
            title: t(`organizer.tabs.${key}.title` as const),
            text: t(`organizer.tabs.${key}.text` as const),
            page: t(`organizer.tabs.${key}.page` as const),
            alt: t(`features.${key}.alt` as const),
            src: feature.src(language),
            width: feature.width,
            height: feature.height
          }
        ]
      : [];
  });

  return (
    <OrganizerTabs
      tabs={tabs}
      labels={{ inside: t("organizer.inside"), pause: t("organizer.pause"), play: t("organizer.play") }}
      cta={
        <Link
          href="/get-workspace"
          prefetch={false}
          className={cn(owtButton({ variant: "primary", size: "lg" }), "w-full sm:w-auto")}
        >
          {t("organizer.cta")}
          <ArrowRight aria-hidden />
        </Link>
      }
    >
      <Eyebrow as="p">{t("organizer.eyebrow")}</Eyebrow>
      <h2 id="home-org-title" className={cn(SECTION_TITLE_CLASS, "mt-3 font-semibold")}>
        {t("organizer.title")}
      </h2>
      <p className={cn(LEDE_CLASS, "mt-3")}>{t("organizer.lede")}</p>
    </OrganizerTabs>
  );
}
