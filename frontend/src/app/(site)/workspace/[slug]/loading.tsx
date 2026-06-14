import React from "react";
import {
  ChartCardSkeleton,
  PageHeaderSkeleton,
  PopularHeroesCardSkeleton,
  StatsGridSkeleton,
  TableCardSkeleton,
} from "@/app/home-skeletons";

export default function Loading() {
  return (
    <>
      <PageHeaderSkeleton />
      <StatsGridSkeleton />

      <div className="grid gap-4 md:gap-8 lg:grid-cols-2">
        <ChartCardSkeleton />
        <ChartCardSkeleton />
      </div>

      <div className="grid gap-4 md:gap-8 lg:grid-cols-8">
        <div className="lg:col-span-2"><TableCardSkeleton /></div>
        <div className="lg:col-span-2"><TableCardSkeleton /></div>
        <div className="lg:col-span-4"><PopularHeroesCardSkeleton /></div>
      </div>
    </>
  );
}
