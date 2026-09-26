import { Suspense } from "react";
import { getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/card";
import { EventsSkeleton } from "@/components/site/LiveEventsWidgets";
import {
  ChartCardSkeleton,
  StatsGridSkeleton,
  TableCardSkeleton
} from "@/components/skeletons/dashboard-skeletons";

import { getTenantMode } from "./_components/home.helpers";
import { PageIntroSection } from "./_components/PageIntroSection";
import { LiveEventsSection } from "./_components/LiveEventsSection";
import { CommunitiesSection, CommunitiesSkeleton } from "./_components/CommunitiesSection";
import { TournamentActivityCard } from "./_components/TournamentActivityCard";
import { DivisionRingsCard } from "./_components/DivisionRingsCard";
import {
  ChampionsCard,
  StatsGridSection,
  TopWinRateCard
} from "./_components/statistics-sections";

export const dynamic = "force-dynamic";

/**
 * The public landing page. Every section fetches its own data and sits behind
 * its own `Suspense` boundary, so the page streams: a slow statistics read
 * holds back one card, never the whole shell.
 */
export default async function Home() {
  // On a tenant (white-label) host the whole site is locked to one
  // workspace, so the cross-workspace "communities on this platform" list
  // is hidden. See proxy.ts (Task 6) for the header injection.
  const tenantMode = await getTenantMode();
  const t = await getTranslations();

  return (
    <div className="space-y-8">
      {/* Cinematic page intro */}
      <PageIntroSection tenantMode={tenantMode} />

      {/* Live / upcoming events */}
      <section>
        <Suspense fallback={<EventsSkeleton />}>
          <LiveEventsSection />
        </Suspense>
      </section>

      {/* Platform stats */}
      <section>
        <p className="mb-4 text-label font-semibold tracking-label uppercase text-muted-foreground/50">
          {t("home.byTheNumbers")}
        </p>
        <Suspense fallback={<StatsGridSkeleton />}>
          <StatsGridSection />
        </Suspense>
      </section>

      {/* Workspace / community cards */}
      {!tenantMode && (
        <section>
          <p className="mb-1.5 text-label font-semibold tracking-label uppercase text-muted-foreground/50">
            {t("home.workspaces")}
          </p>
          <h2 className="font-display text-title font-bold text-foreground mb-5">
            {t("home.communitiesOnPlatform")}
          </h2>
          <Suspense fallback={<CommunitiesSkeleton />}>
            <CommunitiesSection />
          </Suspense>
        </section>
      )}

      {/* Season dashboard */}
      <section className="pb-8 space-y-4">
        <div>
          <p className="mb-1.5 text-label font-semibold tracking-label uppercase text-muted-foreground/50">
            {t("home.seasonOverview")}
          </p>
          <h2 className="font-display text-title font-bold text-foreground">
            {t("home.communityDashboard")}
          </h2>
        </div>

        {/* Full-width tournament activity chart */}
        <Card className="overflow-hidden border-border">
          <Suspense fallback={<ChartCardSkeleton />}>
            <TournamentActivityCard />
          </Suspense>
        </Card>

        {/* 3-column: division rings | champions | top winrate */}
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="overflow-hidden border-border">
            <Suspense fallback={<ChartCardSkeleton />}>
              <DivisionRingsCard />
            </Suspense>
          </Card>

          <Card className="overflow-hidden border-border">
            <Suspense fallback={<TableCardSkeleton />}>
              <ChampionsCard />
            </Suspense>
          </Card>

          <Card className="overflow-hidden border-border">
            <Suspense fallback={<TableCardSkeleton />}>
              <TopWinRateCard />
            </Suspense>
          </Card>
        </div>
      </section>
    </div>
  );
}
