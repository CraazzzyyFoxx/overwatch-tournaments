import React from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-4 w-4 rounded-full" />
        <Skeleton className="h-4 w-64" />
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="hidden md:block">
          <div className="sticky top-20">
            <Card className="p-2">
              <div className="flex flex-col gap-2">
                <Skeleton className="h-11 w-full rounded-lg" />
                <Skeleton className="h-11 w-full rounded-lg" />
                <Skeleton className="h-11 w-full rounded-lg" />
                <Skeleton className="h-11 w-full rounded-lg" />
              </div>
            </Card>
          </div>
        </aside>

        <div className="min-w-0 space-y-6">
          <Card className="shadow-lg">
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Skeleton className="h-5 w-14 rounded-md" />
                <Skeleton className="h-5 w-16 rounded-md" />
                <Skeleton className="h-5 w-20 rounded-md" />
              </div>
              <Skeleton className="mt-3 h-8 w-2/3" />
              <Skeleton className="mt-2 h-4 w-full max-w-prose" />
              <Skeleton className="h-4 w-5/6 max-w-prose" />
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Skeleton className="h-16 w-full rounded-lg" />
                <Skeleton className="h-16 w-full rounded-lg" />
                <Skeleton className="h-16 w-full rounded-lg" />
                <Skeleton className="h-16 w-full rounded-lg" />
              </div>
            </CardContent>
          </Card>

          <div className="md:hidden">
            <div className="flex gap-2 overflow-x-auto pb-1">
              <Skeleton className="h-11 w-28 rounded-full" />
              <Skeleton className="h-11 w-28 rounded-full" />
              <Skeleton className="h-11 w-28 rounded-full" />
              <Skeleton className="h-11 w-28 rounded-full" />
            </div>
          </div>

          <div className="space-y-4">
            <Skeleton className="h-9 w-40" />
            <div className="grid gap-8 sm:grid-cols-2 xl:grid-cols-3">
              <Skeleton className="h-[420px] w-full rounded-xl" />
              <Skeleton className="h-[420px] w-full rounded-xl" />
              <Skeleton className="h-[420px] w-full rounded-xl" />
              <Skeleton className="h-[420px] w-full rounded-xl" />
              <Skeleton className="h-[420px] w-full rounded-xl" />
              <Skeleton className="h-[420px] w-full rounded-xl" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
