"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  FileText,
  Loader2,
  Pin,
  Play,
  Save,
  Search,
  Trash2,
  Tv,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useDebounce } from "use-debounce";
import type { PaginatedResponse } from "@/types/pagination.types";
import type {
  Encounter,
  EncounterOverview,
  EncounterSavedView,
  EncounterScoreHeatmapCell,
  EncounterStageSplit,
} from "@/types/encounter.types";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useToast } from "@/hooks/use-toast";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { getCurrentPathForAuthRedirect } from "@/lib/auth-redirect";
import { cn } from "@/lib/utils";
import {
  applyBuiltInView,
  BUILT_IN_VIEWS,
  buildPageList,
  type BuiltInViewId,
  DEFAULT_FILTERS,
  ENCOUNTERS_PAGE_SIZE,
  EncounterFilterState,
  filtersToApiFilters,
  filtersToSearchParams,
  formatCompactDate,
  formatDuration,
  formatPercent,
  getEncounterStateLabel,
  getMediaSlots,
  getPlayedAt,
  getSeriesDuration,
  getStageBucket,
  getTeamColor,
  getTeamInitials,
  getWinnerSide,
  type MediaSlotKey,
  type TeamColor,
} from "./encounters-redesign.helpers";
import styles from "./EncountersRedesign.module.css";

type EncountersRedesignClientProps = {
  initialData: PaginatedResponse<Encounter>;
  initialOverview: EncounterOverview;
  initialFilters: EncounterFilterState;
  initialPage: number;
  initialError?: string | null;
};

const TEAM_COLOR_CLASS: Record<TeamColor, string> = {
  teal: styles.tgTeal,
  amber: styles.tgAmber,
  rose: styles.tgRose,
  violet: styles.tgViolet,
  blue: styles.tgBlue,
};

const STAGE_PILL_CLASS: Record<string, string> = {
  playoffs: styles.stagePillPlayoffs,
  group: styles.stagePillGroup,
  finals: styles.stagePillFinals,
};

const VIEW_SWATCH_HSL: Record<TeamColor, string> = {
  teal: "hsl(174 72% 46%)",
  amber: "hsl(38 95% 55%)",
  rose: "hsl(340 75% 58%)",
  violet: "hsl(270 70% 62%)",
  blue: "hsl(210 80% 60%)",
};

const STAGE_DONUT_COLORS = [
  "hsl(210 80% 60%)",
  "hsl(38 95% 55%)",
  "hsl(340 75% 58%)",
  "hsl(174 72% 46%)",
  "hsl(270 70% 62%)",
];

function countLabel(value?: number): string {
  return typeof value === "number" ? value.toLocaleString("en") : "-";
}

function tournamentLabel(encounter: Encounter): string {
  if (!encounter.tournament) return "Tournament";
  return encounter.tournament.is_league
    ? encounter.tournament.name
    : `Tournament ${encounter.tournament.number}`;
}

function stageLabel(encounter: Encounter): string {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? "Unassigned";
}

function selectedViewId(filters: EncounterFilterState): BuiltInViewId {
  if (filters.scope === "my_team") return "my_team";
  if (filters.best_of === 5 && filters.closeness_min === 0.6) return "close_bo5";
  if (filters.has_logs === true) return "with_logs";
  if (filters.status === "completed" && filters.sort === "closeness") return "upsets";
  if (filters.status === "completed") return "finals";
  return "all";
}

function toSavedFilterState(view: EncounterSavedView): EncounterFilterState {
  return {
    ...DEFAULT_FILTERS,
    ...view.filters,
    query: view.filters.query ?? "",
    sort:
      view.filters.sort === "closeness" || view.filters.sort === "upcoming"
        ? view.filters.sort
        : DEFAULT_FILTERS.sort,
    scope: view.filters.scope === "my_team" ? "my_team" : "all",
  };
}

function buildHeatmapMatrix(cells: EncounterScoreHeatmapCell[]) {
  const matrix: Record<string, number> = {};
  let max = 0;
  for (const cell of cells) {
    matrix[`${cell.home}-${cell.away}`] = cell.count;
    if (cell.count > max) max = cell.count;
  }
  const rows = [3, 2, 1, 0];
  const cols = [0, 1, 2, 3];
  return { matrix, rows, cols, max };
}

function donutSegments(stages: EncounterStageSplit[]) {
  const total = stages.reduce((sum, stage) => sum + stage.count, 0);
  if (total === 0) return { segments: [], total: 0 };
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = stages.slice(0, 5).map((stage, index) => {
    const fraction = stage.count / total;
    const length = fraction * circumference;
    const segment = {
      name: stage.name,
      count: stage.count,
      pct: stage.pct,
      color: STAGE_DONUT_COLORS[index % STAGE_DONUT_COLORS.length],
      dashArray: `${length.toFixed(2)} ${circumference.toFixed(2)}`,
      dashOffset: -offset,
    };
    offset += length;
    return segment;
  });
  return { segments, total, circumference, radius };
}

