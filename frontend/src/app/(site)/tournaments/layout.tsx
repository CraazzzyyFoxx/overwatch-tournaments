import type { Metadata } from "next";
import React from "react";
import { getTranslations } from "next-intl/server";
import { SITE_NAME } from "@/config/site";
import { resolveSiteMetadata } from "@/lib/site-metadata";

export async function generateMetadata(): Promise<Metadata> {
  const { name, origin } = await resolveSiteMetadata();
  const t = await getTranslations();
  const title = `${t("common.tournaments")} | ${SITE_NAME}`;
  const description = t("tournamentsList.meta.description", { siteName: SITE_NAME });
  return {
    title,
    description,
    metadataBase: new URL(origin),
    openGraph: {
      title,
      description,
      url: origin,
      type: "website",
      siteName: name,
      locale: "en_US"
    }
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
