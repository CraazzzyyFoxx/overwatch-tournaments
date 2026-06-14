import { Skeleton } from "@/components/ui/skeleton";

const StatColumnSkeleton = ({ rows = 15 }: { rows?: number }) => (
  <div className="min-w-[270px] flex-1">
    <div className="flex flex-col items-center gap-1.5 border-b border-border/50 px-4 pb-3 pt-3">
      <Skeleton className="h-[3px] w-8 rounded-full" />
      <Skeleton className="h-3 w-24" />
    </div>
    <div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className={`flex items-center gap-3 px-4 py-[9px] ${i % 2 === 0 ? "bg-muted/[0.06]" : ""}`}
        >
          <Skeleton className="h-4 w-6 shrink-0" />
          <Skeleton className="h-4 w-32 shrink-0" />
          <Skeleton className="h-[22px] flex-1" />
          <Skeleton className="h-4 w-12 shrink-0" />
        </div>
      ))}
    </div>
  </div>
);

export default StatColumnSkeleton;
