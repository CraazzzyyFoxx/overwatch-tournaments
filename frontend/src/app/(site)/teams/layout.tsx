import type { Metadata } from "next";
import React from "react";
import { getTranslations } from "next-intl/server";
import { SITE_NAME } from "@/config/site";
import { buildSectionMetadata } from "@/lib/site/metadata";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations();
  const title = `${t("common.teams")} | ${SITE_NAME}`;
  const description = t("teams.meta.description", { siteName: SITE_NAME });
  return buildSectionMetadata(title, description);
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
