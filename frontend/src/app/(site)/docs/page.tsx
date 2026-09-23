import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { SectionId } from "./nav";
import styles from "./docs.module.css";

const SECTIONS: SectionId[] = ["players", "organizers", "dev"];

export default async function DocsPage() {
  const t = await getTranslations("docs");
  return (
    <article className={styles.prose}>
      <h1>{t("title")}</h1>
      <p>{t("lead")}</p>
      <div className={styles.cards}>
        {SECTIONS.map((id) => (
          <Link key={id} href={`/docs/${id}`} className={styles.card}>
            <span className={styles.cardTitle}>{t(`sections.${id}.title`)}</span>
            <span className={styles.cardDesc}>{t(`sections.${id}.description`)}</span>
          </Link>
        ))}
      </div>
    </article>
  );
}
