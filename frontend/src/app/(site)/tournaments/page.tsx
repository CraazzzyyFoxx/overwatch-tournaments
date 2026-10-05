import { resolveStatsScope } from "@/lib/site/tenant-host";

import TournamentsClient from "./components/TournamentsClient";

const TournamentsPage = async () => <TournamentsClient scope={await resolveStatsScope()} />;

export default TournamentsPage;
