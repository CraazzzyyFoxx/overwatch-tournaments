import { Skeleton } from "@/components/ui/skeleton";

const StatColumnSkeleton = ({ rows = 15 }: { rows?: number }) => (
  <div className="min-w-[286px] flex-1">
    <div className="flex flex-col items-center gap-2 border-b border-[var(--aqt-border)] bg-[hsl(0_0%_100%/0.008)] px-3.5 pb-3 pt-3.5">
      <Skeleton className="h-[3px] w-[34px] rounded-full" />
      <Skeleton className="h-4 w-24" />
    </div>
    <div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[26px_116px_1fr_52px] items-center gap-[9px] border-b border-[color:var(--aqt-border)] px-3.5 py-2"
        >
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-4 w-full" />
        </div>
      ))}
    </div>
  </div>
);

export default StatColumnSkeleton;
