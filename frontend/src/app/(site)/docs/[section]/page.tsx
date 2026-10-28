import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { DOC_CARDS, DOC_TITLE, DocCard, H2, P } from "../mdx";
import { guideGroups, isGuideId, toDocLocale } from "../nav";

export default async function GuideIndexPage({
  params,
}: Readonly<{ params: Promise<{ section: string }> }>) {
  const { section } = await params;
  if (!isGuideId(section)) notFound();
  const [locale, t] = await Promise.all([getLocale(), getTranslations("docs")]);

  return (
    <article className="max-w-2xl">
      <h1 className={DOC_TITLE}>{t(`sections.${section}.title`)}</h1>
      <P>{t(`sections.${section}.description`)}</P>
      {guideGroups(section, toDocLocale(locale)).map((group) => (
        <section key={group.label}>
          <H2>{group.label}</H2>
          <div className={DOC_CARDS}>
            {group.items.map((item) => (
              <DocCard key={item.href} href={item.href} external={item.bypassNext} title={item.title} />
            ))}
          </div>
        </section>
      ))}
    </article>
  );
}
