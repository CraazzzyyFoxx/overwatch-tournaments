import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SchemaExplorer } from "../../SchemaExplorer";
import schema from "../../schema.generated.json";
import styles from "../../docs.module.css";

const ERD_URL = "https://github.com/CraazzzyyFoxx/overwatch-tournaments/blob/master/docs/database_erd.md";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("docs.schema");
  return { title: `${t("title")} · OWT` };
}

export default async function SchemaPage() {
  const t = await getTranslations("docs.schema");
  const tables = schema.packages.reduce((sum, pkg) => sum + pkg.tables.length, 0);
  return (
    <>
      <article className={styles.prose}>
        <h1>{t("title")}</h1>
        <p>{t("lead", { tables, packages: schema.packages.length, head: schema.alembic_head })}</p>
        <p>
          {t("erd")}{" "}
          <a href={ERD_URL} rel="noreferrer">
            docs/database_erd.md
          </a>
        </p>
      </article>
      <SchemaExplorer />
    </>
  );
}
