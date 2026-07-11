import React from "react";

import { UserOverviewPageSkeleton } from "@/app/(site)/users/pages/UserOverviewPage";
import UserHeaderSkeleton from "@/app/(site)/users/components/header/UserHeaderSkeleton";

/**
 * Route-level loading state. Mirrors the live layout in the Editorial-Tactical
 * system: the profile hero skeleton, then the sticky tab-bar treatment matching
 * `UserProfileTabList` (token card + hairline, not shadcn backdrop-blur).
 */
export default function Loading() {
  return (
    <>
      <UserHeaderSkeleton />

      <div className="sticky top-14 z-40 -mx-10 px-10 pb-4 pt-3 bg-[color:var(--aqt-bg)]">
        <div className="flex w-full max-w-[560px] items-center gap-2 overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-2 py-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <span
              key={i}
              className="h-7 flex-1 animate-pulse rounded-lg bg-[color:var(--aqt-card-2)]"
            />
          ))}
        </div>
      </div>

      <div className="pt-6">
        <UserOverviewPageSkeleton />
      </div>
    </>
  );
}
