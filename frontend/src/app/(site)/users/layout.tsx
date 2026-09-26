// Profile-specific global CSS, loaded with this route's chunk rather than from
// globals.css. The achievements sheet comes along because the profile's
// achievements tab renders the same `.aqt-ach-*` / `.aqt-rar-*` markup.
import "../achievements/achievements.css";
import "./user-profile.css";

import type { Metadata } from "next";
import React from "react";
import { getTranslations } from "next-intl/server";
import { SITE_NAME } from "@/config/site";
import { buildSectionMetadata } from "@/lib/site/metadata";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations();
  const title = `${t("users.list.meta.title")} | ${SITE_NAME}`;
  const description = t("users.list.meta.description", { siteName: SITE_NAME });
  return buildSectionMetadata(title, description);
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