export default function EncountersRedesignClient({
  initialData,
  initialOverview,
  initialFilters,
  initialPage,
  initialError,
}: EncountersRedesignClientProps) {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { user } = useAuthProfile();
  const userKey = user?.username;
  const openAuthModal = useAuthModalStore((state) => state.open);
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const [filters, setFilters] = useState<EncounterFilterState>(initialFilters);
  const [searchValue, setSearchValue] = useState(initialFilters.query);
  const [debouncedSearch] = useDebounce(searchValue, 300);
  const [page, setPage] = useState(initialPage);
  const previousUrlRef = useRef({ page: initialPage, filters: initialFilters });
  const effectiveFilters = useMemo(
    () => ({ ...filters, query: debouncedSearch }),
    [debouncedSearch, filters],
  );

  useEffect(() => {
    const params = filtersToSearchParams(effectiveFilters, page);
    const nextUrl = params.toString() ? `${pathname}?${params.toString()}` : pathname;
    const previous = previousUrlRef.current;
    if (
      previous.page === page &&
      JSON.stringify(previous.filters) === JSON.stringify(effectiveFilters)
    ) {
      return;
    }

    window.history.replaceState(null, "", nextUrl);
    previousUrlRef.current = { page, filters: effectiveFilters };
  }, [effectiveFilters, page, pathname]);

  const apiFilters = useMemo(() => filtersToApiFilters(effectiveFilters), [effectiveFilters]);
  const listQuery = useQuery({
    queryKey: ["encounters-redesign", page, apiFilters, effectiveFilters.query],
    queryFn: () =>
      encounterService.getAll(
        page,
        effectiveFilters.query,
        null,
        ENCOUNTERS_PAGE_SIZE,
        apiFilters.sort ?? "id",
        "desc",
        currentWorkspaceId,
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
    initialData:
      page === initialPage && JSON.stringify(effectiveFilters) === JSON.stringify(initialFilters)
        ? initialData
        : undefined,
    placeholderData: (previous) => previous,
  });

  const overviewQuery = useQuery({
    queryKey: ["encounters-overview", apiFilters, effectiveFilters.query],
    queryFn: () =>
      encounterService.getOverview(effectiveFilters.query, apiFilters, currentWorkspaceId),
    initialData:
      JSON.stringify(effectiveFilters) === JSON.stringify(initialFilters)
        ? initialOverview
        : undefined,
    placeholderData: (previous) => previous,
    retry: 1,
  });

  const savedViewsQuery = useQuery({
    queryKey: ["encounters-saved-views", currentWorkspaceId, userKey],
    queryFn: () => encounterService.getSavedViews(currentWorkspaceId),
    enabled: Boolean(user && currentWorkspaceId != null),
    placeholderData: (previous) => previous,
    retry: false,
    staleTime: 60_000,
  });

  const tournamentsLookupQuery = useQuery({
    queryKey: ["encounters-tournaments-lookup", currentWorkspaceId],
    queryFn: () => tournamentService.lookup(currentWorkspaceId),
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const saveViewMutation = useMutation({
    mutationFn: ({ name }: { name: string }) =>
      encounterService.saveView(name, effectiveFilters, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounters-saved-views", currentWorkspaceId, userKey],
      });
      toast({ title: "View saved" });
    },
  });

  const deleteViewMutation = useMutation({
    mutationFn: ({ id }: { id: number }) =>
      encounterService.deleteView(id, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounters-saved-views", currentWorkspaceId, userKey],
      });
      toast({ title: "View deleted" });
    },
  });

  const overview = overviewQuery.data ?? initialOverview;
  const encounters = listQuery.data ?? initialData;
  const rows = encounters.results ?? [];
  const totalPages = Math.max(1, Math.ceil((encounters.total ?? 0) / ENCOUNTERS_PAGE_SIZE));
  const activeView = selectedViewId(effectiveFilters);
  const maxHistogram = Math.max(1, ...overview.closeness_histogram.map((bucket) => bucket.count));
  const heatmap = useMemo(() => buildHeatmapMatrix(overview.score_heatmap), [overview.score_heatmap]);
  const stageDonut = useMemo(() => donutSegments(overview.stage_split), [overview.stage_split]);
  const maxMapCount = Math.max(1, ...overview.hot_maps.map((map) => map.count));
  const liveOrUpcoming = overview.featured.live.length
    ? overview.featured.live
    : overview.featured.upcoming;
  const sortLabel =
    effectiveFilters.sort === "closeness"
      ? "Closeness"
      : effectiveFilters.sort === "upcoming"
        ? "Upcoming"
        : "Date";

  const setFilterPatch = (patch: Partial<EncounterFilterState>) => {
    setPage(1);
    setFilters((current) => ({ ...current, ...patch }));
  };

  const handleSaveCurrentView = () => {
    if (!user) {
      const nextPath = getCurrentPathForAuthRedirect(window.location);
      openAuthModal(nextPath);
      return;
    }
    const name = window.prompt("Saved view name", "Current view");
    if (!name?.trim()) return;
    saveViewMutation.mutate({ name: name.trim() });
  };

  const pageList = buildPageList(page, totalPages);
  const showingStart = rows.length ? (page - 1) * ENCOUNTERS_PAGE_SIZE + 1 : 0;
  const showingEnd = Math.min(page * ENCOUNTERS_PAGE_SIZE, encounters.total);

  const quickFilters: Array<{ id: string; label: string; count: number; active: boolean; onClick: () => void }> = [
    {
      id: "all",
      label: "All",
      count: overview.preset_counts.all ?? overview.kpis.total_encounters,
      active:
        effectiveFilters.status == null &&
        effectiveFilters.has_logs == null &&
        effectiveFilters.scope === "all",
      onClick: () => {
        setSearchValue("");
        setFilterPatch({
          status: null,
          has_logs: null,
          scope: "all",
        });
      },
    },
    {
      id: "live",
      label: "Live",
      count: overview.kpis.live_now_count,
      active: effectiveFilters.status === "live",
      onClick: () =>
        setFilterPatch({
          status: effectiveFilters.status === "live" ? null : "live",
        }),
    },
    {
      id: "upcoming",
      label: "Upcoming",
      count: overview.kpis.upcoming_count,
      active: effectiveFilters.status === "pending",
      onClick: () =>
        setFilterPatch({
          status: effectiveFilters.status === "pending" ? null : "pending",
        }),
    },
    {
      id: "with_logs",
      label: "With logs",
      count: overview.kpis.with_logs_count,
      active: effectiveFilters.has_logs === true,
      onClick: () =>
        setFilterPatch({ has_logs: effectiveFilters.has_logs === true ? null : true }),
    },
  ];

  return (
    <TooltipProvider>
      <div className={styles.surface}>
        <Hero overview={overview} />

        {initialError ? <div className={styles.notice}>{initialError}</div> : null}

        <section aria-label="Encounter views">
          <div className={styles.views}>
            <span className={styles.viewsLabel}>
              <Bookmark className="h-3 w-3" /> Views
            </span>
            {BUILT_IN_VIEWS.map((view) => (
              <button
                key={view.id}
                type="button"
                className={cn(styles.viewTab, activeView === view.id && styles.viewTabActive)}
                onClick={() => {
                  setPage(1);
                  const next = applyBuiltInView(view.id, effectiveFilters);
                  setSearchValue(next.query);
                  setFilters(next);
                }}
              >
                {view.showPin ? (
                  <Pin className={cn("h-3 w-3", styles.viewPin)} fill="currentColor" />
                ) : view.swatch ? (
                  <span
                    className={styles.viewSwatch}
                    style={{ background: VIEW_SWATCH_HSL[view.swatch] }}
                  />
                ) : null}
                <span>{view.label}</span>
                <span className={styles.viewCount}>{countLabel(overview.preset_counts[view.id])}</span>
              </button>
            ))}
            {savedViewsQuery.data?.map((view) => (
              <div key={view.id} className={styles.savedView}>
                <button
                  type="button"
                  className={cn(styles.viewTab, styles.savedViewMain)}
                  onClick={() => {
                    const next = toSavedFilterState(view);
                    setSearchValue(next.query);
                    setPage(1);
                    setFilters(next);
                  }}
                >
                  <Bookmark className="h-3 w-3" />
                  <span>{view.name}</span>
                </button>
                <button
                  type="button"
                  className={styles.savedViewDelete}
                  aria-label={`Delete saved view ${view.name}`}
                  disabled={deleteViewMutation.isPending}
                  onClick={() => {
                    if (!window.confirm(`Delete saved view "${view.name}"?`)) return;
                    deleteViewMutation.mutate({ id: view.id });
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
            <span className={styles.viewsSpacer} />
            <button
              type="button"
              className={styles.viewSave}
              onClick={handleSaveCurrentView}
              disabled={saveViewMutation.isPending}
            >
              {saveViewMutation.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              <span>Save current view</span>
            </button>
          </div>
        </section>

        <section aria-label="Encounter filters">
          <div className={styles.filters}>
            {quickFilters.map((chip) => (
              <button
                key={chip.id}
                type="button"
                className={cn(styles.filterChip, chip.active && styles.filterChipActive)}
                onClick={chip.onClick}
              >
                <span>{chip.label}</span>
                <span className={styles.filterChipCount}>{countLabel(chip.count)}</span>
              </button>
            ))}
            <span className={styles.filterDivider} />
            <FilterSelect
              label="Tournament"
              value={filters.tournament_id == null ? "all" : String(filters.tournament_id)}
              onValueChange={(value) =>
                setFilterPatch({ tournament_id: value === "all" ? null : Number(value) })
              }
              items={[
                ["all", "Tournament: Any"] as [string, string],
                ...(tournamentsLookupQuery.data ?? []).map(
                  (item) => [String(item.id), `Tournament: ${item.name}`] as [string, string],
                ),
              ]}
            />
            <FilterSelect
              label="Best-of"
              value={filters.best_of == null ? "all" : String(filters.best_of)}
              onValueChange={(value) =>
                setFilterPatch({ best_of: value === "all" ? null : Number(value) })
              }
              items={[
                ["all", "Best-of: Any"],
                ["3", "Best-of: 3"],
                ["5", "Best-of: 5"],
                ["7", "Best-of: 7"],
              ]}
            />
            <FilterSelect
              label="Closeness"
              value={filters.closeness_min == null ? "all" : String(filters.closeness_min)}
              onValueChange={(value) =>
                setFilterPatch({ closeness_min: value === "all" ? null : Number(value) })
              }
              items={[
                ["all", "Closeness: Any"],
                ["0.4", "Closeness ≥ 40%"],
                ["0.6", "Closeness ≥ 60%"],
                ["0.8", "Closeness ≥ 80%"],
              ]}
            />
            <FilterSelect
              label="Status"
              value={filters.status ?? "all"}
              onValueChange={(value) => setFilterPatch({ status: value === "all" ? null : value })}
              items={[
                ["all", "Status: All"],
                ["open", "Status: Open"],
                ["pending", "Status: Pending"],
                ["completed", "Status: Final"],
              ]}
            />
            <div className={styles.filterSearch}>
              <Search className={styles.filterSearchIcon} size={14} />
              <input
                value={searchValue}
                onChange={(event) => {
                  setPage(1);
                  setSearchValue(event.target.value);
                }}
                placeholder="Search by team, player, or matchup…"
              />
            </div>
            <FilterSelect
              label="Sort"
              value={filters.sort}
              onValueChange={(value) =>
                setFilterPatch({ sort: value as EncounterFilterState["sort"] })
              }
              items={[
                ["date", `Sort: Date`],
                ["closeness", `Sort: Closeness`],
                ["upcoming", `Sort: Upcoming`],
              ]}
              triggerLabel={`Sort: ${sortLabel}`}
              className={styles.filterSelectSort}
            />
          </div>
        </section>

        <section aria-label="Insights">
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Insights</h2>
            <span className={styles.sectionMeta}>
              Past 30 days · {countLabel(overview.pulse.completed_series_count)} series
            </span>
          </div>
          <div className={styles.grid3}>
            <div className={styles.card}>
              <div className={styles.cardHead}>
                <div>
                  <div className={styles.cardTitle}>Closeness distribution</div>
                  <div className={styles.cardSub}>Series binned by how competitive they were</div>
                </div>
                <span className={styles.pill}>
                  Avg{" "}
                  <span className={cn(styles.mono, styles.pillAccent)}>
                    {formatPercent(overview.kpis.avg_closeness)}
                  </span>
                </span>
              </div>
              <div className={styles.cardBody}>
                <div className={styles.hist}>
                  {overview.closeness_histogram.map((bucket) => (
                    <div
                      key={bucket.label}
                      className={styles.histBar}
                      style={{ height: `${Math.max(6, (bucket.count / maxHistogram) * 100)}%` }}
                      title={`${bucket.label}: ${bucket.count}`}
                    >
                      <span className={styles.histBarValue}>{bucket.count}</span>
                    </div>
                  ))}
                </div>
                <div className={styles.histAxis}>
                  <span>0%</span>
                  <span>20%</span>
                  <span>40%</span>
                  <span>60%</span>
                  <span>80%</span>
                  <span>100%</span>
                </div>
              </div>
            </div>

            <div className={styles.card}>
              <div className={styles.cardHead}>
                <div>
                  <div className={styles.cardTitle}>Score distribution</div>
                  <div className={styles.cardSub}>Final series scores · Bo3 / Bo5</div>
                </div>
                <span className={styles.pill}>
                  Max{" "}
                  <span className={cn(styles.mono, styles.pillAccent)}>{countLabel(heatmap.max)}</span>
                </span>
              </div>
              <div className={styles.cardBody}>
                <div className={styles.scoreGrid}>
                  <div />
                  {heatmap.cols.map((col) => (
                    <div key={`col-${col}`} className={styles.scoreHeader}>
                      {col}
                    </div>
                  ))}
                  {heatmap.rows.map((row) => (
                    <RowCells
                      key={`row-${row}`}
                      row={row}
                      cols={heatmap.cols}
                      matrix={heatmap.matrix}
                      max={heatmap.max}
                    />
                  ))}
                </div>
                <div className={styles.scoreLegend}>
                  <span>fewer</span>
                  <span className={styles.scoreLegendGrad} />
                  <span>more</span>
                </div>
              </div>
            </div>

            <div className={styles.card}>
              <div className={styles.cardHead}>
                <div>
                  <div className={styles.cardTitle}>By stage</div>
                  <div className={styles.cardSub}>Where series happen</div>
                </div>
              </div>
              <div className={styles.cardBody}>
                <div className={styles.donutRow}>
                  <div className={styles.donut}>
                    <svg width="140" height="140" viewBox="0 0 140 140">
                      <circle
                        cx="70"
                        cy="70"
                        r="54"
                        fill="none"
                        stroke="hsl(215 20% 12%)"
                        strokeWidth="18"
                      />
                      {stageDonut.segments.map((segment) => (
                        <circle
                          key={segment.name}
                          cx="70"
                          cy="70"
                          r="54"
                          fill="none"
                          stroke={segment.color}
                          strokeWidth="18"
                          strokeDasharray={segment.dashArray}
                          strokeDashoffset={segment.dashOffset}
                          transform="rotate(-90 70 70)"
                          strokeLinecap="butt"
                        />
                      ))}
                    </svg>
                    <div className={styles.donutCenter}>
                      <span className={styles.donutValue}>{countLabel(stageDonut.total)}</span>
                      <span className={styles.donutLabel}>Series</span>
                    </div>
                  </div>
                  <div className={styles.donutLegend}>
                    {stageDonut.segments.length ? (
                      stageDonut.segments.map((segment) => (
                        <div key={segment.name} className={styles.legendRow}>
                          <span
                            className={styles.legendSwatch}
                            style={{ background: segment.color }}
                          />
                          <span className={styles.legendName}>{segment.name}</span>
                          <span className={styles.legendValue}>
                            {countLabel(segment.count)} · {segment.pct}%
                          </span>
                        </div>
                      ))
                    ) : (
                      <span className={styles.dim}>No stage data yet.</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section aria-label="Featured series">
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Featured series</h2>
            <span className={styles.sectionMeta}>Auto-curated · Current filter scope</span>
          </div>
          <div className={styles.grid2}>
            <FeaturedPanel
              title="Closest fights"
              subtitle="Highest closeness reports"
              encounters={overview.featured.closest}
              variant="closest"
            />
            <FeaturedPanel
              title="Happening now"
              subtitle="Live & upcoming series"
              encounters={liveOrUpcoming}
              variant="live"
            />
          </div>
        </section>

        <section aria-label="All encounters">
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>All encounters</h2>
            <span className={styles.sectionMeta}>
              Page {page} of {totalPages} · sorted by {sortLabel.toLowerCase()}
            </span>
          </div>
          <div className={styles.gridTable}>
            <div className={styles.card}>
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Matchup</th>
                      <th>Tournament</th>
                      <th>Stage</th>
                      <th>Round</th>
                      <th className={styles.scoreAlign}>Score</th>
                      <th>Maps</th>
                      <th>Closeness</th>
                      <th>Media</th>
                      <th>Status</th>
                      <th>Played</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listQuery.isFetching && !rows.length ? (
                      <tr>
                        <td colSpan={10} className={styles.empty}>
                          Loading encounters…
                        </td>
                      </tr>
                    ) : rows.length ? (
                      rows.map((encounter) => (
                        <EncounterRow key={encounter.id} encounter={encounter} />
                      ))
                    ) : (
                      <tr>
                        <td colSpan={10} className={styles.empty}>
                          No encounters found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className={styles.pagination}>
                <span className={styles.pageInfo}>
                  Showing {showingStart} – {showingEnd} of {countLabel(encounters.total)} series
                </span>
                <div className={styles.pageControls}>
                  <button
                    className={styles.pageBtn}
                    type="button"
                    disabled={page === 1}
                    onClick={() => setPage(Math.max(1, page - 1))}
                  >
                    ‹ Prev
                  </button>
                  {pageList.map((entry, index) =>
                    entry === "ellipsis" ? (
                      <span
                        key={`ellipsis-${index}`}
                        className={cn(styles.pageBtn, styles.pageBtnEllipsis)}
                      >
                        …
                      </span>
                    ) : (
                      <button
                        key={entry}
                        type="button"
                        className={cn(
                          styles.pageBtn,
                          entry === page && styles.pageBtnActive,
                        )}
                        disabled={entry === page}
                        onClick={() => setPage(entry)}
                      >
                        {entry}
                      </button>
                    ),
                  )}
                  <button
                    className={styles.pageBtn}
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                  >
                    Next ›
                  </button>
                </div>
              </div>
            </div>

            <aside className={styles.rail}>
              <div className={styles.card}>
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>This week’s pulse</div>
                </div>
                <div className={styles.insightList}>
                  <Insight
                    label="Avg series length"
                    value={formatDuration(overview.pulse.avg_series_seconds)}
                    meta={`across ${countLabel(overview.pulse.completed_series_count)} completed series`}
                  />
                  <Insight
                    label="Sweep rate"
                    value={`${overview.pulse.sweep_rate}%`}
                    meta={`${countLabel(overview.pulse.sweep_count)} sweeps · ${countLabel(overview.pulse.went_distance_count)} went distance`}
                  />
                  <Insight
                    label="Reverse-sweep rate"
                    value={`${overview.pulse.reverse_sweep_rate}%`}
                    meta="series that came back from match point"
                  />
                  <Insight
                    label="Most-decisive map"
                    value={overview.pulse.most_decisive_map ?? "—"}
                    valueClassName={styles.insightValueSmall}
                  />
                </div>
              </div>

              <div className={styles.card}>
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>Hot maps</div>
                  <span className={styles.cardSub}>Current filter scope</span>
                </div>
                <div>
                  {overview.hot_maps.length ? (
                    overview.hot_maps.map((map) => (
                      <div key={map.name} className={styles.mapRow}>
                        <span className={styles.mapName}>{map.name}</span>
                        <div className={styles.mapTrack}>
                          <div
                            className={styles.mapFill}
                            style={{ width: `${(map.count / maxMapCount) * 100}%` }}
                          />
                        </div>
                        <span className={styles.mapNum}>{countLabel(map.count)}</span>
                      </div>
                    ))
                  ) : (
                    <div className={styles.empty}>No map data yet.</div>
                  )}
                </div>
              </div>

              <div className={styles.card}>
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>Side balance</div>
                  <span className={styles.cardSub}>Home vs. away winner</span>
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.balance}>
                    <div
                      className={styles.balanceHome}
                      style={{ width: `${overview.side_balance.home_win_pct}%` }}
                    >
                      {overview.side_balance.home_win_pct}%
                    </div>
                    <div
                      className={styles.balanceAway}
                      style={{ width: `${overview.side_balance.away_win_pct}%` }}
                    >
                      {overview.side_balance.away_win_pct}%
                    </div>
                  </div>
                  <div className={styles.balanceLegend}>
                    <span>
                      <span className={styles.balanceLegendHome}>● </span>Home wins
                    </span>
                    <span>
                      Away wins <span className={styles.dim}>●</span>
                    </span>
                  </div>
                </div>
              </div>
            </aside>
          </div>
        </section>
      </div>
    </TooltipProvider>
  );
}

function Hero({ overview }: { overview: EncounterOverview }) {
  return (
    <section className={styles.hero}>
      <div className={styles.hex} />
      <div className={styles.glow1} />
      <div className={styles.glow2} />
      <div className={styles.heroGrid}>
        <div>
          <p className={styles.crumb}>All tournaments · Encounters</p>
          <h1 className={styles.title}>
            Every fight, <em className={styles.titleAccent}>quantified</em>
          </h1>
          <p className={styles.subtitle}>
            All series across all tournaments and leagues on the platform — sliceable by stage,
            tournament, closeness and logs availability.
          </p>
        </div>
        <div className={styles.heroStats}>
          <HeroStat
            label="Total encounters"
            value={countLabel(overview.kpis.total_encounters)}
            foot={
              overview.kpis.recent_count ? (
                <>
                  <span className={styles.delta}>▲ {countLabel(overview.kpis.recent_count)}</span>{" "}
                  last 7 days
                </>
              ) : (
                "All time"
              )
            }
          />
          <HeroStat
            label="With game logs"
            value={
              <>
                {overview.kpis.with_logs_pct}
                <em>%</em>
              </>
            }
            foot={`${countLabel(overview.kpis.with_logs_count)} of ${countLabel(overview.kpis.total_encounters)} series`}
          />
          <HeroStat
            label="Avg closeness"
            value={
              overview.kpis.avg_closeness != null ? (
                <>
                  {formatPercent(overview.kpis.avg_closeness, "—").replace("%", "")}
                  <em>%</em>
                </>
              ) : (
                "—"
              )
            }
            foot="Across reported series"
          />
          <HeroStat
            label="Live now"
            value={countLabel(overview.kpis.live_now_count)}
            foot={`${countLabel(overview.kpis.upcoming_count)} upcoming`}
          />
        </div>
      </div>
    </section>
  );
}

function HeroStat({
  label,
  value,
  foot,
}: {
  label: string;
  value: React.ReactNode;
  foot: React.ReactNode;
}) {
  return (
    <div className={styles.heroStat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statFoot}>{foot}</span>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onValueChange,
  items,
  triggerLabel,
  className,
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  items: [string, string][];
  triggerLabel?: string;
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger className={cn(styles.filterSelectTrigger, className)} aria-label={label}>
        {triggerLabel ? <span>{triggerLabel}</span> : <SelectValue />}
      </SelectTrigger>
      <SelectContent>
        {items.map(([itemValue, itemLabel]) => (
          <SelectItem key={itemValue} value={itemValue}>
            {itemLabel}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function RowCells({
  row,
  cols,
  matrix,
  max,
}: {
  row: number;
  cols: number[];
  matrix: Record<string, number>;
  max: number;
}) {
  return (
    <>
      <div className={styles.scoreSide}>{row}</div>
      {cols.map((col) => {
        const count = matrix[`${row}-${col}`] ?? 0;
        const alpha = max > 0 ? Math.max(0.05, count / max) : 0;
        return (
          <div
            key={`${row}-${col}`}
            className={cn(styles.scoreCellHeat, count === 0 && styles.scoreCellEmpty)}
            style={{ "--alpha": String(alpha) } as CSSProperties}
          >
            {count > 0 ? countLabel(count) : "—"}
          </div>
        );
      })}
    </>
  );
}

function FeaturedPanel({
  title,
  subtitle,
  encounters,
  variant,
}: {
  title: string;
  subtitle: string;
  encounters: Encounter[];
  variant: "closest" | "live";
}) {
  const router = useRouter();
  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <div>
          <div className={styles.cardTitle}>{title}</div>
          <div className={styles.cardSub}>{subtitle}</div>
        </div>
      </div>
      <div>
        {encounters.length ? (
          encounters.slice(0, 4).map((encounter) => {
            const homeName = encounter.home_team?.name ?? "TBD";
            const awayName = encounter.away_team?.name ?? "TBD";
            const winner = getWinnerSide(encounter);
            const state = getEncounterStateLabel(encounter);
            const isLive = variant === "live" && state === "Live";
            const isUpcoming = variant === "live" && state === "Upcoming";
            const closenessPct = encounter.closeness != null ? Math.round(encounter.closeness * 100) : null;
            return (
              <div
                key={encounter.id}
                className={styles.feat}
                onClick={() => router.push(`/encounters/${encounter.id}`)}
                role="link"
              >
                <div>
                  <div className={styles.matchup}>
                    {isLive ? <span className={cn(styles.statusDot, styles.statusLive)}>Live</span> : null}
                    {isUpcoming ? (
                      <span className={cn(styles.statusDot, styles.statusUpcoming)}>
                        {state === "Upcoming" ? "Soon" : state}
                      </span>
                    ) : null}
                    <TeamChip name={homeName} />
                    <span className={styles.vs}>VS</span>
                    <TeamChip name={awayName} />
                  </div>
                  <div className={styles.featMeta}>
                    {[
                      tournamentLabel(encounter),
                      stageLabel(encounter),
                      `Round ${encounter.round}`,
                      `${encounter.matches?.length ?? 0} maps`,
                      formatDuration(getSeriesDuration(encounter)),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
                <div className={styles.featSide}>
                  {variant === "live" && isUpcoming ? (
                    <span className={styles.featTime}>
                      {formatCompactDate(encounter.scheduled_at ?? null)}
                    </span>
                  ) : (
                    <span className={styles.featScore}>
                      <span className={winner === "home" ? styles.featScoreWinner : styles.featScoreLoser}>
                        {encounter.score.home}
                      </span>
                      <span className={styles.scoreSep}>–</span>
                      <span className={winner === "away" ? styles.featScoreWinner : styles.featScoreLoser}>
                        {encounter.score.away}
                      </span>
                    </span>
                  )}
                  {variant === "closest" && closenessPct != null ? (
                    <span className={styles.badgeCloseness}>⚡ {closenessPct}%</span>
                  ) : null}
                  {isLive ? <span className={styles.featTime}>Live</span> : null}
                </div>
              </div>
            );
          })
        ) : (
          <div className={styles.empty}>No featured series in this slice.</div>
        )}
      </div>
    </div>
  );
}

function TeamChip({ name }: { name: string }) {
  const color = getTeamColor(name);
  return (
    <span className={styles.teamChip}>
      <span className={cn(styles.tg, TEAM_COLOR_CLASS[color])}>{getTeamInitials(name)}</span>
      <span>{name}</span>
    </span>
  );
}

function EncounterRow({ encounter }: { encounter: Encounter }) {
  const router = useRouter();
  const winner = getWinnerSide(encounter);
  const stateLabel = getEncounterStateLabel(encounter);
  const homeName = encounter.home_team?.name ?? "TBD";
  const awayName = encounter.away_team?.name ?? "TBD";
  const sortedMatches = [...(encounter.matches ?? [])].sort((a, b) => a.id - b.id);
  const stageName = stageLabel(encounter);
  const stageBucket = getStageBucket(stageName);
  const closenessPct = encounter.closeness != null ? Math.round(encounter.closeness * 100) : null;
  const homeColor = getTeamColor(homeName);
  const awayColor = getTeamColor(awayName);
  const isUpset =
    encounter.status === "completed" &&
    closenessPct != null &&
    closenessPct >= 80 &&
    Math.abs(encounter.score.home - encounter.score.away) === 1;

  const statusVariant =
    stateLabel === "Live"
      ? styles.statusLive
      : stateLabel === "Upcoming"
        ? styles.statusUpcoming
        : stateLabel === "Pending"
          ? styles.statusPending
          : stateLabel === "Open"
            ? styles.statusOpen
            : styles.statusDone;

  return (
    <tr onClick={() => router.push(`/encounters/${encounter.id}`)}>
      <td>
        <div className={styles.matchupCell}>
          <div className={styles.teamStack}>
            <div className={styles.teamLine}>
              <span className={cn(styles.tg, TEAM_COLOR_CLASS[homeColor])}>
                {getTeamInitials(homeName)}
              </span>
              <span className={cn(styles.teamName, winner === "away" && styles.loser)}>
                {homeName}
              </span>
            </div>
            <div className={styles.teamLine}>
              <span className={cn(styles.tg, TEAM_COLOR_CLASS[awayColor])}>
                {getTeamInitials(awayName)}
              </span>
              <span className={cn(styles.teamName, winner === "home" && styles.loser)}>
                {awayName}
              </span>
            </div>
          </div>
        </div>
      </td>
      <td className={styles.dim}>{tournamentLabel(encounter)}</td>
      <td>
        <span className={cn(styles.stagePill, STAGE_PILL_CLASS[stageBucket])}>{stageName}</span>
      </td>
      <td className={cn(styles.dim, styles.mono)}>R{encounter.round}</td>
      <td className={cn(styles.mono, styles.scoreAlign)}>
        <span className={cn(styles.scoreCell, winner === "home" ? styles.scoreCellWinner : styles.scoreCellLoser)}>
          {encounter.score.home}
        </span>
        <span className={styles.scoreSep}>–</span>
        <span className={cn(styles.scoreCell, winner === "away" ? styles.scoreCellWinner : styles.scoreCellLoser)}>
          {encounter.score.away}
        </span>
      </td>
      <td>
        <div className={styles.maps}>
          {sortedMatches.length ? (
            sortedMatches.map((match) => {
              const homeWon = match.score.home > match.score.away;
              return (
                <span
                  key={match.id}
                  className={cn(styles.pip, homeWon ? styles.pipWin : styles.pipLoss)}
                />
              );
            })
          ) : (
            <span className={styles.dim}>—</span>
          )}
        </div>
      </td>
      <td>
        <div className={styles.closeness}>
          <div className={styles.closenessTrack}>
            <div
              className={styles.closenessFill}
              style={{ width: `${closenessPct ?? 0}%` }}
            />
          </div>
          <span className={cn(styles.closenessNum)}>
            {closenessPct == null ? "—" : `${closenessPct}%`}
          </span>
        </div>
      </td>
      <td>
        <MediaIcons hasLogs={encounter.has_logs} />
      </td>
      <td>
        <span className={cn(styles.statusDot, statusVariant)}>
          {isUpset ? "Upset" : stateLabel}
        </span>
      </td>
      <td className={cn(styles.dim, styles.mono)}>{formatCompactDate(getPlayedAt(encounter))}</td>
    </tr>
  );
}

const MEDIA_ICON_VARIANT: Record<MediaSlotKey, string> = {
  logs: styles.mediaIconLogs,
  vod: styles.mediaIconVod,
  cast: styles.mediaIconCast,
};

function MediaIcons({ hasLogs }: { hasLogs: boolean }) {
  return (
    <div className={styles.media}>
      {getMediaSlots(hasLogs).map((slot) => {
        const enabledVariant = slot.enabled ? MEDIA_ICON_VARIANT[slot.key] : null;
        return (
          <Tooltip key={slot.key}>
            <TooltipTrigger asChild>
              <span
                className={cn(
                  styles.mediaIcon,
                  enabledVariant,
                  !slot.enabled && styles.mediaIconDisabled,
                )}
              >
                {slot.key === "logs" ? (
                  <FileText className="h-3 w-3" />
                ) : slot.key === "vod" ? (
                  <Play className="h-3 w-3" fill="currentColor" />
                ) : (
                  <Tv className="h-3 w-3" />
                )}
                {slot.key === "cast" && slot.enabled ? <span className={styles.liveDot} /> : null}
              </span>
            </TooltipTrigger>
            <TooltipContent>{slot.label}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

function Insight({
  label,
  value,
  meta,
  valueClassName,
}: {
  label: string;
  value: string;
  meta?: string;
  valueClassName?: string;
}) {
  return (
    <div className={styles.insightRow}>
      <span className={styles.insightLabel}>{label}</span>
      <span className={cn(styles.insightValue, valueClassName)}>{value}</span>
      {meta ? <span className={styles.insightMeta}>{meta}</span> : null}
    </div>
  );
}
