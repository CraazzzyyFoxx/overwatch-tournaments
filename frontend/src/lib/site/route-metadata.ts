import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { SITE_NAME } from "@/config/site";
import { resolveSiteMetadata } from "@/lib/site/metadata";

/**
 * Metadata for a public route section.
 *
 * Every `(site)/*` section used to carry its own near-identical copy of this
 * block — six of them, each exporting a pass-through component confusingly
 * named `RootLayout`, and each hardcoding `locale: "en_US"` regardless of the
 * request. One section (`achievements/`) had no layout at all and therefore
 * shipped with no title, description or OG tags.
 *
 * `descriptionValues` covers the sections whose description string
 * interpolates `{siteName}`.
 */
export async function buildSiteRouteMetadata({
  titleKey,
  descriptionKey,
  descriptionValues
}: {
  titleKey: string;
  descriptionKey: string;
  descriptionValues?: Record<string, string | number>;
}): Promise<Metadata> {
  const [{ name, origin }, t, locale] = await Promise.all([
    resolveSiteMetadata(),
    getTranslations(),
    getLocale()
  ]);

  const title = `${t(titleKey as never)} | ${SITE_NAME}`;
  const description = t(descriptionKey as never, {
    siteName: SITE_NAME,
    ...descriptionValues
  } as never);

  return {
    title,
    description,
    metadataBase: new URL(origin),
    openGraph: {
      title,
      description,
      url: origin,
      type: "website",
      siteName: name,
      // Follow the request locale instead of pinning every share card to en_US.
      locale: locale === "ru" ? "ru_RU" : "en_US"
    }
  };
}
