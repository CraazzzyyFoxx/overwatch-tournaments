import { HeroFrame } from "@/components/site/PageHero";
import { SectionStack } from "@/components/site/open-layout";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";

import { HallOfFameSkeleton } from "../_components/HallOfFame";

/**
 * Mirrors `CommunityPage` on the platform host: the back-link row, the identity
 * hero (avatar, eyebrow, name, actions), then the totals and leaders.
 */
export default function Loading() {
  return (
    <SectionStack className="pt-5">
      <div aria-busy className="grid gap-7">
        <div className="flex min-h-9 items-center">
          <Skeleton className="h-3 w-36" />
        </div>
        <HeroFrame>
          <div className="p-[clamp(24px,3.2vw,44px)]">
            <div className="flex items-center gap-[18px] max-[639px]:items-start">
              <Skeleton className="size-[72px] shrink-0 rounded-2xl max-[639px]:size-12 max-[639px]:rounded-xl" />
              <div className="min-w-0 flex-1">
                <Skeleton className="h-3 w-44" />
                <Skeleton className="mt-1.5 h-10 w-2/3" />
              </div>
            </div>
            <div className="mt-[26px] flex flex-wrap gap-2.5">
              <Skeleton className="h-11 w-40 rounded-[var(--aqt-radius-sm)]" />
              <Skeleton className="h-11 w-36 rounded-[var(--aqt-radius-sm)]" />
            </div>
          </div>
        </HeroFrame>
      </div>
      <HallOfFameSkeleton />
    </SectionStack>
  );
}
