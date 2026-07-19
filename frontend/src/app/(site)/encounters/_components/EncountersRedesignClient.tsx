"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, FileText, Loader2, Pin, Play, Save, Search, Trash2, Tv } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useDebounce } from "use-debounce";
import type { PaginatedResponse } from "@/types/pagination.types";
import type {
  Encounter,
  EncounterOverview,
  EncounterSavedView,
  EncounterScoreHeatmapCell,
  EncounterStageSplit
} from "@/types/encounter.types";
import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { notify } from "@/lib/notify";
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
  type MediaSlot,
  type MediaSlotKey,
  type TeamColor
} from "./encounters-redesign.helpers";
import styles from "./EncountersRedesign.module.css";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// module-level helpers can accept `t` straight through (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations<never>>;

// Maps the raw English state SENTINEL from `getEncounterStateLabel` to its
// translation key. The sentinel itself is preserved for control flow; only the
// rendered label is translated.
const STATE_LABEL_KEYS = {
  Live: "encounters.state.live",
  Upcoming: "encounters.state.upcoming",
  Final: "encounters.state.final",
  Pending: "encounters.state.pending",
  Open: "encounters.state.open"
} as const;

type StateLabelKey = (typeof STATE_LABEL_KEYS)[keyof typeof STATE_LABEL_KEYS];

function stateLabelKey(sentinel: string): StateLabelKey {
  return STATE_LABEL_KEYS[sentinel as keyof typeof STATE_LABEL_KEYS] ?? "encounters.state.open";
}

type MediaTooltipKey =
  | "encounters.media.logsAvailable"
  | "encounters.media.noLogs"
  | "encounters.media.comingTwitch";

function mediaTooltipKey(slot: MediaSlot): MediaTooltipKey {
  if (slot.key === "logs") {
    return slot.enabled ? "encounters.media.logsAvailable" : "encounters.media.noLogs";
  }
  return "encounters.media.comingTwitch";
}

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
  blue: styles.tgBlue
};

const STAGE_PILL_CLASS: Record<string, string> = {
  playoffs: styles.stagePillPlayoffs,
  group: styles.stagePillGroup,
  finals: styles.stagePillFinals
};

const VIEW_SWATCH_HSL: Record<TeamColor, string> = {
  teal: "var(--aqt-teal)",
  amber: "var(--aqt-amber)",
  rose: "var(--aqt-rose)",
  violet: "var(--aqt-violet)",
  blue: "var(--aqt-blue)"
};

const STAGE_DONUT_COLORS = [
  "hsl(210 80% 60%)",
  "hsl(38 95% 55%)",
  "hsl(340 75% 58%)",
  "hsl(172 70% 49%)",
  "hsl(270 70% 62%)"
];

function countLabel(value?: number): string {
  return typeof value === "number" ? value.toLocaleString("en") : "-";
}

function tournamentLabel(encounter: Encounter, t: Translate): string {
  if (!encounter.tournament) return t("common.tournament");
  return encounter.tournament.is_league
    ? encounter.tournament.name
    : t("encounters.tournamentNumber", { number: encounter.tournament.number });
}

