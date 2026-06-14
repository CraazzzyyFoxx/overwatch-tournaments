import encounterService from "@/services/encounter.service";
import type { Encounter, EncounterOverview } from "@/types/encounter.types";
import type { PaginatedResponse } from "@/types/pagination.types";
import EncountersRedesignClient from "./_components/EncountersRedesignClient";
import {
  ENCOUNTERS_PAGE_SIZE,
  filtersToApiFilters,
  normalizeEncounterFilters,
} from "./_components/encounters-redesign.helpers";

const DEFAULT_PAGE = 1;

function emptyEncounters(page: number): PaginatedResponse<Encounter> {
  return {
    page,
    per_page: ENCOUNTERS_PAGE_SIZE,
    total: 0,
    results: [],
  };
}

const EMPTY_OVERVIEW: EncounterOverview = {
  kpis: {
    total_encounters: 0,
    recent_count: 0,
    with_logs_count: 0,
    with_logs_pct: 0,
    avg_closeness: null,
    live_now_count: 0,
    upcoming_count: 0,
  },
  preset_counts: {
    all: 0,
    my_team: 0,
    finals: 0,
    close_bo5: 0,
    upsets: 0,
    with_logs: 0,
  },
  closeness_histogram: [],
  score_heatmap: [],
  stage_split: [],
  featured: {
    closest: [],
    upcoming: [],
    live: [],
  },
  hot_maps: [],
  pulse: {
    avg_series_seconds: null,
    completed_series_count: 0,
    sweep_rate: 0,
    sweep_count: 0,
    went_distance_count: 0,
    reverse_sweep_rate: 0,
    most_decisive_map: null,
  },
  side_balance: {
    home_wins: 0,
    away_wins: 0,
    home_win_pct: 0,
    away_win_pct: 0,
  },
};

type EncountersPageProps = {
  searchParams: Promise<{
    page?: string;
    search?: string;
    query?: string;
    stage_id?: string;
    stage_item_id?: string;
    best_of?: string;
    status?: string;
    has_logs?: string;
    closeness_min?: string;
    closeness_max?: string;
    scope?: string;
    sort?: string;
  }>;
};

type ParsedSearchParams = {
  page: number;
  filters: ReturnType<typeof normalizeEncounterFilters>;
};

function parseSearchParams(params: Record<string, string | undefined>): ParsedSearchParams {
  const parsedPage = Number.parseInt(params.page ?? String(DEFAULT_PAGE), 10);
  const page = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : DEFAULT_PAGE;

  return {
    page,
    filters: normalizeEncounterFilters(params),
  };
}

async function EncountersContent({ page, filters }: ParsedSearchParams) {
  const apiFilters = filtersToApiFilters(filters);
  let initialError: string | null = null;
  let data = emptyEncounters(page);
  let overview = EMPTY_OVERVIEW;

  try {
    [data, overview] = await Promise.all([
      encounterService.getAll(
        page,
        filters.query,
        null,
        ENCOUNTERS_PAGE_SIZE,
        apiFilters.sort ?? "id",
        "desc",
        undefined,
        {
          ...apiFilters,
          entities: [
            "tournament",
            "stage",
            "stage_item",
            "home_team",
            "away_team",
            "matches",
            "matches.map",
          ],
        },
      ),
      encounterService.getOverview(filters.query, apiFilters),
    ]);
  } catch {
    initialError = "Encounter data is temporarily unavailable. Retrying in the background.";
  }

  return (
    <EncountersRedesignClient
      initialData={data}
      initialOverview={overview}
      initialFilters={filters}
      initialPage={page}
      initialError={initialError}
    />
  );
}

export default async function EncountersPage({ searchParams }: EncountersPageProps) {
  const params = parseSearchParams(await searchParams);

  return <EncountersContent page={params.page} filters={params.filters} />;
}
