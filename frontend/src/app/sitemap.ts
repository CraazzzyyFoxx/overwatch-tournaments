import type { MetadataRoute } from "next";
import { headers } from "next/headers";
import { unstable_cache } from "next/cache";
import userService from "@/services/user.service";
import { SortDirection } from "@/types/pagination.types";
import { resolveSiteMetadata } from "@/lib/site-metadata";
import { toUserSlug } from "@/app/(site)/users/components/users-overview/utils";

// This route is fully dynamic: `resolveSiteMetadata()` and the workspace lookup
// below both read `headers()` so the URLs/entries reflect the current tenant
// host on every request. The expensive part — `userService.getAll(...)`, up to
// SITE_USER_CAP rows — is NOT re-run per request: it's wrapped in
// `unstable_cache` keyed by workspace id and revalidated once every 24h, so the
// backend still only sees one fetch per workspace per day. NOTE: emits up to
// SITE_USER_CAP player profiles in a single sitemap; if the roster ever
// approaches 50k URLs, switch to generateSitemaps() chunking (and ideally a
// lightweight backend /users/sitemap slug endpoint).
export const dynamic = "force-dynamic";

const SITE_USER_CAP = 5000;

// Must NOT call headers()/cookies() — Next.js forbids dynamic APIs inside
// unstable_cache. The workspace id is passed in explicitly by the caller
// instead of being resolved from ambient request state.
async function fetchUsersForWorkspace(workspaceId: string | null): Promise<string[]> {
  try {
    const res = await userService.getAll(
      {
        page: 1,
        per_page: SITE_USER_CAP,
        sort: "id",
        order: SortDirection.asc,
        query: "",
        fields: [],
        entities: []
      },
      { workspaceId }
    );
    return res.results.map((u) => u.name);
  } catch {
    // Backend unavailable at generation time — ship the static entries only.
    return [];
  }
}

const getSitemapUsers = (workspaceId: string | null) =>
  unstable_cache(async () => fetchUsersForWorkspace(workspaceId), ["sitemap-users", workspaceId ?? "platform"], {
    revalidate: 86400
  })();

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const metadata = await resolveSiteMetadata();
  const abs = (path: string) => new URL(path, metadata.origin).toString();

  const h = await headers();
  const workspaceId = h.get("x-owt-workspace-id");

  const staticEntries: MetadataRoute.Sitemap = [
    { url: abs("/"), changeFrequency: "daily", priority: 1 },
    { url: abs("/users"), changeFrequency: "daily", priority: 0.8 }
  ];

  const userNames = await getSitemapUsers(workspaceId);
  const userEntries: MetadataRoute.Sitemap = userNames.map((name) => ({
    url: abs(`/users/${toUserSlug(name)}`),
    changeFrequency: "weekly" as const,
    priority: 0.6
  }));

  return [...staticEntries, ...userEntries];
}
