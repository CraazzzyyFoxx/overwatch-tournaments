import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** The `next/dynamic` placeholder of a `GraphCanvas`: its frame at the canvas' own height, so nothing shifts when it lands. */
export function GraphCanvasSkeleton({ heightClass }: Readonly<{ heightClass: string }>) {
  return <Skeleton className={cn(heightClass, "w-full rounded-lg")} />;
}
