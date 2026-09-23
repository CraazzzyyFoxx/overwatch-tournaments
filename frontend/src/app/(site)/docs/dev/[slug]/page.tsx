import { notFound } from "next/navigation";

import { Article } from "../../articles";
import { DocsExplorer } from "../../DocsExplorer";
import { ARTICLE_SLUGS, isArticleSlug } from "../../nav";

export function generateStaticParams() {
  return [...ARTICLE_SLUGS, "schema"].map((slug) => ({ slug }));
}

export default async function DevDocsSlugPage({
  params,
}: Readonly<{ params: Promise<{ slug: string }> }>) {
  const { slug } = await params;
  if (slug === "schema") {
    return <DocsExplorer />;
  }
  if (!isArticleSlug(slug)) {
    notFound();
  }
  return <Article slug={slug} />;
}
