import { Suspense } from "react";

import { resolveStatsScope } from "@/lib/site/tenant-host";

import UsersClient from "./components/index/UsersClient";

const UsersPage = async ({
  searchParams
}: Readonly<{ searchParams: Promise<{ scope?: string }> }>) => {
  const scopeState = await resolveStatsScope((await searchParams).scope);

  return (
    <Suspense fallback={null}>
      <UsersClient scopeState={scopeState} />
    </Suspense>
  );
};

export default UsersPage;
