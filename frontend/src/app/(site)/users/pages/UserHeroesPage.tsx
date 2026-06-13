import React from "react";
import dynamic from "next/dynamic";

import { User } from "@/types/user.types";

const UserHeroesContainer = dynamic(
  () => import("@/app/(site)/users/components/heroes/UserHeroesContainer")
);

const UserHeroesPage = ({ user }: { user: User }) => {
  return <UserHeroesContainer userId={user.id} />;
};

export default UserHeroesPage;
