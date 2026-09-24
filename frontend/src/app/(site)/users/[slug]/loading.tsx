
import { UserOverviewPageSkeleton } from "@/app/(site)/users/_views/UserOverviewPage";
import UserHeaderSkeleton from "@/app/(site)/users/components/header/UserHeaderSkeleton";

/**
 * Route-level loading state. Mirrors the live layout in the Editorial-Tactical
 * system: the profile hero skeleton, then the sticky tab bar drawn like
 * `UserProfileTabList` (the shared underline tab row on a hairline).
 */
export default function Loading() {
  return (
    <>
      <UserHeaderSkeleton />

      {/* Gutter and offset must track UserTabsClient exactly, or the loading
          state reintroduces the 375px horizontal scroll the live bar just lost. */}
      <div className="sticky top-[var(--aqt-header-h)] z-40 -mx-4 -mt-3 bg-background px-4 pt-3 md:-mx-6 md:-mt-7 md:px-6 xl:-mx-10 xl:px-10">
        <div className="flex h-9 w-full items-center gap-4 overflow-hidden px-3 shadow-[inset_0_-1px_0_hsl(var(--border))]">
          {Array.from({ length: 6 }).map((_, i) => (
            <span key={i} className="h-3.5 w-16 shrink-0 animate-pulse rounded bg-[color:var(--aqt-card-2)]" />
          ))}
        </div>
      </div>

      <div className="pt-6">
        <UserOverviewPageSkeleton />
      </div>
    </>
  );
}
