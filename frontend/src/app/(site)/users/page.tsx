import { Suspense } from "react";

import { resolveStatsScope } from "@/lib/site/tenant-host";

import UsersClient from "./components/index/UsersClient";

const UsersPage = async () => {
  const scope = await resolveStatsScope();

  return (
    <Suspense fallback={null}>
      <UsersClient scope={scope} />
    </Suspense>
  );
};

export default UsersPage;
