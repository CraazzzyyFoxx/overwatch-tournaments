import { getTranslations } from "next-intl/server";

import { DOC_CARDS, DOC_TITLE, DocCard, P } from "./mdx";
import { GUIDE_IDS } from "./nav";

export default async function DocsPage() {
  const t = await getTranslations("docs");
  return (
    <article className="max-w-2xl">
      <h1 className={DOC_TITLE}>{t("title")}</h1>
      <P>{t("lead")}</P>
      <div className={DOC_CARDS}>
        {GUIDE_IDS.map((id) => (
          <DocCard
            key={id}
            href={`/docs/${id}`}
            title={t(`sections.${id}.title`)}
            description={t(`sections.${id}.description`)}
          />
        ))}
      </div>
    </article>
  );
}
