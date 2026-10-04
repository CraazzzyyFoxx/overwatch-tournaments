import { Suspense } from "react";

import { resolveStatsScope } from "@/lib/site/tenant-host";

import HeroLeaderboardContent from "./components/HeroLeaderboardContent";

const HeroesComparePage = async () => {
  const scope = await resolveStatsScope();

  return (
    <Suspense fallback={null}>
      <HeroLeaderboardContent scope={scope} />
    </Suspense>
  );
};

export default HeroesComparePage;
