
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Suspense fallbacks for the dashboard-shaped pages (home, /statistics). They
 * live in `components/skeletons` rather than at the `app/` root so they are
 * importable without pretending to be a route module.
 */

const StatCardSkeleton = () => {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-5 py-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-8 w-8 rounded-lg" />
      </div>
      <Skeleton className="h-9 w-16" />
    </div>
  );
};

export const StatsGridSkeleton = () => {
  return (
    <div className="grid gap-4 md:grid-cols-2 md:gap-8 lg:grid-cols-4">
      <StatCardSkeleton />
      <StatCardSkeleton />
      <StatCardSkeleton />
      <StatCardSkeleton />
    </div>
  );
};

export const ChartCardSkeleton = () => {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-6 w-64" />
      </CardHeader>
      <CardContent>
        <Skeleton className="aspect-video w-full" />
      </CardContent>
    </Card>
  );
};

export const TableCardSkeleton = () => {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-6 w-44" />
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-[92%]" />
        <Skeleton className="h-8 w-[96%]" />
        <Skeleton className="h-8 w-[90%]" />
        <Skeleton className="h-8 w-[95%]" />
        <Skeleton className="h-8 w-[88%]" />
      </CardContent>
    </Card>
  );
};
