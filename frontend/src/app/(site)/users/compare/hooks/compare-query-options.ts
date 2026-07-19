import type { LogStatsName } from "@/types/stats.types";
import type { UserCompareBaselineMode, UserRoleType } from "@/types/user.types";

interface QueryContext {
  signal: AbortSignal;
}

interface CompareFilters {
  baseline: UserCompareBaselineMode;
  targetUserId?: number;
  role?: UserRoleType;
  divMin?: number;
  divMax?: number;
  tournamentId?: number;
}

export interface OverallCompareRequest extends CompareFilters {
  signal?: AbortSignal;
}

export interface HeroCompareRequest extends CompareFilters {
  leftHeroId?: number;
  rightHeroId?: number;
  mapId?: number;
  stats: LogStatsName[];
  signal?: AbortSignal;
}

interface OverallOptions<TData> extends CompareFilters {
  isHeroScope: boolean;
  subjectUserId?: number;
  fetchCompare: (userId: number, request: OverallCompareRequest) => Promise<TData>;
}

interface HeroOptions<TData> extends CompareFilters {
  isHeroScope: boolean;
  subjectUserId?: number;
  leftHeroId?: number;
  rightHeroId?: number;
  mapId?: number;
  stats: LogStatsName[];
  fetchCompare: (userId: number, request: HeroCompareRequest) => Promise<TData>;
}

export const keepPreviousCompareData = <TData>(previous: TData | undefined) => previous;

export const shouldLoadHeroCatalogs = (isHeroScope: boolean) => isHeroScope;

export const getCompareActivity = ({
  isLoading,
  isFetching
}: {
  isLoading: boolean;
  isFetching: boolean;
}) => ({
  isInitialLoading: isLoading,
  isRefreshing: isFetching && !isLoading
});

export const buildOverallCompareQueryOptions = <TData>({
  isHeroScope,
  subjectUserId,
  baseline,
  targetUserId,
  role,
  divMin,
  divMax,
  tournamentId,
  fetchCompare
}: OverallOptions<TData>) => ({
  queryKey: [
    "user-compare",
    subjectUserId,
    baseline,
    targetUserId,
    role,
    divMin,
    divMax,
    tournamentId
  ] as const,
  enabled: !isHeroScope && subjectUserId !== undefined,
  placeholderData: keepPreviousCompareData<TData>,
  queryFn: ({ signal }: QueryContext) =>
    fetchCompare(subjectUserId!, {
      baseline,
      targetUserId,
      role,
      divMin,
      divMax,
      tournamentId,
      signal
    })
});

export const buildHeroCompareQueryOptions = <TData>({
  isHeroScope,
  subjectUserId,
  baseline,
  targetUserId,
  role,
  divMin,
  divMax,
  tournamentId,
  leftHeroId,
  rightHeroId,
  mapId,
  stats,
  fetchCompare
}: HeroOptions<TData>) => ({
  queryKey: [
    "user-hero-compare",
    subjectUserId,
    baseline,
    targetUserId,
    role,
    divMin,
    divMax,
    tournamentId,
    leftHeroId,
    rightHeroId,
    mapId
  ] as const,
  enabled: isHeroScope && subjectUserId !== undefined,
  placeholderData: keepPreviousCompareData<TData>,
  queryFn: ({ signal }: QueryContext) =>
    fetchCompare(subjectUserId!, {
      baseline,
      targetUserId,
      leftHeroId,
      rightHeroId,
      mapId,
      role,
      divMin,
      divMax,
      tournamentId,
      stats,
      signal
    })
});
