import { resolveStatsScope } from "@/lib/site/tenant-host";

import CompareClient from "./components/CompareClient";

const UserComparePage = async () => <CompareClient scope={await resolveStatsScope()} />;

export default UserComparePage;
