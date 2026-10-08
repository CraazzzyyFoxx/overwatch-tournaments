import { HeroFrame } from "@/components/site/PageHero";

/**
 * Loading placeholder for the player hero: the same `HeroFrame` profile shell
 * (spectrum base hairline) and the same grid as `UserHeader`, so nothing jumps
 * when the real header streams in.
 */
const Bar = ({ className }: { className?: string }) => (
  <span className={`block animate-pulse rounded bg-[color:var(--aqt-card-2)] ${className ?? ""}`} />
);

const UserHeaderSkeleton = () => {
  return (
    <HeroFrame className="aqt-player" variant="profile">
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-6 px-5 py-5 md:gap-x-6 md:px-8 md:py-7 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center lg:gap-x-10">
        <Bar className="size-[72px] rounded-[14px] md:size-[104px] md:rounded-[18px]" />

        <div className="flex min-w-0 flex-col gap-3">
          <Bar className="h-9 w-64 max-w-full rounded-md" />
          <Bar className="h-3.5 w-32 max-w-full" />
          <div className="mt-1 flex gap-1.5">
            <Bar className="h-6 w-24 rounded-md" />
            <Bar className="h-6 w-24 rounded-md" />
          </div>
        </div>

        <div className="col-span-full flex min-w-0 flex-col gap-5 lg:col-span-1 lg:items-end">
          <div className="flex gap-2">
            <Bar className="h-8 w-20 rounded-lg" />
            <Bar className="h-8 w-24 rounded-lg" />
          </div>
          <div className="grid w-full grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 lg:w-auto lg:gap-x-9">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex flex-col gap-2">
                <Bar className="h-2.5 w-16" />
                <Bar className="h-7 w-20 rounded-md" />
              </div>
            ))}
          </div>
          <div className="flex w-full flex-wrap items-center gap-3 border-t border-[color:var(--aqt-border)] pt-3">
            <Bar className="h-2.5 w-24" />
            <div className="flex gap-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Bar key={i} className="h-5 w-5 rounded-[5px]" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </HeroFrame>
  );
};

export default UserHeaderSkeleton;