function stageLabel(encounter: Encounter, t: Translate): string {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? t("encounters.unassigned");
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
    scope: view.filters.scope === "my_team" ? "my_team" : "all"
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
      dashOffset: -offset
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
  initialError
}: EncountersRedesignClientProps) {
  const t = useTranslations();
  const pathname = usePathname();
  const queryClient = useQueryClient();
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
    [debouncedSearch, filters]
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
            "matches.map"
          ]
        }
      ),
    initialData:
      page === initialPage && JSON.stringify(effectiveFilters) === JSON.stringify(initialFilters)
        ? initialData
        : undefined,
    placeholderData: (previous) => previous
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
    retry: 1
  });

  const savedViewsQuery = useQuery({
    queryKey: ["encounters-saved-views", currentWorkspaceId, userKey],
    queryFn: () => encounterService.getSavedViews(currentWorkspaceId),
    enabled: Boolean(user && currentWorkspaceId != null),
    placeholderData: (previous) => previous,
    retry: false,
    staleTime: 60_000
  });

  const tournamentsLookupQuery = useQuery({
    queryKey: ["encounters-tournaments-lookup", currentWorkspaceId],
    queryFn: () => tournamentService.lookup(currentWorkspaceId),
    staleTime: 5 * 60_000,
    retry: 1
  });

  const saveViewMutation = useMutation({
    mutationFn: ({ name }: { name: string }) =>
      encounterService.saveView(name, effectiveFilters, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounters-saved-views", currentWorkspaceId, userKey]
      });
      notify.success(t("encounters.savedView.saved"));
    }
  });

  const deleteViewMutation = useMutation({
    mutationFn: ({ id }: { id: number }) => encounterService.deleteView(id, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounters-saved-views", currentWorkspaceId, userKey]
      });
      notify.success(t("encounters.savedView.deleted"));
    }
  });

  const overview = overviewQuery.data ?? initialOverview;
  const encounters = listQuery.data ?? initialData;
  const rows = encounters.results ?? [];
  const totalPages = Math.max(1, Math.ceil((encounters.total ?? 0) / ENCOUNTERS_PAGE_SIZE));
  const activeView = selectedViewId(effectiveFilters);
  const maxHistogram = Math.max(1, ...overview.closeness_histogram.map((bucket) => bucket.count));
  const heatmap = useMemo(
    () => buildHeatmapMatrix(overview.score_heatmap),
    [overview.score_heatmap]
  );
  const stageDonut = useMemo(() => donutSegments(overview.stage_split), [overview.stage_split]);
  const maxMapCount = Math.max(1, ...overview.hot_maps.map((map) => map.count));
  const liveOrUpcoming = overview.featured.live.length
    ? overview.featured.live
    : overview.featured.upcoming;
  const sortLabel = t(`encounters.sort.${effectiveFilters.sort}`);

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
    const name = window.prompt(
      t("encounters.savedView.promptName"),
      t("encounters.savedView.promptDefault")
    );
    if (!name?.trim()) return;
    saveViewMutation.mutate({ name: name.trim() });
  };

  const pageList = buildPageList(page, totalPages);
  const showingStart = rows.length ? (page - 1) * ENCOUNTERS_PAGE_SIZE + 1 : 0;
  const showingEnd = Math.min(page * ENCOUNTERS_PAGE_SIZE, encounters.total);

  const quickFilters: Array<{
    id: string;
    label: string;
    count: number;
    active: boolean;
    onClick: () => void;
  }> = [
    {
      id: "all",
      label: t("common.all"),
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
          scope: "all"
        });
      }
    },
    {
      id: "live",
      label: t("common.live"),
      count: overview.kpis.live_now_count,
      active: effectiveFilters.status === "live",
      onClick: () =>
        setFilterPatch({
          status: effectiveFilters.status === "live" ? null : "live"
        })
    },
    {
      id: "upcoming",
      label: t("encounters.state.upcoming"),
      count: overview.kpis.upcoming_count,
      active: effectiveFilters.status === "pending",
      onClick: () =>
        setFilterPatch({
          status: effectiveFilters.status === "pending" ? null : "pending"
        })
    },
    {
      id: "with_logs",
      label: t("encounters.filter.withLogs"),
      count: overview.kpis.with_logs_count,
      active: effectiveFilters.has_logs === true,
      onClick: () => setFilterPatch({ has_logs: effectiveFilters.has_logs === true ? null : true })
    }
  ];

  return (
    <TooltipProvider>
      <div className={styles.surface}>
        <Hero overview={overview} />

        {initialError ? <div className={styles.notice}>{initialError}</div> : null}

        <section aria-label={t("encounters.aria.views")}>
          <div className={styles.views}>
            <span className={styles.viewsLabel}>
              <Bookmark className="h-3 w-3" /> {t("encounters.views")}
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
                <span>{t(view.labelKey)}</span>
                <span className={styles.viewCount}>
                  {countLabel(overview.preset_counts[view.id])}
                </span>
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
                  aria-label={t("encounters.savedView.deleteAria", { name: view.name })}
                  disabled={deleteViewMutation.isPending}
                  onClick={() => {
                    if (!window.confirm(t("encounters.savedView.confirmDelete", { name: view.name })))
                      return;
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
              <span>{t("encounters.savedView.saveCurrent")}</span>
            </button>
          </div>
        </section>

        <section aria-label={t("encounters.aria.filters")}>
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
              label={t("common.tournament")}
              value={filters.tournament_id == null ? "all" : String(filters.tournament_id)}
              onValueChange={(value) =>
                setFilterPatch({ tournament_id: value === "all" ? null : Number(value) })
              }
              items={[
                ["all", t("encounters.filter.tournamentAny")] as [string, string],
                ...(tournamentsLookupQuery.data ?? []).map(
                  (item) =>
                    [
                      String(item.id),
                      t("encounters.filter.tournamentNamed", { name: item.name })
                    ] as [string, string]
                )
              ]}
            />
            <FilterSelect
              label={t("encounters.filter.bestOf")}
              value={filters.best_of == null ? "all" : String(filters.best_of)}
              onValueChange={(value) =>
                setFilterPatch({ best_of: value === "all" ? null : Number(value) })
              }
              items={[
                ["all", t("encounters.filter.bestOfAny")],
                ["3", t("encounters.filter.bestOfValue", { count: "3" })],
                ["5", t("encounters.filter.bestOfValue", { count: "5" })],
                ["7", t("encounters.filter.bestOfValue", { count: "7" })]
              ]}
            />
            <FilterSelect
              label={t("encounters.col.closeness")}
              value={filters.closeness_min == null ? "all" : String(filters.closeness_min)}
              onValueChange={(value) =>
                setFilterPatch({ closeness_min: value === "all" ? null : Number(value) })
              }
              items={[
                ["all", t("encounters.filter.closenessAny")],
                ["0.4", t("encounters.filter.closenessMin", { pct: "40" })],
                ["0.6", t("encounters.filter.closenessMin", { pct: "60" })],
                ["0.8", t("encounters.filter.closenessMin", { pct: "80" })]
              ]}
            />
            <FilterSelect
              label={t("common.status")}
              value={filters.status ?? "all"}
              onValueChange={(value) => setFilterPatch({ status: value === "all" ? null : value })}
              items={[
                ["all", t("encounters.filter.statusAll")],
                ["open", t("encounters.filter.statusOpen")],
                ["pending", t("encounters.filter.statusPending")],
                ["completed", t("encounters.filter.statusFinal")]
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
                placeholder={t("encounters.searchPlaceholder")}
              />
            </div>
            <FilterSelect
              label={t("common.sortBy")}
              value={filters.sort}
              onValueChange={(value) =>
                setFilterPatch({ sort: value as EncounterFilterState["sort"] })
              }
              items={[
                ["date", t("encounters.filter.sortDate")],
                ["closeness", t("encounters.filter.sortCloseness")],
                ["upcoming", t("encounters.filter.sortUpcoming")]
              ]}
              triggerLabel={t("encounters.filter.sortTrigger", { label: sortLabel })}
              className={styles.filterSelectSort}
            />
          </div>
        </section>

        <section aria-label={t("encounters.insights.title")}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>{t("encounters.insights.title")}</h2>
            <span className={styles.sectionMeta}>
              {t("encounters.insights.meta", {
                count: overview.pulse.completed_series_count
              })}
            </span>
          </div>
          <div className={styles.grid3}>
            <div className={styles.card}>
              <div className={styles.cardHead}>
                <div>
                  <div className={styles.cardTitle}>{t("encounters.insights.closenessTitle")}</div>
                  <div className={styles.cardSub}>{t("encounters.insights.closenessSub")}</div>
                </div>
                <span className={styles.pill}>
                  {t("encounters.insights.avg")}{" "}
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
                  <div className={styles.cardTitle}>{t("encounters.insights.scoreTitle")}</div>
                  <div className={styles.cardSub}>{t("encounters.insights.scoreSub")}</div>
                </div>
                <span className={styles.pill}>
                  {t("encounters.insights.max")}{" "}
                  <span className={cn(styles.mono, styles.pillAccent)}>
                    {countLabel(heatmap.max)}
                  </span>
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
                  <span>{t("encounters.insights.fewer")}</span>
                  <span className={styles.scoreLegendGrad} />
                  <span>{t("encounters.insights.more")}</span>
                </div>
              </div>
            </div>

            <div className={styles.card}>
              <div className={styles.cardHead}>
                <div>
                  <div className={styles.cardTitle}>{t("encounters.insights.byStageTitle")}</div>
                  <div className={styles.cardSub}>{t("encounters.insights.byStageSub")}</div>
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
                      <span className={styles.donutLabel}>{t("encounters.insights.series")}</span>
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
                      <span className={styles.dim}>{t("encounters.insights.noStageData")}</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section aria-label={t("encounters.featured.title")}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>{t("encounters.featured.title")}</h2>
            <span className={styles.sectionMeta}>{t("encounters.featured.meta")}</span>
          </div>
          <div className={styles.grid2}>
            <FeaturedPanel
              title={t("encounters.featured.closestTitle")}
              subtitle={t("encounters.featured.closestSub")}
              encounters={overview.featured.closest}
              variant="closest"
            />
            <FeaturedPanel
              title={t("encounters.featured.liveTitle")}
              subtitle={t("encounters.featured.liveSub")}
              encounters={liveOrUpcoming}
              variant="live"
            />
          </div>
        </section>

        <section aria-label={t("encounters.list.title")}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>{t("encounters.list.title")}</h2>
            <span className={styles.sectionMeta}>
              {t("encounters.list.pageMeta", {
                page: String(page),
                total: String(totalPages),
                sort: effectiveFilters.sort
              })}
            </span>
          </div>
          <div className={styles.gridTable}>
            <div className={styles.card}>
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>{t("encounters.col.matchup")}</th>
                      <th>{t("common.tournament")}</th>
                      <th>{t("common.stage")}</th>
                      <th>{t("encounters.col.round")}</th>
                      <th className={styles.scoreAlign}>{t("encounters.col.score")}</th>
                      <th>{t("encounters.col.maps")}</th>
                      <th>{t("encounters.col.closeness")}</th>
                      <th>{t("encounters.col.media")}</th>
                      <th>{t("common.status")}</th>
                      <th>{t("encounters.col.played")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listQuery.isFetching && !rows.length ? (
                      <tr>
                        <td colSpan={10} className={styles.empty}>
                          {t("encounters.list.loading")}
                        </td>
                      </tr>
                    ) : rows.length ? (
                      rows.map((encounter) => (
                        <EncounterRow key={encounter.id} encounter={encounter} />
                      ))
                    ) : (
                      <tr>
                        <td colSpan={10} className={styles.empty}>
                          {t("encounters.list.empty")}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className={styles.pagination}>
                <span className={styles.pageInfo}>
                  {t("encounters.list.showing", {
                    start: String(showingStart),
                    end: String(showingEnd),
                    total: countLabel(encounters.total)
                  })}
                </span>
                <div className={styles.pageControls}>
                  <button
                    className={styles.pageBtn}
                    type="button"
                    disabled={page === 1}
                    onClick={() => setPage(Math.max(1, page - 1))}
                  >
                    ‹ {t("common.prev")}
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
                        className={cn(styles.pageBtn, entry === page && styles.pageBtnActive)}
                        disabled={entry === page}
                        onClick={() => setPage(entry)}
                      >
                        {entry}
                      </button>
                    )
                  )}
                  <button
                    className={styles.pageBtn}
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                  >
                    {t("common.next")} ›
                  </button>
                </div>
              </div>
            </div>

            <aside className={styles.rail}>
              <div className={styles.card}>
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>{t("encounters.pulse.title")}</div>
                </div>
                <div className={styles.insightList}>
                  <Insight
                    label={t("encounters.pulse.avgLength")}
                    value={formatDuration(overview.pulse.avg_series_seconds)}
                    meta={t("encounters.pulse.avgLengthMeta", {
                      count: countLabel(overview.pulse.completed_series_count)
                    })}
                  />
                  <Insight
                    label={t("encounters.pulse.sweepRate")}
                    value={`${overview.pulse.sweep_rate}%`}
                    meta={t("encounters.pulse.sweepMeta", {
                      sweeps: countLabel(overview.pulse.sweep_count),
                      distance: countLabel(overview.pulse.went_distance_count)
                    })}
                  />
                  <Insight
                    label={t("encounters.pulse.reverseSweepRate")}
                    value={`${overview.pulse.reverse_sweep_rate}%`}
                    meta={t("encounters.pulse.reverseSweepMeta")}
                  />
                  <Insight
                    label={t("encounters.pulse.mostDecisiveMap")}
                    value={overview.pulse.most_decisive_map ?? "—"}
                    valueClassName={styles.insightValueSmall}
                  />
                </div>
              </div>

              <div className={styles.card}>
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>{t("encounters.hotMaps.title")}</div>
                  <span className={styles.cardSub}>{t("encounters.hotMaps.sub")}</span>
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
                    <div className={styles.empty}>{t("encounters.hotMaps.empty")}</div>
                  )}
                </div>
              </div>

              <div className={styles.card}>
                <div className={styles.cardHead}>
                  <div className={styles.cardTitle}>{t("encounters.sideBalance.title")}</div>
                  <span className={styles.cardSub}>{t("encounters.sideBalance.sub")}</span>
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
                      <span className={styles.balanceLegendHome}>● </span>
                      {t("encounters.sideBalance.homeWins")}
                    </span>
                    <span>
                      {t("encounters.sideBalance.awayWins")} <span className={styles.dim}>●</span>
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
  const t = useTranslations();
  return (
    <PageHero
      eyebrow={<HeroCoord>{t("encounters.hero.eyebrow")}</HeroCoord>}
      title={t.rich("encounters.hero.title", {
        em: (chunks) => <em>{chunks}</em>
      })}
      lede={t("encounters.hero.lede")}
      aside={
        <div className={styles.heroStats}>
          <HeroStat
            label={t("encounters.hero.totalLabel")}
            value={countLabel(overview.kpis.total_encounters)}
            foot={
              overview.kpis.recent_count ? (
                <>
                  <span className={styles.delta}>▲ {countLabel(overview.kpis.recent_count)}</span>{" "}
                  {t("encounters.hero.last7Days")}
                </>
              ) : (
                t("encounters.hero.allTime")
              )
            }
          />
          <HeroStat
            label={t("encounters.hero.withLogsLabel")}
            value={
              <>
                {overview.kpis.with_logs_pct}
                <em>%</em>
              </>
            }
            foot={t("encounters.hero.ofSeries", {
              count: countLabel(overview.kpis.with_logs_count),
              total: countLabel(overview.kpis.total_encounters)
            })}
          />
          <HeroStat
            label={t("encounters.hero.avgClosenessLabel")}
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
            foot={t("encounters.hero.acrossReported")}
          />
          <HeroStat
            label={t("encounters.hero.liveNowLabel")}
            value={countLabel(overview.kpis.live_now_count)}
            foot={t("encounters.hero.upcomingCount", {
              count: countLabel(overview.kpis.upcoming_count)
            })}
          />
        </div>
      }
    />
  );
}

function HeroStat({
  label,
  value,
  foot
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
  className
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
  max
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
  variant
}: {
  title: string;
  subtitle: string;
  encounters: Encounter[];
  variant: "closest" | "live";
}) {
  const t = useTranslations();
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
            const homeName = encounter.home_team?.name ?? t("common.tbd");
            const awayName = encounter.away_team?.name ?? t("common.tbd");
            const winner = getWinnerSide(encounter);
            const state = getEncounterStateLabel(encounter);
            const isLive = variant === "live" && state === "Live";
            const isUpcoming = variant === "live" && state === "Upcoming";
            const closenessPct =
              encounter.closeness != null ? Math.round(encounter.closeness * 100) : null;
            return (
              <div
                key={encounter.id}
                className={styles.feat}
                onClick={() => router.push(`/encounters/${encounter.id}`)}
                role="link"
              >
                <div>
                  <div className={styles.matchup}>
                    {isLive ? (
                      <span className={cn(styles.statusDot, styles.statusLive)}>
                        {t("encounters.state.live")}
                      </span>
                    ) : null}
                    {isUpcoming ? (
                      <span className={cn(styles.statusDot, styles.statusUpcoming)}>
                        {state === "Upcoming"
                          ? t("encounters.state.soon")
                          : t(stateLabelKey(state))}
                      </span>
                    ) : null}
                    <TeamChip name={homeName} />
                    <span className={styles.vs}>{t("common.vs")}</span>
                    <TeamChip name={awayName} />
                  </div>
                  <div className={styles.featMeta}>
                    {[
                      tournamentLabel(encounter, t),
                      stageLabel(encounter, t),
                      t("encounters.roundNum", { round: encounter.round }),
                      t("encounters.mapsCount", { count: encounter.matches?.length ?? 0 }),
                      formatDuration(getSeriesDuration(encounter))
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
                      <span
                        className={
                          winner === "home" ? styles.featScoreWinner : styles.featScoreLoser
                        }
                      >
                        {encounter.score.home}
                      </span>
                      <span className={styles.scoreSep}>–</span>
                      <span
                        className={
                          winner === "away" ? styles.featScoreWinner : styles.featScoreLoser
                        }
                      >
                        {encounter.score.away}
                      </span>
                    </span>
                  )}
                  {variant === "closest" && closenessPct != null ? (
                    <span className={styles.badgeCloseness}>⚡ {closenessPct}%</span>
                  ) : null}
                  {isLive ? (
                    <span className={styles.featTime}>{t("encounters.state.live")}</span>
                  ) : null}
                </div>
              </div>
            );
          })
        ) : (
          <div className={styles.empty}>{t("encounters.featured.empty")}</div>
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
  const t = useTranslations();
  const router = useRouter();
  const winner = getWinnerSide(encounter);
  const stateLabel = getEncounterStateLabel(encounter);
  const homeName = encounter.home_team?.name ?? t("common.tbd");
  const awayName = encounter.away_team?.name ?? t("common.tbd");
  const sortedMatches = [...(encounter.matches ?? [])].sort((a, b) => a.id - b.id);
  const stageName = stageLabel(encounter, t);
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
      <td className={styles.dim}>{tournamentLabel(encounter, t)}</td>
      <td>
        <span className={cn(styles.stagePill, STAGE_PILL_CLASS[stageBucket])}>{stageName}</span>
      </td>
      <td className={cn(styles.dim, styles.mono)}>
        {t("encounters.roundShort", { round: encounter.round })}
      </td>
      <td className={cn(styles.mono, styles.scoreAlign)}>
        <span
          className={cn(
            styles.scoreCell,
            winner === "home" ? styles.scoreCellWinner : styles.scoreCellLoser
          )}
        >
          {encounter.score.home}
        </span>
        <span className={styles.scoreSep}>–</span>
        <span
          className={cn(
            styles.scoreCell,
            winner === "away" ? styles.scoreCellWinner : styles.scoreCellLoser
          )}
        >
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
            <div className={styles.closenessFill} style={{ width: `${closenessPct ?? 0}%` }} />
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
          {isUpset ? t("encounters.state.upset") : t(stateLabelKey(stateLabel))}
        </span>
      </td>
      <td className={cn(styles.dim, styles.mono)}>{formatCompactDate(getPlayedAt(encounter))}</td>
    </tr>
  );
}

const MEDIA_ICON_VARIANT: Record<MediaSlotKey, string> = {
  logs: styles.mediaIconLogs,
  vod: styles.mediaIconVod,
  cast: styles.mediaIconCast
};

function MediaIcons({ hasLogs }: { hasLogs: boolean }) {
  const t = useTranslations();
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
                  !slot.enabled && styles.mediaIconDisabled
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
            <TooltipContent>{t(mediaTooltipKey(slot))}</TooltipContent>
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
  valueClassName
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
