import type { Metadata } from "next";
import type { MDXContent } from "mdx/types";
import { ArrowUpRight } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";

import { PageHero } from "@/components/site/PageHero";
import { Button } from "@/components/ui/button";
import { REPO_URL } from "@/config/site";
import { RELEASES } from "@/lib/changelog/releases";
import { getFormatter } from "@/lib/datetime/server";

import { toDocLocale } from "../docs/nav";
import { changelogComponents } from "./mdx";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("changelog");
  return { title: `${t("title")} · OWT` };
}

export default async function ChangelogPage() {
  const [t, locale, format] = await Promise.all([getTranslations("changelog"), getLocale(), getFormatter()]);
  const lang = toDocLocale(locale);
  // Runtime-selected: the locale comes from a cookie / Accept-Language, so
  // this cannot be a static import. RELEASES is the allow-list.
  const entries = await Promise.all(
    RELEASES.map(async (release) => ({
      release,
      Content: (await import(`./_content/${lang}/${release.version}.mdx`)).default as MDXContent
    }))
  );

  return (
    <>
      <PageHero compact title={t("title")} lede={t("lede")} />
      {entries.map(({ release, Content }) => {
        const id = `v${release.version}`;
        return (
          // The meta column (version, date) beside the entry from `lg`; above the title below it.
          // From `md` the entry starts where the hero's title does: its 1px frame plus PageHero compact's `md:px-6`.
          <article
            key={id}
            id={id}
            aria-labelledby={`${id}-title`}
            className="mt-12 grid max-w-287 scroll-mt-[var(--aqt-sticky-top)] grid-cols-1 gap-4.5 md:mt-14 md:pl-6.25 lg:grid-cols-[10.5rem_minmax(0,1fr)] lg:gap-12"
          >
            <div className="flex items-center gap-3 self-start lg:sticky lg:top-[var(--aqt-sticky-top)] lg:flex-col lg:items-start lg:gap-2.5">
              <Button variant="outline" size="sm" asChild>
                <a href={`#${id}`}>{id}</a>
              </Button>
              <time dateTime={release.date} className="text-caption text-[color:var(--aqt-fg-dim)]">
                {format.dateTime(new Date(release.date), { dateStyle: "long", timeZone: "UTC" })}
              </time>
            </div>
            <div>
              <h2
                id={`${id}-title`}
                className="max-w-[34ch] text-balance font-display text-title font-semibold text-[color:var(--aqt-fg)] md:text-headline"
              >
                {release.title[lang]}
              </h2>
              <Content components={changelogComponents} />
              <Button variant="outline" asChild className="mt-10">
                <a href={`${REPO_URL}/releases/tag/${id}`} target="_blank" rel="noreferrer">
                  {t("fullLog")}
                  <ArrowUpRight aria-hidden />
                </a>
              </Button>
            </div>
          </article>
        );
      })}
    </>
  );
}
