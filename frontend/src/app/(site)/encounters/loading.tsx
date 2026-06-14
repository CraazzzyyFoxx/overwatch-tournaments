import { Skeleton } from "@/components/ui/skeleton";

const ROWS = 8;

export default function Loading() {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.74fr)]">
        <Skeleton className="h-56 rounded-lg" />
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-28 rounded-lg" />
          <Skeleton className="h-28 rounded-lg" />
          <Skeleton className="h-28 rounded-lg" />
          <Skeleton className="h-28 rounded-lg" />
        </div>
      </div>

      <Skeleton className="h-14 rounded-lg" />
      <Skeleton className="h-16 rounded-lg" />

      <div className="grid gap-4 xl:grid-cols-3">
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_310px]">
        <div className="rounded-lg border p-4">
          <div className="space-y-3">
            {Array.from({ length: ROWS }).map((_, index) => (
              <Skeleton key={index} className="h-14 rounded-md" />
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <Skeleton className="h-44 rounded-lg" />
          <Skeleton className="h-56 rounded-lg" />
          <Skeleton className="h-36 rounded-lg" />
        </div>
      </div>
    </div>
  );
}
