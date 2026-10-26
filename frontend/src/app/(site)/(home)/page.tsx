import { Suspense } from "react";
import { headers } from "next/headers";
import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { SectionStack } from "@/components/site/open-layout";
import { OG_SIZE } from "@/lib/og/base";
import { resolveSiteMetadata } from "@/lib/site/metadata";
import workspaceService from "@/services/workspace.service";

import { CommunityPage } from "../workspace/_components/CommunityPage";
import { Directory, DirectorySkeleton } from "./_components/Directory";
import { HomeHero } from "./_components/HomeHero";
import { NowOnPlatform, NowSkeleton } from "./_components/NowOnPlatform";
import { OrganizerBanner } from "./_components/OrganizerBanner";
import { PlatformFeatures } from "./_components/PlatformFeatures";
import { PlatformLeaders, PlatformLeadersSkeleton } from "./_components/PlatformLeaders";
import { PlatformNumbers, PlatformNumbersSkeleton } from "./_components/PlatformNumbers";

export async function generateMetadata(): Promise<Metadata> {
  // A tenant host's landing is its community page: the root layout already
  // carries that tenant's own title and description.
  if ((await headers()).get("x-owt-host-mode") === "tenant") return {};
  const [t, locale, { name, origin }] = await Promise.all([
    getTranslations("home.meta"),
    getLocale(),
    resolveSiteMetadata()
  ]);
  const title = t("title", { siteName: name });
  const description = t("description", { siteName: name });
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url: origin,
      type: "website",
      siteName: name,
      locale: locale === "ru" ? "ru_RU" : "en_US",
      // The `og` route, not an `opengraph-image` file: the file would put the
      // platform's card on every community host's `/` as well.
      images: [{ url: "/og", ...OG_SIZE, alt: title }]
    }
  };
}

/**
 * The workspace a white-label host is locked to, from the `x-owt-workspace-id`
 * header `proxy.ts` injects. `null` on the platform apex and on any failure —
 * the landing is the fail-safe.
 */
async function tenantWorkspace() {
  try {
    const requestHeaders = await headers();
    if (requestHeaders.get("x-owt-host-mode") !== "tenant") return null;
    const id = Number(requestHeaders.get("x-owt-workspace-id"));
    return Number.isFinite(id) ? await workspaceService.getById(id) : null;
  } catch {
    return null;
  }
}

/**
 * `/` is two pages. On a community host it IS that community's page — the
 * visitor came to the community, not to the platform. On the apex it is the
 * product's landing, for players, organizers and partners alike: what runs
 * now, the platform in figures, its communities, what it does, who leads.
 * Every section that reads the API sits behind its own Suspense boundary, so a
 * slow statistics read holds back one block, never the page.
 */
export default async function Home({
  searchParams
}: Readonly<{ searchParams: Promise<{ discipline?: string | string[] }> }>) {
  const { discipline } = await searchParams;
  const workspace = await tenantWorkspace();
  if (workspace) {
    return <CommunityPage workspace={workspace} ownHost discipline={discipline} />;
  }

  return (
    <SectionStack className="mx-auto w-full max-w-7xl gap-[clamp(56px,7vw,96px)] pt-5">
      <HomeHero />
      <Suspense fallback={<NowSkeleton />}>
        <NowOnPlatform />
      </Suspense>
      <Suspense fallback={<PlatformNumbersSkeleton />}>
        <PlatformNumbers />
      </Suspense>
      <Suspense fallback={<DirectorySkeleton />}>
        <Directory />
      </Suspense>
      <PlatformFeatures />
      <Suspense fallback={<PlatformLeadersSkeleton />}>
        <PlatformLeaders discipline={discipline} />
      </Suspense>
      <OrganizerBanner />
    </SectionStack>
  );
}
