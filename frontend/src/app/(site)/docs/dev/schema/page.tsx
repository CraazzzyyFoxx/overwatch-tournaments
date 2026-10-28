import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Anchor, DOC_TITLE, P } from "../../mdx";
import { SchemaExplorer } from "../../SchemaExplorer";
import schema from "../../schema.generated.json";

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
      <article className="max-w-2xl">
        <h1 className={DOC_TITLE}>{t("title")}</h1>
        <P>{t("lead", { tables, packages: schema.packages.length, head: schema.alembic_head })}</P>
        <P>
          {t("erd")} <Anchor href={ERD_URL}>docs/database_erd.md</Anchor>
        </P>
      </article>
      <SchemaExplorer />
    </>
  );
}
