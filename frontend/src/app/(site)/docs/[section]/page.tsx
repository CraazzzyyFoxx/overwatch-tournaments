import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { guideGroups, isGuideId, toDocLocale } from "../nav";
import styles from "../docs.module.css";

export default async function GuideIndexPage({
  params,
}: Readonly<{ params: Promise<{ section: string }> }>) {
  const { section } = await params;
  if (!isGuideId(section)) notFound();
  const [locale, t] = await Promise.all([getLocale(), getTranslations("docs")]);

  return (
    <article className={styles.prose}>
      <h1>{t(`sections.${section}.title`)}</h1>
      <p>{t(`sections.${section}.description`)}</p>
      {guideGroups(section, toDocLocale(locale)).map((group) => (
        <section key={group.label}>
          <h2>{group.label}</h2>
          <div className={styles.cards}>
            {group.items.map((item) => (
              <Link key={item.href} href={item.href} className={styles.card}>
                <span className={styles.cardTitle}>{item.title}</span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </article>
  );
}
