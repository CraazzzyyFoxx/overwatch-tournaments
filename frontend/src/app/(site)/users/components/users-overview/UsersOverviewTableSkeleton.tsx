import { Skeleton } from "@/components/ui/skeleton";

const UsersOverviewTableSkeleton = () => {
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <div className="min-w-[980px] space-y-2">
          <div className="grid grid-cols-7 gap-3 rounded-md border border-border/60 p-3">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-5 w-20 justify-self-center" />
            <Skeleton className="h-5 w-24 justify-self-center" />
            <Skeleton className="h-5 w-24 justify-self-center" />
            <Skeleton className="h-5 w-24 justify-self-center" />
            <Skeleton className="h-5 w-20 justify-self-center" />
            <Skeleton className="h-5 w-16 justify-self-center" />
          </div>

          {Array.from({ length: 8 }).map((_, index) => (
            <div key={`users-overview-row-skeleton-${index}`} className="grid grid-cols-7 items-center gap-3 rounded-md border border-border/50 p-3">
              <Skeleton className="h-5 w-44" />
              <div className="flex justify-center gap-1">
                <Skeleton className="h-9 w-9 rounded-full" />
                <Skeleton className="h-9 w-9 rounded-full" />
              </div>
              <Skeleton className="h-5 w-10 justify-self-center" />
              <Skeleton className="h-5 w-10 justify-self-center" />
              <Skeleton className="h-5 w-16 justify-self-center" />
              <div className="flex justify-center gap-1">
                <Skeleton className="h-9 w-9 rounded-full" />
                <Skeleton className="h-9 w-9 rounded-full" />
                <Skeleton className="h-9 w-9 rounded-full" />
              </div>
              <Skeleton className="h-9 w-9 rounded-full justify-self-center" />
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Skeleton className="h-4 w-52" />
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-24" />
        </div>
      </div>
    </div>
  );
};

export default UsersOverviewTableSkeleton;
