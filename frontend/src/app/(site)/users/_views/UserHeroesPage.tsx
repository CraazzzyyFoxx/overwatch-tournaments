import dynamic from "next/dynamic";

import { User } from "@/types/user.types";
import type { StatsScope } from "@/lib/site/stats-scope";

const UserHeroesContainer = dynamic(
  () => import("@/app/(site)/users/components/heroes/UserHeroesContainer")
);

const UserHeroesPage = ({ user, scope }: { user: User; scope: StatsScope }) => {
  return <UserHeroesContainer userId={user.id} scope={scope} />;
};

export default UserHeroesPage;
