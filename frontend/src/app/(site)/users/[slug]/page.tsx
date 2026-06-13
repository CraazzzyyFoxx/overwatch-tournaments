import React, { Suspense, cache } from "react";
import userService from "@/services/user.service";
import UserHeader from "@/app/(site)/users/components/UserHeader";
import { TabsContent } from "@/components/ui/tabs";
import UserOverviewPage, { UserOverviewPageSkeleton } from "@/app/(site)/users/pages/UserOverviewPage";
import UserMapsPage from "@/app/(site)/users/pages/UserMapsPage";
import { notFound, redirect } from "next/navigation";
import UserHeroesPage from "@/app/(site)/users/pages/UserHeroesPage";
import {
  UserEncountersPageSkeleton,
  UserEncountersPage
} from "@/app/(site)/users/pages/UserEncountersPage";
import type { MatchesFilters } from "@/app/(site)/users/components/redesign/MatchesTable";
import { Metadata } from "next";
import {
  UserTournamentsPage,
  UserTournamentsPageSkeleton
} from "@/app/(site)/users/pages/UserTournamentsPage";
import UserAchievementPage from "@/app/(site)/users/pages/UserAchievementPage";
import { SITE_NAME } from "@/config/site";
import { ApiError } from "@/lib/api-error";
import { decodePlayerSlug } from "@/utils/player";
import { Skeleton } from "@/components/ui/skeleton";
import UserTabsClient from "@/app/(site)/users/components/UserTabsClient";
import UserLiquidGlassProvider from "@/app/(site)/users/components/UserLiquidGlassProvider";
import UserHeaderSkeleton from "@/app/(site)/users/components/UserHeaderSkeleton";

export const dynamic = "force-dynamic";

const USER_TABS = ["overview", "tournaments", "matches", "heroes", "maps", "achievements"] as const;
type UserTab = (typeof USER_TABS)[number];

type UserPageSearchParams = {
  tab?: string;
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
  try {
    const user = await userService.getUserByName(decodePlayerSlug(params.slug));

    return {
      title: `${user.name} Overview | ${SITE_NAME}`,
      description: `Overview for ${user.name} on ${SITE_NAME}.`,
      openGraph: {
        title: `${user.name} Overview | on ${SITE_NAME}.`,
        description: `Overview for ${user.name} on ${SITE_NAME}.`,
        url: SITE_NAME,
        type: "website",
        siteName: "AQT",
        images: [
          {
            url: `/avatar/${user.id % 10}.png`,
            width: 1200,
            height: 630
          }
        ],
        locale: "en_US"
      }
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return {
        title: `User Not Found | ${SITE_NAME}`,
        description: `The requested user profile could not be found on ${SITE_NAME}.`
      };
    }
    throw error;
  }
}

