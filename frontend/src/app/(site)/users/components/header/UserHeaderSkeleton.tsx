import React from "react";
import { HeroFrame } from "@/components/site/PageHero";

/**
 * Loading placeholder for the player hero, in the Editorial-Tactical aesthetic
 * (design-book §9): the same `HeroFrame` profile shell (masked grid + spectrum
 * base hairline) with a token-coloured hairline scaffold, so the skeleton reads
 * as the system rather than a generic shadcn card. No coloured blur auras.
 */
const Bar = ({ className }: { className?: string }) => (
  <span className={`block animate-pulse rounded bg-[color:var(--aqt-card-2)] ${className ?? ""}`} />
);

const UserHeaderSkeleton = () => {
  return (
    <HeroFrame className="aqt-player" variant="profile">
      <div className="flex items-center justify-between gap-3 px-9 pt-5">
        <Bar className="h-3 w-40" />
        <div className="flex gap-2">
          <Bar className="h-7 w-20 rounded-lg" />
          <Bar className="h-7 w-24 rounded-lg" />
        </div>
      </div>

      <div className="grid items-center gap-8 p-7 pt-6 md:grid-cols-[auto_1fr_auto] md:px-9 md:py-7">
        <Bar className="h-[110px] w-[110px] rounded-[18px]" />

        <div className="flex min-w-0 flex-col gap-3">
          <Bar className="h-9 w-64 max-w-full rounded-md" />
          <Bar className="h-3.5 w-52 max-w-full" />
          <div className="mt-1 flex gap-1.5">
            <Bar className="h-6 w-24 rounded-md" />
            <Bar className="h-6 w-24 rounded-md" />
          </div>
        </div>

        <div className="grid w-full items-end gap-4 md:w-auto md:min-w-[460px] md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex flex-col gap-2">
              <Bar className="h-2.5 w-16" />
              <Bar className="h-7 w-20 rounded-md" />
            </div>
          ))}
          <div className="col-span-full mt-2 flex flex-wrap items-center gap-3 border-t border-[color:var(--aqt-border)] pt-3">
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
