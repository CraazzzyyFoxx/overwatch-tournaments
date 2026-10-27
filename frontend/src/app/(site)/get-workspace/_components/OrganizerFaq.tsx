import type { ReactNode } from "react";
import Link from "next/link";
import { ChevronDown, FileText } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";

import { findGuideArticle, toDocLocale } from "@/app/(site)/docs/nav";
import { MoreLink, Section, SectionHead } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";

const TITLE_ID = "gw-faq-title";

/**
 * Two columns of two topics, each question with the organizer docs article its
 * answer comes from (`null`: the answer is the page's own). The first question
 * of each column starts open.
 */
const COLUMNS = [
  [
    [
      "start",
      [
        ["price", null],
        ["accounts", "getting-started"],
        ["review", "getting-started"]
      ]
    ],
    [
      "catalog",
      [
        ["verification", "getting-started"],
        ["domain", "workspace"],
        ["hidden", "workspace"]
      ]
    ]
  ],
  [
    [
      "tournaments",
      [
        ["teams", "team-formation"],
        ["sheets", "registration"],
        ["stats", "logs"]
      ]
    ],
    [
      "team",
      [
        ["discord", "workspace"],
        ["roles", "roles"],
        ["mixes", "mixes"]
      ]
    ]
  ]
] as const;

const bold = (chunks: ReactNode) => <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>;

/**
 * The organizer page's questions, grouped by topic in two columns (one on a
 * phone). Each is a native disclosure (DESIGN "Expanding row"), several can be
 * open, and every answer drawn from the docs links its article.
 */
export async function OrganizerFaq() {
  const [t, locale] = await Promise.all([getTranslations("getWorkspace.faq"), getLocale()]);
  const docLocale = toDocLocale(locale);

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("title")}
        titleId={TITLE_ID}
        aside={<MoreLink href="/docs/organizers/faq">{t("docs")}</MoreLink>}
      />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-x-[clamp(24px,4vw,56px)] gap-y-7 md:grid-cols-2">
        {COLUMNS.map((column, columnIndex) => (
          <div key={columnIndex} className="grid min-w-0 content-start gap-7">
            {column.map(([topic, items], topicIndex) => (
              <div key={topic}>
                <Eyebrow as="h3" className="block border-b border-[color:var(--aqt-fg-faint)] pb-2">
                  {t(`topics.${topic}`)}
                </Eyebrow>
                {items.map(([key, doc], index) => {
                  const article = doc ? findGuideArticle("organizers", doc) : undefined;
                  return (
                    <details
                      key={key}
                      open={topicIndex === 0 && index === 0}
                      className="group border-b border-[color:var(--aqt-border)]"
                    >
                      <summary className="group/q flex cursor-pointer list-none items-center justify-between gap-4 py-3.5 font-display text-ui font-semibold leading-snug text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] [&::-webkit-details-marker]:hidden">
                        {t(`items.${key}.q`)}
                        <ChevronDown
                          aria-hidden
                          className="size-4.5 shrink-0 text-[color:var(--aqt-fg-faint)] transition-[transform,color] duration-200 group-open:rotate-180 group-open:text-[color:var(--aqt-teal)] group-hover/q:text-[color:var(--aqt-teal)]"
                        />
                      </summary>
                      <div className="pb-4 pr-9 text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">
                        <p className="text-pretty">{t.rich(`items.${key}.a`, { b: bold })}</p>
                        {article ? (
                          <p className="mt-2 flex items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)]">
                            <FileText aria-hidden className="size-3.5 shrink-0" />
                            <Link
                              href={`/docs/organizers/${article.slug}`}
                              prefetch={false}
                              className="rounded-sm text-[color:var(--aqt-teal)] underline-offset-[3px] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
                            >
                              {article.title[docLocale]}
                            </Link>
                          </p>
                        ) : null}
                      </div>
                    </details>
                  );
                })}
              </div>
            ))}
          </div>
        ))}
      </div>
    </Section>
  );
}
