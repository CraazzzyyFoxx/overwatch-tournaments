import { Card, CardHeader } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";

/**
 * Mirrors the match page: the header card (mode badge and map, the score, the
 * facts row, the log line), then the statistics block's own loading panel.
 */
export default function Loading() {
  return (
    <div aria-busy className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <div className="flex flex-row items-center gap-8">
            <div className="flex flex-row items-center gap-4">
              <Skeleton className="size-10 rounded-full" />
              <Skeleton className="h-7 w-40" />
            </div>
            <div className="flex flex-row gap-4">
              <div className="flex flex-col items-end gap-1">
                <Skeleton className="h-7 w-28" />
                <Skeleton className="h-7 w-8" />
              </div>
              <div className="flex flex-col gap-1">
                <Skeleton className="h-7 w-28" />
                <Skeleton className="h-7 w-8" />
              </div>
            </div>
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="flex flex-col gap-1">
                <Skeleton className="h-7 w-20" />
                <Skeleton className="h-7 w-24" />
              </div>
            ))}
          </div>
        </CardHeader>
        <div className="px-6 pb-6">
          <Skeleton className="h-5 w-48" />
        </div>
      </Card>
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}
