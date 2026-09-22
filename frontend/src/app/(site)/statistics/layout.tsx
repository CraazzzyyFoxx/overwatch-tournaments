import type { Metadata } from "next";
import React from "react";
import { getTranslations } from "next-intl/server";
import { SITE_NAME } from "@/config/site";
import { buildSectionMetadata } from "@/lib/site/metadata";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations();
  const title = `${t("statistics.navTitle")} | ${SITE_NAME}`;
  const description = t("statistics.metaDescription", { siteName: SITE_NAME });
  return buildSectionMetadata(title, description);
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
