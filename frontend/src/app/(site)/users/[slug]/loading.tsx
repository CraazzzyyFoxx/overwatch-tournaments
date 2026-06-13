import React from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { UserOverviewPageSkeleton } from "@/app/(site)/users/pages/UserOverviewPage";
import UserHeaderSkeleton from "@/app/(site)/users/components/header/UserHeaderSkeleton";

export default function Loading() {
  return (
    <>
      <UserHeaderSkeleton />

      <div className="sticky top-14 z-40 -mx-10 px-10 pt-3 pb-4 bg-background/70 backdrop-blur supports-[backdrop-filter]:bg-background/50 border-b">
        <Skeleton className="h-11 w-[520px] rounded-full" />
      </div>

      <div className="pt-6">
        <UserOverviewPageSkeleton />
      </div>
    </>
  );
}
