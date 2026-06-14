import type { MetadataRoute } from "next";
import { SITE_URL_OBJ } from "@/config/site";

export default function robots(): MetadataRoute.Robots {
  const base = SITE_URL_OBJ.toString().replace(/\/$/, "");
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
