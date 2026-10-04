import { Suspense } from "react";

import { resolveStatsScope } from "@/lib/site/tenant-host";

import HeroLeaderboardContent from "./components/HeroLeaderboardContent";

const HeroesComparePage = async ({
  searchParams
}: Readonly<{ searchParams: Promise<{ scope?: string }> }>) => {
  const scopeState = await resolveStatsScope((await searchParams).scope);

  return (
    <Suspense fallback={null}>
      <HeroLeaderboardContent scopeState={scopeState} />
    </Suspense>
  );
};

export default HeroesComparePage;
