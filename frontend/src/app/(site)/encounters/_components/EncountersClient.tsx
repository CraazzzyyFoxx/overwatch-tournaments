"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Pin, Save, Trash2, TrendingUp } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { DataPagination } from "@/components/ui/data-pagination";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { SearchField } from "@/components/ui/search-field";
import { StatusDot } from "@/components/ui/status-dot";
import { EncountersDataTable, FULL_ENCOUNTER_COLUMNS } from "@/components/EncountersTable";
import TeamName, { type TeamNameInput } from "@/components/TeamName";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { notify } from "@/lib/notify";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { getEncounterState, getEncounterWinner } from "@/lib/encounter/status";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";
import {
  applyBuiltInView,
  BUILT_IN_VIEWS,
  type BuiltInViewId,
  DEFAULT_FILTERS,
  ENCOUNTERS_PAGE_SIZE,
  EncounterFilterState,
  filtersToApiFilters,
  filtersToSearchParams,
  formatDuration,
  formatPercent,
  getSeriesDuration,
  type TeamColor
} from "./encounters.helpers";
import styles from "./Encounters.module.css";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// module-level helpers can accept `t` straight through (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations<never>>;

// Same idea for number formatting: module-level helpers take the locale-aware
// formatter instead of pinning a locale of their own.
type NumberFormatter = Pick<ReturnType<typeof useFormatter>, "number">;

type EncountersClientProps = {
  initialData: PaginatedResponse<Encounter>;
  initialOverview: EncounterOverview;
  initialFilters: EncounterFilterState;
  initialPage: number;
  initialError?: string | null;
};

const VIEW_SWATCH_COLOR: Record<TeamColor, string> = {
  teal: "var(--aqt-teal)",
  amber: "var(--aqt-amber)",
  rose: "var(--aqt-rose)",
  violet: "var(--aqt-violet)",
  blue: "var(--aqt-blue)"
};

const STAGE_DONUT_COLORS = [
  "var(--aqt-blue)",
  "var(--aqt-amber)",
  "var(--aqt-rose)",
  "var(--aqt-teal)",
  "var(--aqt-violet)"
];

function countLabel(format: NumberFormatter, value?: number): string {
  return typeof value === "number" ? format.number(value) : "-";
}

function tournamentLabel(encounter: Encounter, t: Translate): string {
  if (!encounter.tournament) return t("common.tournament");
  return encounter.tournament.name;
}

