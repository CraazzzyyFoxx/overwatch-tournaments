import React from "react";
import { Skeleton } from "@/components/ui/skeleton";

const UserHeaderSkeleton = () => {
  return (
    <div className="relative overflow-hidden rounded-2xl border bg-card/70 p-4 backdrop-blur md:p-6">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-24 -left-24 h-72 w-72 rounded-full bg-emerald-500/15 blur-3xl" />
        <div className="absolute -top-28 right-0 h-80 w-80 rounded-full bg-sky-500/12 blur-3xl" />
        <div className="absolute -bottom-24 left-1/3 h-80 w-80 rounded-full bg-amber-500/10 blur-3xl" />
      </div>
      <div className="relative flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <Skeleton className="h-24 w-24 rounded-2xl" />
          <div className="flex flex-col gap-2">
            <div className="flex flex-row items-center gap-2">
              <Skeleton className="h-7 w-56" />
              <Skeleton className="hidden h-7 w-24 xs1:block" />
            </div>
            <Skeleton className="h-4 w-64" />
            <div className="flex flex-wrap gap-2 pt-1">
              <Skeleton className="h-8 w-40 rounded-full" />
              <Skeleton className="h-8 w-40 rounded-full" />
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Skeleton className="h-14 w-32 rounded-xl" />
          <Skeleton className="h-14 w-32 rounded-xl" />
          <Skeleton className="h-14 w-32 rounded-xl" />
          <Skeleton className="h-14 w-32 rounded-xl" />
        </div>
      </div>
    </div>
  );
};

export default UserHeaderSkeleton;
