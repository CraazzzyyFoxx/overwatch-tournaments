import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SITE_NAME, SITE_URL } from "@/config/site";
import encounterService from "@/services/encounter.service";

export async function generateMetadata(props: {
  params: Promise<{ slug: string; encounterId: string }>;
}): Promise<Metadata> {
  const params = await props.params;
  const t = await getTranslations();
  const url = `${SITE_URL}/tournaments/${params.slug}/pregame/${params.encounterId}`;

  // The room is reachable before the bracket resolves either side, and a
  // private tournament answers 404 to a crawler: neither may throw out of
  // metadata, so both fall back to the room's own name.
  let title = `${t("pickBan.room.title")} | ${SITE_NAME}`;
  let description = t("pickBan.room.metaDescriptionFallback", { siteName: SITE_NAME });
  try {
    const encounter = await encounterService.getEncounter(Number(params.encounterId));
    const home = encounter.home_team?.name ?? t("common.tbd");
    const away = encounter.away_team?.name ?? t("common.tbd");
    title = `${t("pickBan.room.metaTitle", { home, away })} | ${SITE_NAME}`;
    description = t("pickBan.room.metaDescription", { home, away, siteName: SITE_NAME });
  } catch (error) {
    console.error(`pregame metadata: failed to load encounter ${params.encounterId}:`, error);
  }

  return {
    title,
    description,
    alternates: { canonical: url },
    // No `openGraph.images` here on purpose: the colocated `opengraph-image`
    // route is injected by the file convention.
    openGraph: { title, description, url, siteName: SITE_NAME, type: "website" },
    twitter: { card: "summary_large_image", title, description }
  };
}

export default function PregameLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
