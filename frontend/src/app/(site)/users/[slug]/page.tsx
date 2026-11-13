import React, { Suspense, cache } from "react";
import userService from "@/services/user.service";
import disciplineService from "@/services/discipline.service";
import UserHeader from "@/app/(site)/users/components/header/UserHeader";
import { TabsContent } from "@/components/ui/tabs";
import UserOverviewPage, { UserOverviewPageSkeleton } from "@/app/(site)/users/_views/UserOverviewPage";
import UserMapsPage from "@/app/(site)/users/_views/UserMapsPage";
import { notFound } from "next/navigation";
import UserHeroesPage from "@/app/(site)/users/_views/UserHeroesPage";
import {
  UserEncountersPageSkeleton,
  UserEncountersPage
} from "@/app/(site)/users/_views/UserEncountersPage";
import type { MatchesFilters } from "@/app/(site)/users/components/matches/MatchesTable";
import { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import {
  UserTournamentsPage,
  UserTournamentsPageSkeleton
} from "@/app/(site)/users/_views/UserTournamentsPage";
import UserAchievementPage from "@/app/(site)/users/_views/UserAchievementPage";
import { SITE_NAME, SITE_URL_OBJ } from "@/config/site";
import { isDivisionGridRequired, isNotFoundError } from "@/lib/api/error";
import { decodePlayerSlug } from "@/lib/player";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import UserTabsClient from "@/app/(site)/users/components/tabs/UserTabsClient";
import UserHeaderSkeleton from "@/app/(site)/users/components/header/UserHeaderSkeleton";
import { ProfileJsonLd } from "@/app/(site)/users/components/shared/profile-jsonld";
import UserProfileEmpty from "@/app/(site)/users/components/shared/UserProfileEmpty";
import ProfileGameTabs from "@/app/(site)/users/components/shared/ProfileGameTabs";
import ProfileGameData from "@/app/(site)/users/components/shared/ProfileGameData";
import ProfileNotPlayed from "@/app/(site)/users/components/shared/ProfileNotPlayed";
import { blockGameOf, orderPlayerGames } from "@/app/(site)/users/components/shared/profile-games";
import { tournamentOptions } from "@/app/(site)/users/components/shared/list-utils";
import { UsersMissingGrid } from "@/app/(site)/users/components/shared/UsersMissingGrid";
import ProfileScopeUnavailable from "@/app/(site)/users/components/shared/ProfileScopeUnavailable";
import { resolveStatsScope } from "@/lib/site/tenant-host";
import { resolveServerPageGame } from "@/lib/site/discipline-server";
import type { StatsScope } from "@/lib/site/stats-scope";
import type { GameScopeInit, WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { UserProfile } from "@/types/user.types";

// The route still renders dynamically (api-fetch reads the workspace cookie),
// but we no longer force `fetchCache: force-no-store` — public, workspace-scoped
// profile reads are tagged + revalidated in the Data Cache (see user.service),
// which cuts repeat TTFB and gives crawlers fast SSR HTML.

const USER_TABS = ["overview", "tournaments", "matches", "heroes", "maps", "achievements"] as const;
type UserTab = (typeof USER_TABS)[number];

type UserPageSearchParams = {
  tab?: string;
  discipline?: string | string[];
  tournamentId?: string;
  page?: string;
  selectedTournamentId?: string;
  achievementTournamentId?: string;
  // Matches-tab server-side filters
  mResult?: string;
  mStage?: string;
  mMvp1?: string;
  mLogs?: string;
  mOpp?: string;
};

/**
 * What every tab reads with (spec §6.6, a multi page): the viewing scope, the page's game — `null` under
 * "all games" — the workspace axis it is viewed on (host lock first) and the scope inputs the per-game tabs resolve
 * their game from.
 */
type ProfileView = { scope: StatsScope; game: string | null; axis: WorkspaceAxis; init: GameScopeInit };

const isUserTab = (value: string): value is UserTab => {
  return USER_TABS.includes(value as UserTab);
};

const toPositiveInt = (value: string | undefined, fallback: number) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return Math.floor(parsed);
};

export async function generateMetadata(props: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const params = await props.params;
  const t = await getTranslations();
  try {
    const user = await userService.getUserByName(decodePlayerSlug(params.slug));

    const title = t("users.profile.meta.title", { name: user.name, siteName: SITE_NAME });
    const description = t("users.profile.meta.description", { name: user.name, siteName: SITE_NAME });
    const canonical = new URL(`/users/${params.slug}`, SITE_URL_OBJ).toString();

    // OG/Twitter images are supplied by the colocated opengraph-image route
    // (Next auto-injects og:image + twitter:image), so we don't set them here.
    return {
      title,
      description,
      alternates: { canonical },
      robots: { index: true, follow: true },
      openGraph: {
        title,
        description,
        url: canonical,
        type: "profile",
        siteName: SITE_NAME,
        locale: "en_US"
      },
      twitter: {
        card: "summary_large_image",
        title,
        description
      }
    };
  } catch (error) {
    if (isNotFoundError(error)) {
      return {
        title: t("users.profile.meta.notFoundTitle", { siteName: SITE_NAME }),
        description: t("users.profile.meta.notFoundDescription", { siteName: SITE_NAME })
      };
    }
    throw error;
  }
}

const getUserAndProfile = cache(async (slug: string, scope: StatsScope, game: string | null) => {
  try {
    const user = await userService.getUserByName(decodePlayerSlug(slug));
    const profile = await userService.getUserProfile(user.id, game, scope);
    return { user, profile };
  } catch (error) {
    if (isNotFoundError(error)) {
      notFound();
    }
    throw error;
  }
});

type UserAndProfile = Awaited<ReturnType<typeof getUserAndProfile>>;

/**
 * What the profile's blocks read of the games, read once for the page alongside the profile: the metadata, on the
 * viewed axis, of every game the page can show — its game, or under "all games" each of the area's. A failed read is
 * left out: the browser reads it itself.
 */
const loadProfileGameMetadata = async (view: ProfileView) => {
  const codes = view.game === null ? (view.init.disciplines ?? []).map((entry) => entry.code) : [view.game];
  const metadata = await Promise.all(
    codes.map((code) => disciplineService.metadata(view.axis, code).catch(() => null))
  );
  return metadata.filter((entry) => entry !== null);
};

const gameNameOf = (view: ProfileView, code: string) =>
  view.init.disciplines?.find((entry) => entry.code === code)?.name ?? code;

const UserHeaderSection = async ({
  userAndProfile,
  slug,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  slug: string;
  view: ProfileView;
}) => {
  const { user, profile } = await userAndProfile;
  const canonical = new URL(`/users/${slug}`, SITE_URL_OBJ).toString();
  return (
    <>
      <ProfileJsonLd user={user} profile={profile} url={canonical} />
      <UserHeader user={user} profile={profile} scope={view.scope} discipline={view.game} axis={view.axis} />
    </>
  );
};

/**
 * A tab that reads one game (overview, characters, maps): the page's game, or under "all games" the per-game tab's
 * game (`blockGameOf`) with the tabs above it. That game's own profile (R15) is refused like the page's when the game
 * has no division grid on the viewed axis: the missing-grid notice then stands under the tabs.
 */
const PerGameTab = async ({
  userAndProfile,
  view,
  children
}: {
  userAndProfile: Promise<UserAndProfile>;
  view: ProfileView;
  /** `gameProfile` is the profile bound to `game` (role split, last-tournament dossier, per-game totals). */
  children: (game: string, gameProfile: UserProfile) => React.ReactNode;
}) => {
  const { user, profile } = await userAndProfile;
  if (view.game !== null) return children(view.game, profile);
  const game = blockGameOf(profile.games, view.init);
  if (game === null) return <UserProfileEmpty name={user.name} />;
  const tabs = (
    <ProfileGameTabs
      initial={view.init}
      games={orderPlayerGames(profile.games, view.init).map((entry) => entry.discipline)}
    />
  );
  let gameProfile: UserProfile;
  try {
    gameProfile = await userService.getUserProfile(user.id, game, view.scope);
  } catch (error) {
    if (!isDivisionGridRequired(error)) throw error;
    return (
      <>
        {tabs}
        <UsersMissingGrid discipline={game} gameName={gameNameOf(view, game)} axis={view.axis} />
      </>
    );
  }
  return (
    <>
      {tabs}
      {children(game, gameProfile)}
    </>
  );
};

const UserOverviewTab = async ({
  userAndProfile,
  tournamentId,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  tournamentId?: number;
  view: ProfileView;
}) => {
  const { user } = await userAndProfile;
  return (
    <PerGameTab userAndProfile={userAndProfile} view={view}>
      {(game, gameProfile) => (
        <UserOverviewPage
          user={user}
          profile={gameProfile}
          tournamentId={tournamentId}
          scope={view.scope}
          discipline={game}
          axis={view.axis}
        />
      )}
    </PerGameTab>
  );
};

const UserTournamentsTab = async ({
  userAndProfile,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  view: ProfileView;
}) => {
  const { user, profile } = await userAndProfile;
  return (
    <UserTournamentsPage
      user={user}
      profile={profile}
      scope={view.scope}
      discipline={view.game}
      showGames={view.game === null}
    />
  );
};

const UserMatchesTab = async ({
  userAndProfile,
  page,
  filters,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  page: number;
  filters?: MatchesFilters;
  view: ProfileView;
}) => {
  const { user, profile } = await userAndProfile;
  // The list spans every game; its summary sidebars are one game's, picked like the per-game tabs.
  const summaryGame = view.game ?? blockGameOf(profile.games, view.init);
  return (
    <UserEncountersPage
      user={user}
      page={page}
      filters={filters}
      scope={view.scope}
      discipline={view.game}
      summaryGame={summaryGame}
      sidebarTabs={
        view.game === null ? (
          <ProfileGameTabs
            initial={view.init}
            games={orderPlayerGames(profile.games, view.init).map((entry) => entry.discipline)}
          />
        ) : null
      }
    />
  );
};

const UserMapsTab = async ({
  userAndProfile,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  view: ProfileView;
}) => {
  const { user } = await userAndProfile;
  return (
    <PerGameTab userAndProfile={userAndProfile} view={view}>
      {(game, gameProfile) => (
        <UserMapsPage
          user={user}
          tournaments={tournamentOptions(gameProfile.tournaments)}
          scope={view.scope}
          discipline={game}
          axis={view.axis}
        />
      )}
    </PerGameTab>
  );
};

const UserHeroesTab = async ({
  userAndProfile,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  view: ProfileView;
}) => {
  const { user } = await userAndProfile;
  return (
    <PerGameTab userAndProfile={userAndProfile} view={view}>
      {(game, gameProfile) => (
        <UserHeroesPage
          user={user}
          tournaments={tournamentOptions(gameProfile.tournaments)}
          scope={view.scope}
          discipline={game}
          axis={view.axis}
        />
      )}
    </PerGameTab>
  );
};

const UserAchievementsTab = async ({
  userAndProfile,
  selectedTournamentId,
  view
}: {
  userAndProfile: Promise<UserAndProfile>;
  selectedTournamentId?: string;
  view: ProfileView;
}) => {
  const { user, profile } = await userAndProfile;
  return (
    <UserAchievementPage
      user={user}
      tournaments={tournamentOptions(profile.tournaments)}
      selectedTournamentId={selectedTournamentId}
      scope={view.scope}
      discipline={view.game ?? undefined}
      showGames={view.game === null}
    />
  );
};

const resolveTabContent = ({
  activeTab,
  userAndProfile,
  tournamentId,
  pageNumber,
  achievementTournamentId,
  matchFilters,
  view
}: {
  activeTab: UserTab;
  userAndProfile: Promise<UserAndProfile>;
  tournamentId?: number;
  pageNumber: number;
  achievementTournamentId?: string;
  matchFilters?: MatchesFilters;
  view: ProfileView;
}) => {
  switch (activeTab) {
    case "overview":
      return {
        value: "overview",
        fallback: <UserOverviewPageSkeleton />,
        content: <UserOverviewTab userAndProfile={userAndProfile} tournamentId={tournamentId} view={view} />
      };
    case "tournaments":
      return {
        value: "tournaments",
        fallback: <UserTournamentsPageSkeleton />,
        content: <UserTournamentsTab userAndProfile={userAndProfile} view={view} />
      };
    case "matches":
      return {
        value: "matches",
        fallback: <UserEncountersPageSkeleton />,
        content: (
          <UserMatchesTab userAndProfile={userAndProfile} page={pageNumber} filters={matchFilters} view={view} />
        )
      };
    case "maps":
      return {
        value: "maps",
        fallback: <Skeleton className="min-h-150 w-full rounded-xl" />,
        content: <UserMapsTab userAndProfile={userAndProfile} view={view} />
      };
    case "heroes":
      return {
        value: "heroes",
        fallback: <Skeleton className="min-h-150 w-full rounded-xl" />,
        content: <UserHeroesTab userAndProfile={userAndProfile} view={view} />
      };
    case "achievements":
      return {
        value: "achievements",
        fallback: <Skeleton className="min-h-150 w-full rounded-xl" />,
        content: (
          <UserAchievementsTab
            userAndProfile={userAndProfile}
            selectedTournamentId={achievementTournamentId}
            view={view}
          />
        )
      };
  }
};

/**
 * The profile body: the tab strip (with its count badges), or — for a player with no tournament in view — one
 * panel: the empty career under "all games", "{player} never played {game}" under a game (spec §6.6).
 */
const ProfileBody = async ({
  userAndProfile,
  activeTab,
  view,
  children
}: {
  userAndProfile: Promise<UserAndProfile>;
  activeTab: UserTab;
  view: ProfileView;
  children: React.ReactNode;
}) => {
  const { user, profile } = await userAndProfile;

  // Any tournament at all — including a league or one still in progress, whose
  // final placement (and therefore `tournaments_count`) does not exist yet.
  if (profile.tournaments.length === 0) {
    return view.game === null ? (
      <UserProfileEmpty name={user.name} />
    ) : (
      <ProfileNotPlayed player={user.name} game={gameNameOf(view, view.game)} />
    );
  }

  return (
    <UserTabsClient
      activeTab={activeTab}
      badges={{
        tournaments: profile.tournaments_count ?? null,
        // Characters are one game's: no count across games.
        heroes: view.game === null ? null : profile.characters_count,
        maps: profile.maps_total ?? null
      }}
    >
      {children}
    </UserTabsClient>
  );
};

/**
 * The profile, or — when the viewed axis has no division grid for the page's game (the server's
 * `division_grid_required`) — the missing-grid notice in its place. The cross-game profile reads no grid.
 */
const ProfileOrMissingGrid = async ({
  userAndProfile,
  gameMetadata,
  view,
  children
}: {
  userAndProfile: Promise<UserAndProfile>;
  gameMetadata: ReturnType<typeof loadProfileGameMetadata>;
  view: ProfileView;
  children: React.ReactNode;
}) => {
  try {
    await userAndProfile;
  } catch (error) {
    if (!isDivisionGridRequired(error) || view.game === null) throw error;
    return <UsersMissingGrid discipline={view.game} gameName={gameNameOf(view, view.game)} axis={view.axis} />;
  }
  return (
    <ProfileGameData axis={view.axis} metadata={await gameMetadata}>
      {children}
    </ProfileGameData>
  );
};

export default async function UserPage({
  params,
  searchParams
}: Readonly<{
  params: Promise<{ slug: string }>;
  searchParams: Promise<UserPageSearchParams>;
}>) {
  const resolvedParams = await params;
  const resolvedSearchParams = await searchParams;
  const [scope, page] = await Promise.all([
    resolveStatsScope(),
    resolveServerPageGame("multi", resolvedSearchParams.discipline)
  ]);
  // Without the installed games there is no scope to read: an error, never a guessed one.
  if (page.resolution === null) throw new Error("The installed games could not be read.");
  const kind = page.resolution.game.kind;
  if (kind === "invalid" || kind === "empty") {
    return <ProfileScopeUnavailable initial={page.init} />;
  }
  const view: ProfileView = {
    scope,
    game: page.resolution.game.kind === "game" ? page.resolution.game.code : null,
    axis: page.init.axis,
    init: page.init
  };
  const userAndProfile = getUserAndProfile(resolvedParams.slug, scope, view.game);
  const gameMetadata = loadProfileGameMetadata(view);

  const requestedTab = resolvedSearchParams.tab ?? "overview";
  const activeTab: UserTab = isUserTab(requestedTab) ? requestedTab : "overview";

  const tournamentId = toPositiveInt(resolvedSearchParams.tournamentId, 0) || undefined;
  const pageNumber = toPositiveInt(resolvedSearchParams.page, 1);
  const achievementTournamentId = resolvedSearchParams.achievementTournamentId;
  const { mResult, mStage, mMvp1, mLogs, mOpp } = resolvedSearchParams;
  const matchFilters: MatchesFilters = {
    result: mResult === "win" || mResult === "loss" || mResult === "draw" ? mResult : undefined,
    stage: mStage === "group" || mStage === "playoffs" || mStage === "finals" ? mStage : undefined,
    // MVP is one game's fact: no MVP filter across games.
    mvp1: view.game !== null && mMvp1 === "1",
    hasLogs: mLogs === "1",
    opponent: mOpp || undefined
  };
  const tabContent = resolveTabContent({
    activeTab,
    userAndProfile,
    tournamentId,
    pageNumber,
    achievementTournamentId,
    matchFilters,
    view
  });
  return (
    <Suspense
      fallback={
        <>
          <UserHeaderSkeleton />
          <UserTabsClient activeTab={activeTab}>
            <TabsContent value={tabContent.value} className="mt-0">
              {tabContent.fallback}
            </TabsContent>
          </UserTabsClient>
        </>
      }
    >
      <ProfileOrMissingGrid userAndProfile={userAndProfile} gameMetadata={gameMetadata} view={view}>
        <Suspense fallback={<UserHeaderSkeleton />}>
          <UserHeaderSection userAndProfile={userAndProfile} slug={resolvedParams.slug} view={view} />
        </Suspense>
        <Suspense
          fallback={
            <UserTabsClient activeTab={activeTab}>
              <Suspense fallback={tabContent.fallback}>
                <TabsContent value={tabContent.value} className="mt-0">
                  {tabContent.content}
                </TabsContent>
              </Suspense>
            </UserTabsClient>
          }
        >
          <ProfileBody userAndProfile={userAndProfile} activeTab={activeTab} view={view}>
            <Suspense fallback={tabContent.fallback}>
              <TabsContent value={tabContent.value} className="mt-0">
                {tabContent.content}
              </TabsContent>
            </Suspense>
          </ProfileBody>
        </Suspense>
      </ProfileOrMissingGrid>
    </Suspense>
  );
}
