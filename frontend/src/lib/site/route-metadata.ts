import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { OG_SIZE } from "@/lib/og/base";
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
 * interpolates `{siteName}`. `noIndex` is for routes reached only through a
 * private link (a team invite, a scrim room) — they carry a credential in the
 * URL and have nothing to rank for. `image` is the path of the route's share
 * card, rendered at `OG_SIZE`.
 */
export async function buildSiteRouteMetadata({
  titleKey,
  descriptionKey,
  descriptionValues,
  noIndex,
  image
}: {
  titleKey: string;
  descriptionKey: string;
  descriptionValues?: Record<string, string | number>;
  noIndex?: boolean;
  image?: string;
}): Promise<Metadata> {
  const [{ name, origin }, t, locale] = await Promise.all([
    resolveSiteMetadata(),
    getTranslations(),
    getLocale()
  ]);

  // The resolved name, not the build-time SITE_NAME: on a tenant host it is
  // the community's own title.
  const title = `${t(titleKey as never)} | ${name}`;
  const description = t(descriptionKey as never, {
    siteName: name,
    ...descriptionValues
  } as never);

  return {
    title,
    description,
    ...(noIndex && { robots: { index: false, follow: false } }),
    metadataBase: new URL(origin),
    openGraph: {
      title,
      description,
      url: origin,
      type: "website",
      siteName: name,
      // Follow the request locale instead of pinning every share card to en_US.
      locale: locale === "ru" ? "ru_RU" : "en_US",
      ...(image && { images: [{ url: image, ...OG_SIZE, alt: title }] })
    }
  };
}
