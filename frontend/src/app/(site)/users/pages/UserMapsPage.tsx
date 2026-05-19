import React from "react";
import dynamic from "next/dynamic";

import { User } from "@/types/user.types";

const MapsView = dynamic(() => import("@/app/(site)/users/components/redesign/MapsView"));

const UserMapsPage = ({ user }: { user: User }) => {
  return <MapsView userId={user.id} />;
};

export default UserMapsPage;
