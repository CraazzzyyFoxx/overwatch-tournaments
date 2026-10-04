import { resolveStatsScope } from "@/lib/site/tenant-host";

import AchievementsCatalog from "./components/AchievementsCatalog";

const AchievementsPage = async () => <AchievementsCatalog scope={await resolveStatsScope()} />;

export default AchievementsPage;