const getUserAndProfile = cache(async (slug: string) => {
  try {
    const user = await userService.getUserByName(decodePlayerSlug(slug));
    const profile = await userService.getUserProfile(user.id);
    return { user, profile };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
});

type UserAndProfile = Awaited<ReturnType<typeof getUserAndProfile>>;

const UserHeaderSection = async ({ userAndProfile }: { userAndProfile: Promise<UserAndProfile> }) => {
  const { user, profile } = await userAndProfile;
  return <UserHeader user={user} profile={profile} />;
};

const UserOverviewTab = async ({
  userAndProfile,
  tournamentId
}: {
  userAndProfile: Promise<UserAndProfile>;
  tournamentId?: number;
}) => {
  const { user, profile } = await userAndProfile;
  return <UserOverviewPage user={user} profile={profile} tournamentId={tournamentId} />;
};

const UserTournamentsTab = async ({ userAndProfile }: { userAndProfile: Promise<UserAndProfile> }) => {
  const { user } = await userAndProfile;
  return <UserTournamentsPage user={user} />;
};

const UserMatchesTab = async ({
  userAndProfile,
  page,
  filters
}: {
  userAndProfile: Promise<UserAndProfile>;
  page: number;
  filters?: MatchesFilters;
}) => {
  const { user } = await userAndProfile;
  return <UserEncountersPage user={user} page={page} filters={filters} />;
};

const UserMapsTab = async ({ userAndProfile }: { userAndProfile: Promise<UserAndProfile> }) => {
  const { user } = await userAndProfile;
  return <UserMapsPage user={user} />;
};

const UserHeroesTab = async ({ userAndProfile }: { userAndProfile: Promise<UserAndProfile> }) => {
  const { user } = await userAndProfile;
  return <UserHeroesPage user={user} />;
};

const UserAchievementsTab = async ({
  userAndProfile,
  selectedTournamentId
}: {
  userAndProfile: Promise<UserAndProfile>;
  selectedTournamentId?: string;
}) => {
  const { user } = await userAndProfile;
  return <UserAchievementPage user={user} selectedTournamentId={selectedTournamentId} />;
};

const resolveTabContent = ({
  activeTab,
  userAndProfile,
  tournamentId,
  pageNumber,
  achievementTournamentId,
  matchFilters
}: {
  activeTab: UserTab;
  userAndProfile: Promise<UserAndProfile>;
  tournamentId?: number;
  pageNumber: number;
  achievementTournamentId?: string;
  matchFilters?: MatchesFilters;
}) => {
  switch (activeTab) {
    case "overview":
      return {
        value: "overview",
        fallback: <UserOverviewPageSkeleton />,
        content: <UserOverviewTab userAndProfile={userAndProfile} tournamentId={tournamentId} />
      };
    case "tournaments":
      return {
        value: "tournaments",
        fallback: <UserTournamentsPageSkeleton />,
        content: <UserTournamentsTab userAndProfile={userAndProfile} />
      };
    case "matches":
      return {
        value: "matches",
        fallback: <UserEncountersPageSkeleton />,
        content: <UserMatchesTab userAndProfile={userAndProfile} page={pageNumber} filters={matchFilters} />
      };
    case "maps":
      return {
        value: "maps",
        fallback: <Skeleton className="min-h-150 w-full rounded-xl" />,
        content: <UserMapsTab userAndProfile={userAndProfile} />
      };
    case "heroes":
      return {
        value: "heroes",
        fallback: <Skeleton className="min-h-150 w-full rounded-xl" />,
        content: <UserHeroesTab userAndProfile={userAndProfile} />
      };
    case "achievements":
      return {
        value: "achievements",
        fallback: <Skeleton className="min-h-150 w-full rounded-xl" />,
        content: (
          <UserAchievementsTab
            userAndProfile={userAndProfile}
            selectedTournamentId={achievementTournamentId}
          />
        )
      };
  }
};

const TabsWithBadges = async ({
  userAndProfile,
  activeTab,
  children
}: {
  userAndProfile: Promise<UserAndProfile>;
  activeTab: UserTab;
  children: React.ReactNode;
}) => {
  const { profile } = await userAndProfile;
  const heroesCount = profile.heroes_count ?? null;
  const tournamentsCount = profile.tournaments_count ?? null;
  // Maps badge: not always available — approximate via maps_total
  const mapsTotal = profile.maps_total ?? null;

  return (
    <UserTabsClient
      activeTab={activeTab}
      badges={{
        tournaments: tournamentsCount,
        heroes: heroesCount,
        maps: mapsTotal
      }}
    >
      {children}
    </UserTabsClient>
  );
};

export default async function UserPage({
  params,
  searchParams
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<UserPageSearchParams>;
}) {
  const resolvedParams = await params;
  const resolvedSearchParams = await searchParams;
  const userAndProfile = getUserAndProfile(resolvedParams.slug);

  const requestedTab = resolvedSearchParams.tab ?? "overview";
  const activeTab: UserTab = isUserTab(requestedTab) ? requestedTab : "overview";

  if (!isUserTab(requestedTab)) {
    const searchParamsObj = new URLSearchParams();
    for (const [key, value] of Object.entries(resolvedSearchParams)) {
      if (typeof value === "string") {
        searchParamsObj.set(key, value);
      }
    }
    searchParamsObj.set("tab", "overview");
    redirect(`/users/${resolvedParams.slug}?${searchParamsObj.toString()}`);
  }

  const tournamentId = toPositiveInt(resolvedSearchParams.tournamentId, 0) || undefined;
  const pageNumber = toPositiveInt(resolvedSearchParams.page, 1);
  const achievementTournamentId = resolvedSearchParams.achievementTournamentId;
  const { mResult, mStage, mMvp1, mLogs, mOpp } = resolvedSearchParams;
  const matchFilters: MatchesFilters = {
    result: mResult === "win" || mResult === "loss" || mResult === "draw" ? mResult : undefined,
    stage: mStage === "group" || mStage === "playoffs" || mStage === "finals" ? mStage : undefined,
    mvp1: mMvp1 === "1",
    hasLogs: mLogs === "1",
    opponent: mOpp || undefined
  };
  const tabContent = resolveTabContent({
    activeTab,
    userAndProfile,
    tournamentId,
    pageNumber,
    achievementTournamentId,
    matchFilters
  });

  return (
    <UserLiquidGlassProvider>
      <Suspense fallback={<UserHeaderSkeleton />}>
        <UserHeaderSection userAndProfile={userAndProfile} />
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
        <TabsWithBadges userAndProfile={userAndProfile} activeTab={activeTab}>
          <Suspense fallback={tabContent.fallback}>
            <TabsContent value={tabContent.value} className="mt-0">
              {tabContent.content}
            </TabsContent>
          </Suspense>
        </TabsWithBadges>
      </Suspense>
    </UserLiquidGlassProvider>
  );
}
