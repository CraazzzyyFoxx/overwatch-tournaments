import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { GUIDE_IDS } from "./nav";
import styles from "./docs.module.css";

export default async function DocsPage() {
  const t = await getTranslations("docs");
  return (
    <article className={styles.prose}>
      <h1>{t("title")}</h1>
      <p>{t("lead")}</p>
      <div className={styles.cards}>
        {GUIDE_IDS.map((id) => (
          <Link key={id} href={`/docs/${id}`} className={styles.card}>
            <span className={styles.cardTitle}>{t(`sections.${id}.title`)}</span>
            <span className={styles.cardDesc}>{t(`sections.${id}.description`)}</span>
          </Link>
        ))}
      </div>
    </article>
  );
}
