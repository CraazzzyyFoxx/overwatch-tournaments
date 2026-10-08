import { Suspense, cache } from "react";
import { User, UserProfile } from "@/types/user.types";
import { AchievementRarity } from "@/types/achievement.types";
import userService from "@/services/user.service";
import { Skeleton } from "@/components/ui/skeleton";
import OverviewLastTournamentCard from "@/app/(site)/users/components/overview/OverviewLastTournamentCard";
import OverviewRoleSplit from "@/app/(site)/users/components/overview/OverviewRoleSplit";
import OverviewRecentEncounters from "@/app/(site)/users/components/overview/OverviewRecentEncounters";
import OverviewCareerList from "@/app/(site)/users/components/overview/OverviewCareerList";
import OverviewTeammatesSynergy from "@/app/(site)/users/components/overview/OverviewTeammatesSynergy";
import OverviewTopHeroesTable from "@/app/(site)/users/components/overview/OverviewTopHeroesTable";
import OverviewAchievementsPreview from "@/app/(site)/users/components/overview/OverviewAchievementsPreview";
import { tournamentMapPips } from "@/app/(site)/users/components/overview/map-results";
import { getPlayerSlug } from "@/lib/player";
import type { StatsScope } from "@/lib/site/stats-scope";

interface OverviewPageProps {
  profile: UserProfile;
  user: User;
  tournamentId?: number;
  scope: StatsScope;
}

// Reads shared by more than one section. `cache()` collapses them to a single
// request per render even though each section awaits them from its own
// Suspense boundary.
const getTournaments = cache((userId: number, scope: StatsScope) =>
  userService.getUserTournaments(userId, scope === "all" ? "all" : undefined).catch(() => [])
);
const getHeroes = cache((userId: number, scope: StatsScope) =>
  userService.getUserHeroes(userId, undefined, undefined, scope).catch(() => null)
);
const getMaps = cache((userId: number, scope: StatsScope) =>
  userService.getUserMaps(userId, { perPage: -1, minCount: 1, scope }).catch(() => null)
);

export const UserOverviewPageSkeleton = () => {
  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_380px]">
      <div className="flex min-w-0 flex-col gap-3.5">
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-[26rem] w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
      <div className="flex min-w-0 flex-col gap-3.5">
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
    </div>
  );
};

const LastTournamentSection = async ({
  user,
  profile,
  tournamentId
}: {
  user: User;
  profile: UserProfile;
  tournamentId?: number;
}) => {
  const resolvedTournamentId = tournamentId ?? profile.tournaments[0]?.id;
  if (!resolvedTournamentId) return null;

  const [tournament, tournamentEncounters] = await Promise.all([
    userService.getUserTournament(user.id, resolvedTournamentId),
    userService.getUserTournamentEncounters(user.id, resolvedTournamentId).catch(() => [])
  ]);
  if (!tournament) return null;

  return (
    <OverviewLastTournamentCard
      tournament={tournament}
      tournaments={profile.tournaments}
      userId={user.id}
      mapPips={tournamentMapPips(tournamentEncounters, user.id)}
    />
  );
};

const CareerListSection = async ({
  user,
  profile,
  scope
}: {
  user: User;
  profile: UserProfile;
  scope: StatsScope;
}) => <OverviewCareerList profile={profile} tournaments={await getTournaments(user.id, scope)} />;

const TopHeroesSection = async ({
  user,
  userSlug,
  scope
}: {
  user: User;
  userSlug: string;
  scope: StatsScope;
}) => {
  const [heroesRes, mapsRes] = await Promise.all([
    getHeroes(user.id, scope),
    getMaps(user.id, scope)
  ]);
  return (
    <OverviewTopHeroesTable
      heroes={heroesRes?.results ?? []}
      maps={mapsRes?.results ?? []}
      userSlug={userSlug}
    />
  );
};

const RecentEncountersSection = async ({ user, scope }: { user: User; scope: StatsScope }) => {
  const [encounters, tournaments] = await Promise.all([
    userService
      .getUserEncounters(
        user.id,
        1,
        5,
        "played_at",
        "desc",
        ["tournament", "stage", "stage_item", "home_team", "away_team", "matches.map"],
        undefined,
        scope
      )
      .catch(() => ({ results: [], total: 0 })),
    getTournaments(user.id, scope)
  ]);
  return (
    <OverviewRecentEncounters
      encounters={encounters.results}
      userName={user.name}
      tournaments={tournaments}
    />
  );
};

const RoleSplitSection = async ({
  user,
  profile,
  scope
}: {
  user: User;
  profile: UserProfile;
  scope: StatsScope;
}) => {
  const [heroesRes, mapsRes] = await Promise.all([
    getHeroes(user.id, scope),
    getMaps(user.id, scope)
  ]);
  return (
    <OverviewRoleSplit
      profile={profile}
      heroes={heroesRes?.results ?? []}
      maps={mapsRes?.results ?? []}
    />
  );
};

const AchievementsSection = async ({
  user,
  userSlug,
  scope
}: {
  user: User;
  userSlug: string;
  scope: StatsScope;
}) => {
  const achievements = await userService
    .getUserAchievements(user.id, { scope })
    .catch(() => [] as AchievementRarity[]);
  return <OverviewAchievementsPreview achievements={achievements} userSlug={userSlug} />;
};

const TeammatesSection = async ({ user, scope }: { user: User; scope: StatsScope }) => {
  const teammates = await userService
    .getUserBestTeammates(user.id, -1, scope)
    .catch(() => ({ results: [], total: 0 }));
  if (teammates.results.length === 0) return null;

  return (
    <OverviewTeammatesSynergy
      teammates={teammates.results}
      totalCount={teammates.total ?? teammates.results.length}
      totalMaps={teammates.results.reduce((sum, tm) => sum + (tm.tournaments ?? 0), 0)}
    />
  );
};

/**
 * Overview tab. Every section fetches behind its own Suspense boundary so the
 * tab paints at the pace of the fastest read instead of the slowest — the
 * career-wide teammates and maps reads are unbounded and used to gate the
 * whole grid.
 */
const UserOverviewPage = ({ profile, tournamentId, user, scope }: OverviewPageProps) => {
  const userSlug = getPlayerSlug(user.name);

  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_380px] xl:items-start">
      <div className="flex min-w-0 flex-col gap-3.5">
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" />}>
          <LastTournamentSection user={user} profile={profile} tournamentId={tournamentId} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-[26rem] w-full rounded-xl" />}>
          <CareerListSection user={user} profile={profile} scope={scope} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
          <TopHeroesSection user={user} userSlug={userSlug} scope={scope} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-80 w-full rounded-xl" />}>
          <RecentEncountersSection user={user} scope={scope} />
        </Suspense>
      </div>
      {/* Below the tab strip's z-40 so it scrolls under the bar, not through it. */}
      <aside className="z-30 flex min-w-0 flex-col gap-3.5 xl:sticky xl:top-[var(--aqt-sticky-top)]">
        <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
          <RoleSplitSection user={user} profile={profile} scope={scope} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" />}>
          <AchievementsSection user={user} userSlug={userSlug} scope={scope} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-80 w-full rounded-xl" />}>
          <TeammatesSection user={user} scope={scope} />
        </Suspense>
      </aside>
    </div>
  );
};

export default UserOverviewPage;
