import { Suspense, cache } from "react";
import type { CharacterSummary, CharacterWithUserStats, User, UserProfile } from "@/types/user.types";
import { AchievementRarity } from "@/types/achievement.types";
import userService from "@/services/user.service";
import disciplineService from "@/services/discipline.service";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import OverviewLastTournamentCard from "@/app/(site)/users/components/overview/OverviewLastTournamentCard";
import OverviewRoleSplit from "@/app/(site)/users/components/overview/OverviewRoleSplit";
import OverviewRecentEncounters from "@/app/(site)/users/components/overview/OverviewRecentEncounters";
import OverviewCareerList from "@/app/(site)/users/components/overview/OverviewCareerList";
import OverviewTeammatesSynergy from "@/app/(site)/users/components/overview/OverviewTeammatesSynergy";
import CharacterStatsTable from "@/components/profile/CharacterStatsTable";
import ProfileWidget from "@/components/profile/ProfileWidget";
import OverviewAchievementsPreview from "@/app/(site)/users/components/overview/OverviewAchievementsPreview";
import { tournamentMapPips } from "@/app/(site)/users/components/overview/map-results";
import { tournamentOptions } from "@/app/(site)/users/components/shared/list-utils";
import { USER_ENCOUNTER_ENTITIES } from "@/app/(site)/users/components/shared/encounter-perspective";
import { getPlayerSlug } from "@/lib/player";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";

interface OverviewPageProps {
  profile: UserProfile;
  user: User;
  tournamentId?: number;
  scope: StatsScope;
  /** The one game the profile shows; every stats read below names it. */
  discipline: string;
  /** The workspace axis the profile is viewed on: role names and hues read that axis's ontology. */
  axis: WorkspaceAxis;
}

/** What a section reads with. */
interface SectionProps {
  user: User;
  scope: StatsScope;
  discipline: string;
  /** The viewed workspace axis the game's metadata is read on (tenant host: its own). */
  axis: WorkspaceAxis;
}

// Reads shared by more than one section. `cache()` collapses them to a single
// request per render even though each section awaits them from its own
// Suspense boundary.
const getTournaments = cache((userId: number, scope: StatsScope, discipline: string) =>
  userService
    .getUserTournaments(userId, discipline, scope === "all" ? "all" : undefined)
    .then((list) => list.results)
    .catch(() => [])
);
// One array for every section: the RSC payload writes an object once and refers back to it, so the top characters
// and the role split's signatures carry a single copy of the list.
const getCharacterCards = cache(async (userId: number, scope: StatsScope, discipline: string) =>
  characterCards(
    (await userService.getUserCharacters(userId, discipline, { scope }).catch(() => null))?.results ?? []
  )
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
  // The role and stats are drawn in the tournament's own community and game, a scope no other block reads: read here
  // too, so the first paint names them. A failed read is left to the browser.
  const metadata = await disciplineService
    .metadata(tournament.workspace_id, tournament.discipline)
    .catch(() => undefined);

  return (
    <OverviewLastTournamentCard
      tournament={tournament}
      metadata={metadata}
      tournaments={tournamentOptions(profile.tournaments)}
      userId={user.id}
      mapPips={tournamentMapPips(tournamentEncounters, user.id)}
    />
  );
};

const CareerListSection = async ({ user, profile, scope, discipline }: SectionProps & { profile: UserProfile }) => (
  <OverviewCareerList profile={profile} tournaments={await getTournaments(user.id, scope, discipline)} />
);

/**
 * What the overview's character cards read: each character without its per-stat best-match records (they would ride
 * the RSC payload once per stat per row); the game record and the one career-best `record` stay.
 */
const characterCards = (characters: CharacterWithUserStats[]): CharacterSummary[] =>
  characters.map(({ stats, ...character }) => ({
    ...character,
    stats: stats.map(({ name, overall, avg_10, avg_10_all }) => ({ name, overall, avg_10, avg_10_all }))
  }));

const TopHeroesSection = async ({ user, userSlug, scope, discipline, axis }: SectionProps & { userSlug: string }) => {
  const characters = await getCharacterCards(user.id, scope, discipline);
  if (characters.length === 0) return null;
  return (
    <ProfileWidget
      axis={axis}
      discipline={discipline}
      slot="topCharacters"
      props={{ characters, userSlug }}
      fallback={<CharacterStatsTable axis={axis} discipline={discipline} characters={characters} limit={8} />}
    />
  );
};

const RecentEncountersSection = async ({ user, scope, discipline }: SectionProps) => {
  const [encounters, tournaments] = await Promise.all([
    userService
      .getUserEncounters(user.id, discipline, 1, 5, "played_at", "desc", USER_ENCOUNTER_ENTITIES, undefined, scope)
      .catch(() => ({ results: [], total: 0 })),
    getTournaments(user.id, scope, discipline)
  ]);
  return (
    <OverviewRecentEncounters
      encounters={encounters.results}
      userId={user.id}
      userName={user.name}
      tournaments={tournaments}
    />
  );
};

const RoleSplitSection = async ({
  user,
  profile,
  scope,
  discipline,
  axis
}: SectionProps & { profile: UserProfile }) => {
  const characters = await getCharacterCards(user.id, scope, discipline);
  const { roles, maps_total, tournaments_count } = profile;
  return (
    <OverviewRoleSplit
      profile={{ roles, maps_total, tournaments_count }}
      discipline={discipline}
      axis={axis}
      characters={characters}
    />
  );
};

const AchievementsSection = async ({
  user,
  userSlug,
  scope,
  discipline
}: Pick<SectionProps, "user" | "scope" | "discipline"> & { userSlug: string }) => {
  // The preview draws each tile's own fields: no links to where it was earned.
  const achievements = await userService
    .getUserAchievements(user.id, { scope, discipline, entities: [] })
    .catch(() => [] as AchievementRarity[]);
  return <OverviewAchievementsPreview achievements={achievements} userSlug={userSlug} />;
};

const TeammatesSection = async ({ user, scope, discipline }: SectionProps) => {
  const teammates = await userService
    .getUserBestTeammates(user.id, discipline, -1, scope)
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
 * career-wide teammates read is unbounded and used to gate the whole grid.
 */
const UserOverviewPage = ({ profile, tournamentId, user, scope, discipline, axis }: OverviewPageProps) => {
  const userSlug = getPlayerSlug(user.name);
  const section = { user, scope, discipline, axis };

  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_380px] xl:items-start">
      <div className="flex min-w-0 flex-col gap-3.5">
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" />}>
          <LastTournamentSection user={user} profile={profile} tournamentId={tournamentId} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-[26rem] w-full rounded-xl" />}>
          <CareerListSection {...section} profile={profile} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
          <TopHeroesSection {...section} userSlug={userSlug} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-80 w-full rounded-xl" />}>
          <RecentEncountersSection {...section} />
        </Suspense>
      </div>
      {/* Below the tab strip's z-40 so it scrolls under the bar, not through it. */}
      <aside className="z-30 flex min-w-0 flex-col gap-3.5 xl:sticky xl:top-[var(--aqt-sticky-top)]">
        <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
          <RoleSplitSection {...section} profile={profile} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" />}>
          <AchievementsSection user={user} userSlug={userSlug} scope={scope} discipline={discipline} />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-80 w-full rounded-xl" />}>
          <TeammatesSection {...section} />
        </Suspense>
      </aside>
    </div>
  );
};

export default UserOverviewPage;
