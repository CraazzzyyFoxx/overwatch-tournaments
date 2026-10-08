import { useTranslations } from "next-intl";

import { Section, SectionHead, Showcase } from "@/components/site/open-layout";

const TITLE_ID = "home-showcase-title";

/** Screenshots of the live platform — real players, tournaments and matches. */
export function HomeShowcase() {
  const t = useTranslations("home.showcase");

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead rubric={t("rubric")} title={t("title")} titleId={TITLE_ID} sub={t("sub")} />
      <Showcase
        title={t("profile.title")}
        text={t("profile.text")}
        more={{ label: t("profile.more"), href: "/users" }}
        img="player-profile.webp"
        alt={t("profile.alt")}
      />
      <Showcase
        title={t("tournament.title")}
        text={t("tournament.text")}
        more={{ label: t("tournament.more"), href: "/tournaments" }}
        img="tournament-overview.webp"
        alt={t("tournament.alt")}
      />
      <Showcase
        title={t("match.title")}
        text={t("match.text")}
        more={{ label: t("match.more"), href: "/encounters" }}
        img="match.webp"
        alt={t("match.alt")}
      />
    </Section>
  );
}
