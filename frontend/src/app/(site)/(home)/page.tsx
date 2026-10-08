import { Suspense } from "react";
import { headers } from "next/headers";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SectionStack } from "@/components/site/open-layout";
import workspaceService from "@/services/workspace.service";

import { CommunityPage } from "../workspace/_components/CommunityPage";
import { Directory, DirectorySkeleton } from "./_components/Directory";
import { HomeHero } from "./_components/HomeHero";
import { HomeShowcase } from "./_components/HomeShowcase";
import { NowOnPlatform, NowSkeleton } from "./_components/NowOnPlatform";
import { OrganizerBanner } from "./_components/OrganizerBanner";
import { PlatformLeaders, PlatformLeadersSkeleton } from "./_components/PlatformLeaders";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home.meta");
  return { title: t("title"), description: t("description") };
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
 * platform landing: every section fetches its own data behind its own Suspense
 * boundary, so a slow statistics read holds back one block, never the page.
 */
export default async function Home() {
  const workspace = await tenantWorkspace();
  if (workspace) return <CommunityPage workspace={workspace} ownHost />;

  return (
    <SectionStack className="pt-5">
      <HomeHero />
      <Suspense fallback={<NowSkeleton />}>
        <NowOnPlatform />
      </Suspense>
      <Suspense fallback={<DirectorySkeleton />}>
        <Directory />
      </Suspense>
      <Suspense fallback={<PlatformLeadersSkeleton />}>
        <PlatformLeaders />
      </Suspense>
      <HomeShowcase />
      <OrganizerBanner />
    </SectionStack>
  );
}
