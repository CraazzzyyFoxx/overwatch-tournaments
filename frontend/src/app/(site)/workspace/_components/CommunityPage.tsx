import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SectionStack } from "@/components/site/open-layout";
import type { Workspace } from "@/types/workspace.types";

import { AboutStaff, AboutStaffSkeleton } from "./AboutStaff";
import { CommunityStats, CommunityStatsSkeleton } from "./CommunityStats";
import { CommunityTop } from "./CommunityHero";
import { HallOfFame, HallOfFameSkeleton } from "./HallOfFame";
import { NowInCommunity, NowInCommunitySkeleton } from "./NowInCommunity";

/**
 * A community's public page. Rendered at `/workspace/<slug>` on the platform
 * host, and at `/` on the community's own host (subdomain or verified custom
 * domain), where `ownHost` drops the "you are on the platform" context row:
 * there is no platform chrome around it to come back to.
 */
export async function CommunityPage({
  workspace,
  ownHost
}: Readonly<{ workspace: Workspace; ownHost: boolean }>) {
  return (
    <SectionStack className="pt-5">
      <CommunityTop workspace={workspace} ownHost={ownHost} />
      <Suspense fallback={<NowInCommunitySkeleton workspace={workspace} />}>
        <NowInCommunity workspace={workspace} />
      </Suspense>
      <Suspense fallback={<HallOfFameSkeleton />}>
        <HallOfFame workspace={workspace} />
      </Suspense>
      <Suspense fallback={<CommunityStatsSkeleton workspace={workspace} />}>
        <CommunityStats workspace={workspace} />
      </Suspense>
      <Suspense fallback={<AboutStaffSkeleton workspace={workspace} />}>
        <AboutStaff workspace={workspace} />
      </Suspense>
    </SectionStack>
  );
}

/** The tab title for both hosts the page is served on. */
export async function communityMetadata({
  workspace,
  ownHost
}: Readonly<{ workspace: Workspace; ownHost: boolean }>): Promise<Metadata> {
  const t = await getTranslations("workspace");
  return {
    title: t(ownHost ? "metaTitleOwnHost" : "metaTitlePlatform", { name: workspace.name })
  };
}
