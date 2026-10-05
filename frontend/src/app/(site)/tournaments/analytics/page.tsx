import { resolveStatsScope } from "@/lib/site/tenant-host";

import AnalyticsClient from "./components/AnalyticsClient";

const AnalyticsPage = async () => <AnalyticsClient scope={await resolveStatsScope()} />;

export default AnalyticsPage;
