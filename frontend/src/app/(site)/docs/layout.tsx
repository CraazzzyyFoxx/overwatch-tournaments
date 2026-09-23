import type { Metadata } from "next";
import type { ReactNode } from "react";
import { getLocale, getTranslations } from "next-intl/server";

import { DocsShell } from "./DocsShell";
import { docSections, toDocLocale } from "./nav";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("docs");
  return { title: `${t("title")} · OWT`, description: t("lead") };
}

export default async function DocsLayout({ children }: Readonly<{ children: ReactNode }>) {
  const [locale, t] = await Promise.all([getLocale(), getTranslations("docs")]);
  const sections = docSections(toDocLocale(locale), {
    players: t("sections.players.title"),
    organizers: t("sections.organizers.title"),
    dev: t("sections.dev.title"),
  });
  return <DocsShell sections={sections}>{children}</DocsShell>;
}
