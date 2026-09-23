import type { Metadata } from "next";
import type { MDXContent } from "mdx/types";
import { notFound } from "next/navigation";
import { getLocale } from "next-intl/server";

import { mdxComponents } from "../../mdx";
import { findGuideArticle, isGuideId, toDocLocale } from "../../nav";
import styles from "../../docs.module.css";

type Params = Promise<{ section: string; slug: string }>;

async function resolveArticle(params: Params) {
  const { section, slug } = await params;
  // The registry is the allow-list: nothing from the URL reaches the import
  // below unless it names a known article.
  const article = isGuideId(section) ? findGuideArticle(section, slug) : undefined;
  if (!article) notFound();
  return { section, article, locale: toDocLocale(await getLocale()) };
}

export async function generateMetadata({ params }: Readonly<{ params: Params }>): Promise<Metadata> {
  const { article, locale } = await resolveArticle(params);
  return { title: `${article.title[locale]} · OWT` };
}

export default async function GuideArticlePage({ params }: Readonly<{ params: Params }>) {
  const { section, article, locale } = await resolveArticle(params);
  // Runtime-selected: the locale comes from a cookie / Accept-Language and the
  // article from the URL, so this cannot be a static import.
  const Content: MDXContent = (
    await import(`../../_content/${locale}/${section}/${article.slug}.mdx`)
  ).default;

  return (
    <article className={styles.prose}>
      <h1>{article.title[locale]}</h1>
      <Content components={mdxComponents} />
    </article>
  );
}
