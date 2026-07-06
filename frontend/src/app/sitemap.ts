import type { MetadataRoute } from "next";
import userService from "@/services/user.service";
import { SortDirection } from "@/types/pagination.types";
import { resolveSiteMetadata } from "@/lib/site-metadata";
import { toUserSlug } from "@/app/(site)/users/components/users-overview/utils";

// Regenerated daily. NOTE: emits up to SITE_USER_CAP player profiles in a single
// sitemap; if the roster ever approaches 50k URLs, switch to generateSitemaps()
// chunking (and ideally a lightweight backend /users/sitemap slug endpoint).
export const revalidate = 86400;

const SITE_USER_CAP = 5000;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const metadata = await resolveSiteMetadata();
  const abs = (path: string) => new URL(path, metadata.origin).toString();

  const staticEntries: MetadataRoute.Sitemap = [
    { url: abs("/"), changeFrequency: "daily", priority: 1 },
    { url: abs("/users"), changeFrequency: "daily", priority: 0.8 }
  ];

  let userEntries: MetadataRoute.Sitemap = [];
  try {
    const res = await userService.getAll({
      page: 1,
      per_page: SITE_USER_CAP,
      sort: "id",
      order: SortDirection.asc,
      query: "",
      fields: [],
      entities: []
    });
    userEntries = res.results.map((u) => ({
      url: abs(`/users/${toUserSlug(u.name)}`),
      changeFrequency: "weekly" as const,
      priority: 0.6
    }));
  } catch {
    // Backend unavailable at generation time — ship the static entries only.
  }

  return [...staticEntries, ...userEntries];
}
