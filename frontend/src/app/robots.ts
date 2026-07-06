import type { MetadataRoute } from "next";
import { resolveSiteMetadata } from "@/lib/site-metadata";

// This route is fully dynamic (resolveSiteMetadata() reads headers() to reflect
// the current tenant host), but that's cheap here — there's no heavy fetch like
// the sitemap's user list, so per-request generation needs no caching.
export default async function robots(): Promise<MetadataRoute.Robots> {
  const metadata = await resolveSiteMetadata();
  const base = metadata.origin;
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Internal/auth surfaces that shouldn't be indexed.
        disallow: ["/api/", "/account", "/settings"]
      }
    ],
    sitemap: `${base}/sitemap.xml`,
    host: base
  };
}
