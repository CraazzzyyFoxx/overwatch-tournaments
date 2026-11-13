import { User, UserProfile } from "@/types/user.types";
import type { StatsScope } from "@/lib/site/stats-scope";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import userService from "@/services/user.service";
import TournamentsHistory from "@/app/(site)/users/components/tournaments/TournamentsHistory";

export const UserTournamentsPageSkeleton = () => {
  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-80 w-full rounded-xl" />
      <Skeleton className="min-h-[400px] w-full rounded-xl" />
    </div>
  );
};

export const UserTournamentsPage = async ({
  user,
  profile,
  scope,
  discipline,
  showGames = false
}: {
  user: User;
  /** Supplies the career Titles figure shown above the placement timeline. */
  profile: UserProfile;
  scope: StatsScope;
  discipline: string | null;
  /** "All games": rows mark their game. */
  showGames?: boolean;
}) => {
  // Scoped and cached (Next Data Cache); drives the master-detail Event dossier.
  const tournaments = await userService.getUserTournaments(user.id, discipline, scope === "all" ? "all" : undefined);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <TournamentsHistory
        tournaments={tournaments}
        selfUserId={user.id}
        tournamentsWon={profile.tournaments_won}
        showGames={showGames}
      />
    </div>
  );
};
