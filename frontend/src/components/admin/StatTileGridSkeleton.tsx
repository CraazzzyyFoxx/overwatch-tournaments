import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { StatTileGrid } from "./StatTile";

/**
 * Loading placeholder for a collector health dashboard: a status-bar-sized
 * skeleton above a `StatTileGrid` of `count` tile-sized skeletons — pass the
 * number of `StatTile`s the loaded dashboard renders, so nothing jumps.
 */
export function StatTileGridSkeleton({ count = 4 }: Readonly<{ count?: number }>) {
  return (
    <div className="space-y-3">
      <Skeleton className="h-9 w-full" />
      <StatTileGrid>
        {Array.from({ length: count }, (_, index) => (
          <Skeleton key={index} className="h-28" />
        ))}
      </StatTileGrid>
    </div>
  );
}
