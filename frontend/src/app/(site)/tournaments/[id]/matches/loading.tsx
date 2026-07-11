import React from "react";

import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col gap-8">
      <Skeleton className="h-9 w-[280px]" />

      <Skeleton className="h-[420px] w-full rounded-md" />

      <div className="flex items-center justify-end">
        <Skeleton className="h-9 w-56" />
      </div>
    </div>
  );
}
