import { resolveStatsScope } from "@/lib/site/tenant-host";

import AchievementsCatalog from "./components/AchievementsCatalog";

const AchievementsPage = async ({
  searchParams
}: Readonly<{ searchParams: Promise<{ scope?: string }> }>) => {
  const scopeState = await resolveStatsScope((await searchParams).scope);

  return <AchievementsCatalog scopeState={scopeState} />;
};

export default AchievementsPage;
