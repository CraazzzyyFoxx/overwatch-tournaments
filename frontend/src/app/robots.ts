import type { MetadataRoute } from "next";
import { resolveSiteMetadata } from "@/lib/site-metadata";

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
