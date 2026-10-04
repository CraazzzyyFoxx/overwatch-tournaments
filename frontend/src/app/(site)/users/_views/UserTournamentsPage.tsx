import { User } from "@/types/user.types";
import type { StatsScope } from "@/lib/site/stats-scope";
import { Skeleton } from "@/components/ui/skeleton";
import userService from "@/services/user.service";
import TournamentsHistory from "@/app/(site)/users/components/tournaments/TournamentsHistory";

export const UserTournamentsPageSkeleton = () => {
  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-56 w-full rounded-xl" />
      <Skeleton className="min-h-[400px] w-full rounded-xl" />
    </div>
  );
};

export const UserTournamentsPage = async ({ user, scope }: { user: User; scope: StatsScope }) => {
  // Both reads are scoped and cached (Next Data Cache); fetched in parallel.
  // The profile powers the KPI strip (Played / Titles / Avg placement); the
  // tournaments list drives the master-detail Event dossier explorer.
  const [tournaments, profile] = await Promise.all([
    userService.getUserTournaments(user.id, scope === "all" ? "all" : undefined),
    userService.getUserProfile(user.id, scope).catch(() => null)
  ]);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <TournamentsHistory tournaments={tournaments} selfUserId={user.id} profile={profile} />
    </div>
  );
};
