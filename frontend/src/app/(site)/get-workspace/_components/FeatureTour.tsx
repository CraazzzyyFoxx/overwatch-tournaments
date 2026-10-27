import { getLocale, getTranslations } from "next-intl/server";
import {
  ChartColumn,
  ClipboardList,
  CodeXml,
  Layers,
  ListChecks,
  Network,
  Scale,
  ShieldCheck,
  Shuffle,
  Table2,
  Users
} from "lucide-react";

import { Section, SECTION_TITLE_CLASS } from "@/components/site/open-layout";
import { OrganizerTabs, type OrganizerTab } from "@/components/site/OrganizerTabs";

import { MoreFeatures, type MoreFeature } from "./MoreFeatures";

/** The tour's tabs, in the order a tournament happens; `docs` sets each one up. Every capture is 2880×2000. */
const SHOTS = [
  { key: "form", Icon: ClipboardList, img: "admin-form.webp", docs: "/docs/organizers/registration" },
  { key: "registration", Icon: ListChecks, img: "registration.webp", docs: "/docs/organizers/registration" },
  { key: "entries", Icon: Table2, img: "admin-registrations.webp", docs: "/docs/organizers/registration" },
  { key: "stages", Icon: Layers, img: "admin-bracket.webp", docs: "/docs/organizers/brackets" },
  { key: "bracket", Icon: Network, img: "bracket.webp", docs: "/docs/organizers/brackets" },
  { key: "mapStats", Icon: ChartColumn, img: "map-stats.webp", docs: "/docs/organizers/logs" }
] as const;

/** What the tour does not show, each with its real capture (per interface language where there are two) and docs article. */
const MORE = [
  {
    key: "balancer",
    Icon: Scale,
    src: () => "/showcase/balancer.webp",
    width: 2708,
    height: 2032,
    docs: "/docs/organizers/team-formation"
  },
  { key: "draft", Icon: Users, src: () => "/showcase/draft.webp", width: 2880, height: 1896, docs: "/docs/organizers/draft" },
  {
    key: "mixes",
    Icon: Shuffle,
    src: (language: "ru" | "en") => `/changelog/2.0.0/mix-room.${language}.webp`,
    width: 2400,
    height: 1380,
    docs: "/docs/organizers/mixes"
  },
  { key: "roles", Icon: ShieldCheck, src: () => "/showcase/roles.webp", width: 2880, height: 2000, docs: "/docs/organizers/roles" },
  { key: "api", Icon: CodeXml, src: () => "/showcase/api-keys.webp", width: 1344, height: 1458, docs: "/docs/dev/api" }
] as const;

/**
 * The organizer page's product tour: the home banner's tabs (`OrganizerTabs`)
 * over six steps of a tournament, each with its docs link, then the bento of
 * what the tabs do not show (`MoreFeatures`).
 */
export async function FeatureTour() {
  const [t, locale] = await Promise.all([getTranslations("getWorkspace.features"), getLocale()]);
  const language = locale === "ru" ? "ru" : "en";

  const tabs: OrganizerTab[] = SHOTS.map(({ key, Icon, img, docs }) => ({
    key,
    icon: <Icon aria-hidden />,
    title: t(`shots.${key}.title` as const),
    text: t(`shots.${key}.text` as const),
    page: t(`shots.${key}.page` as const),
    alt: t(`shots.${key}.alt` as const),
    src: `/showcase/${img}`,
    width: 2880,
    height: 2000,
    href: docs
  }));

  const more: MoreFeature[] = MORE.map(({ key, Icon, src, width, height, docs }) => ({
    key,
    icon: <Icon aria-hidden />,
    title: t(`grid.${key}.title` as const),
    text: t(`grid.${key}.text` as const),
    alt: t(`grid.${key}.alt` as const),
    href: docs,
    src: src(language),
    width,
    height
  }));

  return (
    <Section labelledBy="gw-feat-title">
      <OrganizerTabs
        tabs={tabs}
        labels={{ inside: t("inside"), pause: t("pause"), play: t("play"), link: t("howTo") }}
        textLines={3}
      >
        <h2 id="gw-feat-title" className={SECTION_TITLE_CLASS}>
          {t("title")}
        </h2>
      </OrganizerTabs>
      <MoreFeatures features={more} labels={{ title: t("more"), docs: t("docs"), howTo: t("howTo") }} />
    </Section>
  );
}