function stageLabel(encounter: Encounter, t: Translate): string {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? t("common.unassignedStage");
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

export default function EncountersClient({
  initialData,
  initialOverview,
  initialFilters,
  initialPage,
  initialError
}: Readonly<EncountersClientProps>) {
  const t = useTranslations();
  const format = useFormatter();
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
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [viewToDelete, setViewToDelete] = useState<EncounterSavedView | null>(null);
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
    queryKey: ["encounters-list", page, apiFilters, effectiveFilters.query],
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
      setSaveDialogOpen(false);
      notify.success(t("encounters.savedView.saved"));
    }
  });

  const deleteViewMutation = useMutation({
    mutationFn: ({ id }: { id: number }) => encounterService.deleteView(id, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounters-saved-views", currentWorkspaceId, userKey]
      });
      setViewToDelete(null);
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

  const isFiltered =
    effectiveFilters.query !== "" ||
    effectiveFilters.status != null ||
    effectiveFilters.has_logs != null ||
    effectiveFilters.tournament_id != null ||
    effectiveFilters.stage_id != null ||
    effectiveFilters.stage_item_id != null ||
    effectiveFilters.best_of != null ||
    effectiveFilters.closeness_min != null ||
    effectiveFilters.closeness_max != null ||
    effectiveFilters.scope !== DEFAULT_FILTERS.scope ||
    effectiveFilters.sort !== DEFAULT_FILTERS.sort;

  const setFilterPatch = (patch: Partial<EncounterFilterState>) => {
    setPage(1);
    setFilters((current) => ({ ...current, ...patch }));
  };

  const clearFilters = () => {
    setSearchValue("");
    setPage(1);
    setFilters(DEFAULT_FILTERS);
  };

  const openSaveDialog = () => {
    if (!user) {
      const nextPath = getCurrentPathForAuthRedirect(window.location);
      openAuthModal(nextPath);
      return;
    }
    setSaveName(t("encounters.savedView.promptDefault"));
    setSaveDialogOpen(true);
  };

  const showingStart = rows.length ? (page - 1) * ENCOUNTERS_PAGE_SIZE + 1 : 0;
  const showingEnd = Math.min(page * ENCOUNTERS_PAGE_SIZE, encounters.total);

  // Status is owned by these chips alone. There used to be a "Status: …" select
  // beside them setting the same field with a different option set, so the two
  // controls silently overwrote each other — and the select added a third "All".
  const statusChips: Array<{ id: string; label: string; count?: number; value: string }> = [
    { id: "live", label: t("common.live"), count: overview.kpis.live_now_count, value: "live" },
    {
      id: "pending",
      label: t("encounters.filter.statusPending"),
      count: overview.kpis.upcoming_count,
      value: "pending"
    },
    { id: "completed", label: t("encounters.filter.statusFinal"), value: "completed" },
    { id: "open", label: t("encounters.filter.statusOpen"), value: "open" }
  ];

  const listBody = () => {
    if (listQuery.isError) {
      return <PageStateCard state="error" onAction={() => void listQuery.refetch()} />;
    }
    if (!rows.length && !listQuery.isFetching) {
      return (
        <PageStateCard
          state={isFiltered ? "filtered-empty" : "empty"}
          onAction={isFiltered ? clearFilters : undefined}
        />
      );
    }
    return (
      <EncountersDataTable
        rows={rows}
        columns={FULL_ENCOUNTER_COLUMNS}
        loading={listQuery.isFetching && !rows.length}
      />
    );
  };

  return (
    <div className={styles.surface}>
      <Hero overview={overview} />

      {initialError ? (
        <PageStateCard
          state="error"
          description={initialError}
          onAction={() => {
            void listQuery.refetch();
            void overviewQuery.refetch();
          }}
        />
      ) : null}

      <section aria-label={t("encounters.aria.views")}>
        <div className={styles.views}>
          <span className={styles.viewsLabel}>
            <Bookmark aria-hidden className="h-3 w-3" /> {t("encounters.views")}
          </span>
          {BUILT_IN_VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              aria-pressed={activeView === view.id}
              className={cn(styles.viewTab, activeView === view.id && styles.viewTabActive)}
              onClick={() => {
                setPage(1);
                const next = applyBuiltInView(view.id, effectiveFilters);
                setSearchValue(next.query);
                setFilters(next);
              }}
            >
              {view.showPin ? (
                <Pin aria-hidden className={cn("h-3 w-3", styles.viewPin)} fill="currentColor" />
              ) : view.swatch ? (
                <span
                  aria-hidden
                  className={styles.viewSwatch}
                  style={{ background: VIEW_SWATCH_COLOR[view.swatch] }}
                />
              ) : null}
              <span>{t(view.labelKey)}</span>
              <span className={styles.viewCount}>{countLabel(format, overview.preset_counts[view.id])}</span>
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
                <Bookmark aria-hidden className="h-3 w-3" />
                <span>{view.name}</span>
              </button>
              <button
                type="button"
                className={styles.savedViewDelete}
                aria-label={t("encounters.savedView.deleteAria", { name: view.name })}
                disabled={deleteViewMutation.isPending}
                onClick={() => setViewToDelete(view)}
              >
                <Trash2 aria-hidden className="h-3 w-3" />
              </button>
            </div>
          ))}
          <ConfirmDialog
            open={viewToDelete != null}
            onOpenChange={(open) => {
              if (!open) setViewToDelete(null);
            }}
            intent={{
              title: t("encounters.savedView.deleteTitle"),
              description: t("encounters.savedView.confirmDelete", {
                name: viewToDelete?.name ?? ""
              }),
              confirmLabel: t("common.delete"),
              tone: "danger"
            }}
            pending={deleteViewMutation.isPending}
            onConfirm={() => {
              if (viewToDelete) deleteViewMutation.mutate({ id: viewToDelete.id });
            }}
          />
          <span className={styles.viewsSpacer} />
          <button
            type="button"
            className={styles.viewSave}
            onClick={openSaveDialog}
            disabled={saveViewMutation.isPending}
          >
            {saveViewMutation.isPending ? (
              <Spinner className="size-3" />
            ) : (
              <Save aria-hidden className="h-3 w-3" />
            )}
            <span>{t("encounters.savedView.saveCurrent")}</span>
          </button>
        </div>
      </section>

      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>{t("encounters.savedView.saveCurrent")}</DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              const name = saveName.trim();
              if (!name) return;
              saveViewMutation.mutate({ name });
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="saved-view-name">{t("encounters.savedView.promptName")}</Label>
              <Input
                id="saved-view-name"
                value={saveName}
                onChange={(event) => setSaveName(event.target.value)}
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setSaveDialogOpen(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!saveName.trim() || saveViewMutation.isPending}>
                {t("common.save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <section aria-label={t("encounters.aria.filters")}>
        <div className={styles.filters}>
          <FilterChipGroup label={t("common.status")}>
            {statusChips.map((chip) => (
              <FilterChip
                key={chip.id}
                active={effectiveFilters.status === chip.value}
                count={chip.count == null ? undefined : countLabel(format, chip.count)}
                onClick={() =>
                  setFilterPatch({
                    status: effectiveFilters.status === chip.value ? null : chip.value
                  })
                }
              >
                {chip.label}
              </FilterChip>
            ))}
          </FilterChipGroup>
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
          <SearchField
            value={searchValue}
            onValueChange={(next) => {
              setPage(1);
              setSearchValue(next);
            }}
            label={t("encounters.searchPlaceholder")}
            placeholder={t("encounters.searchPlaceholder")}
            containerClassName={styles.filterSearch}
          />
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
                    aria-label={`${bucket.label}: ${bucket.count}`}
                    style={{ height: `${Math.max(6, (bucket.count / maxHistogram) * 100)}%` }}
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
                  {countLabel(format, heatmap.max)}
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
                <span aria-hidden className={styles.scoreLegendGrad} />
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
                  <svg width="140" height="140" viewBox="0 0 140 140" aria-hidden>
                    <circle
                      cx="70"
                      cy="70"
                      r="54"
                      fill="none"
                      stroke="var(--aqt-border)"
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
                    <span className={styles.donutValue}>{countLabel(format, stageDonut.total)}</span>
                    <span className={styles.donutLabel}>{t("encounters.insights.series")}</span>
                  </div>
                </div>
                <div className={styles.donutLegend}>
                  {stageDonut.segments.length ? (
                    stageDonut.segments.map((segment) => (
                      <div key={segment.name} className={styles.legendRow}>
                        <span
                          aria-hidden
                          className={styles.legendSwatch}
                          style={{ background: segment.color }}
                        />
                        <span className={styles.legendName}>{segment.name}</span>
                        <span className={cn(styles.legendValue, "tabular-nums")}>
                          {countLabel(format, segment.count)} · {segment.pct}%
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
          <div className="flex min-w-0 flex-col gap-3">
            {listBody()}
            <DataPagination
              page={page}
              totalPages={totalPages}
              onPageChange={setPage}
              summary={t("encounters.list.showing", {
                start: String(showingStart),
                end: String(showingEnd),
                total: countLabel(format, encounters.total)
              })}
            />
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
                    count: countLabel(format, overview.pulse.completed_series_count)
                  })}
                />
                <Insight
                  label={t("encounters.pulse.sweepRate")}
                  value={`${overview.pulse.sweep_rate}%`}
                  meta={t("encounters.pulse.sweepMeta", {
                    sweeps: countLabel(format, overview.pulse.sweep_count),
                    distance: countLabel(format, overview.pulse.went_distance_count)
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
                      <div aria-hidden className={styles.mapTrack}>
                        <div
                          className={styles.mapFill}
                          style={{ width: `${(map.count / maxMapCount) * 100}%` }}
                        />
                      </div>
                      <span className={cn(styles.mapNum, "tabular-nums")}>
                        {countLabel(format, map.count)}
                      </span>
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
                    className={cn(styles.balanceHome, "tabular-nums")}
                    style={{ width: `${overview.side_balance.home_win_pct}%` }}
                  >
                    {overview.side_balance.home_win_pct}%
                  </div>
                  <div
                    className={cn(styles.balanceAway, "tabular-nums")}
                    style={{ width: `${overview.side_balance.away_win_pct}%` }}
                  >
                    {overview.side_balance.away_win_pct}%
                  </div>
                </div>
                <div className={styles.balanceLegend}>
                  <span>
                    <span aria-hidden className={styles.balanceLegendHome}>
                      ●{" "}
                    </span>
                    {t("encounters.sideBalance.homeWins")}
                  </span>
                  <span>
                    {t("encounters.sideBalance.awayWins")}{" "}
                    <span aria-hidden className={styles.dim}>
                      ●
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </section>
    </div>
  );
}

function Hero({ overview }: Readonly<{ overview: EncounterOverview }>) {
  const t = useTranslations();
  const format = useFormatter();
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
            value={countLabel(format, overview.kpis.total_encounters)}
            foot={
              overview.kpis.recent_count ? (
                <>
                  <span className={styles.delta}>
                    <TrendingUp aria-hidden className="inline size-4 align-[-3px]" />
                    {/* Icon is decorative; the sign reaches AT through this. */}
                    <span className="sr-only">+</span> {countLabel(format, overview.kpis.recent_count)}
                  </span>{" "}
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
              count: countLabel(format, overview.kpis.with_logs_count),
              total: countLabel(format, overview.kpis.total_encounters)
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
            value={countLabel(format, overview.kpis.live_now_count)}
            foot={t("encounters.hero.upcomingCount", {
              count: countLabel(format, overview.kpis.upcoming_count)
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
}: Readonly<{
  label: string;
  value: React.ReactNode;
  foot: React.ReactNode;
}>) {
  return (
    <div className={styles.heroStat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={cn(styles.statValue, "tabular-nums")}>{value}</span>
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
}: Readonly<{
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  items: [string, string][];
  triggerLabel?: string;
  className?: string;
}>) {
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
}: Readonly<{
  row: number;
  cols: number[];
  matrix: Record<string, number>;
  max: number;
}>) {
  const format = useFormatter();
  return (
    <>
      <div className={styles.scoreSide}>{row}</div>
      {cols.map((col) => {
        const count = matrix[`${row}-${col}`] ?? 0;
        const alpha = max > 0 ? Math.max(0.05, count / max) : 0;
        return (
          <div
            key={`${row}-${col}`}
            className={cn(
              styles.scoreCellHeat,
              count === 0 && styles.scoreCellEmpty,
              "tabular-nums"
            )}
            style={{ "--alpha": String(alpha) } as CSSProperties}
          >
            {count > 0 ? countLabel(format, count) : "—"}
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
}: Readonly<{
  title: string;
  subtitle: string;
  encounters: Encounter[];
  variant: "closest" | "live";
}>) {
  const t = useTranslations();
  const format = useFormatter();
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
            const winner = getEncounterWinner(encounter);
            const state = getEncounterState(encounter);
            const isLive = variant === "live" && state === "Live";
            const isUpcoming = variant === "live" && state === "Upcoming";
            const closenessPct =
              encounter.closeness != null ? Math.round(encounter.closeness * 100) : null;
            const scheduledAt = encounter.scheduled_at ? new Date(encounter.scheduled_at) : null;
            return (
              <Link key={encounter.id} href={`/encounters/${encounter.id}`} className={styles.feat}>
                <div>
                  <div className={styles.matchup}>
                    {isLive ? (
                      <span className={cn(styles.statusTag, styles.statusLive)}>
                        <StatusDot className="shadow-[0_0_0_3px_color-mix(in_srgb,currentColor_20%,transparent)]" />
                        {t("encounters.state.live")}
                      </span>
                    ) : null}
                    {isUpcoming ? (
                      <span className={cn(styles.statusTag, styles.statusUpcoming)}>
                        <StatusDot />
                        {t("encounters.state.soon")}
                      </span>
                    ) : null}
                    <TeamChip team={encounter.home_team} />
                    <span className={styles.vs}>{t("common.vs")}</span>
                    <TeamChip team={encounter.away_team} />
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
                      {scheduledAt
                        ? format.dateTime(scheduledAt, { month: "short", day: "numeric" })
                        : "—"}
                    </span>
                  ) : (
                    <span className={cn(styles.featScore, "tabular-nums")}>
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
                    <span className={cn(styles.badgeCloseness, "tabular-nums")}>
                      ⚡ {closenessPct}%
                    </span>
                  ) : null}
                  {isLive ? (
                    <span className={styles.featTime}>{t("encounters.state.live")}</span>
                  ) : null}
                </div>
              </Link>
            );
          })
        ) : (
          <div className={styles.empty}>{t("encounters.featured.empty")}</div>
        )}
      </div>
    </div>
  );
}

function TeamChip({ team }: Readonly<{ team?: TeamNameInput | null }>) {
  const t = useTranslations();
  return (
    <span className={styles.teamChip}>
      <TeamName team={team} fallback={t("common.tbd")} size="xs" />
    </span>
  );
}

function Insight({
  label,
  value,
  meta,
  valueClassName
}: Readonly<{
  label: string;
  value: string;
  meta?: string;
  valueClassName?: string;
}>) {
  return (
    <div className={styles.insightRow}>
      <span className={styles.insightLabel}>{label}</span>
      <span className={cn(styles.insightValue, "tabular-nums", valueClassName)}>{value}</span>
      {meta ? <span className={styles.insightMeta}>{meta}</span> : null}
    </div>
  );
}
