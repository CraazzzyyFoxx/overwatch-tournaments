import dynamic from "next/dynamic";

import { User } from "@/types/user.types";
import type { StatsScope } from "@/lib/site/stats-scope";

const MapsView = dynamic(() => import("@/app/(site)/users/components/maps/MapsView"));

const UserMapsPage = ({ user, scope }: { user: User; scope: StatsScope }) => {
  return <MapsView userId={user.id} scope={scope} />;
};

export default UserMapsPage;
