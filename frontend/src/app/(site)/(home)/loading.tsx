import React from "react";

import {
  ChartCardSkeleton,
  PageHeaderSkeleton,
  PopularHeroesCardSkeleton,
  StatsGridSkeleton,
  TableCardSkeleton
} from "@/app/home-skeletons";

export default function Loading() {
  return (
    <>
      <PageHeaderSkeleton />
      <StatsGridSkeleton />

      <div className="grid gap-4 md:gap-8 lg:grid-cols-2 xl:grid-cols-4">
        <div className="lg:col-span-2">
          <ChartCardSkeleton />
        </div>
        <div className="lg:col-span-2">
          <ChartCardSkeleton />
        </div>
      </div>

      <div className="grid gap-4 md:gap-8 xl:grid-cols-4 lg:grid-cols-2 xs:grid-cols-1">
        <TableCardSkeleton />
        <TableCardSkeleton />
        <PopularHeroesCardSkeleton />
      </div>
    </>
  );
}
