"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import { BarChart3, ChevronDown, ChevronUp, LayoutGrid, Search, Trophy } from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import { useCurrentWorkspaceId, useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { clampDivisionToGrid, getDivisionLabel, getDivisionOptions } from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import userService from "@/services/user.service";
import { LogStatsName } from "@/types/stats.types";
import {
  UserCatalogEntry,
  UserOverviewHero,
  UserOverviewRoleDivision,
  UserOverviewRow,
  UserRoleType
} from "@/types/user.types";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";

import styles from "./UsersRedesign.module.css";

// Loose translator alias matching next-intl's `useTranslations()` return type so
// module-scope helpers can accept the caller's `t` (strictFunctionTypes-safe).
type Translate = ReturnType<typeof useTranslations<never>>;

type SortValue = "name" | "tournaments_count" | "achievements_count" | "avg_placement";
type OrderValue = "asc" | "desc";
type ViewMode = "analytics" | "catalog";

type SortLabelKey =
  | "users.list.sort.name"
  | "users.list.sort.tournaments"
  | "users.list.sort.achievements"
  | "users.list.sort.avgPlacement";

const SORT_OPTIONS: Array<{ value: SortValue; labelKey: SortLabelKey }> = [
  { value: "name", labelKey: "users.list.sort.name" },
  { value: "tournaments_count", labelKey: "users.list.sort.tournaments" },
  { value: "achievements_count", labelKey: "users.list.sort.achievements" },
  { value: "avg_placement", labelKey: "users.list.sort.avgPlacement" }
];

type HeroMetricLabelKey =
  | "users.list.heroMetrics.elims"
  | "users.list.heroMetrics.fb"
  | "users.list.heroMetrics.dmg"
  | "users.list.heroMetrics.heal";

const HERO_METRIC_LABEL_KEYS: Record<string, HeroMetricLabelKey> = {
  [LogStatsName.Eliminations]: "users.list.heroMetrics.elims",
  [LogStatsName.FinalBlows]: "users.list.heroMetrics.fb",
  [LogStatsName.HeroDamageDealt]: "users.list.heroMetrics.dmg",
  [LogStatsName.HealingDealt]: "users.list.heroMetrics.heal"
};

// Maps a role type to its shared `common.roles.*` message key (dps = "Damage").
const ROLE_LABEL_KEY: Record<
  UserRoleType,
  "common.roles.tank" | "common.roles.dps" | "common.roles.support"
> = {
  Tank: "common.roles.tank",
  Damage: "common.roles.dps",
  Support: "common.roles.support"
};

const ROLE_FILTERS: Array<{ value: "all" | UserRoleType; labelKey: "common.all" | (typeof ROLE_LABEL_KEY)[UserRoleType] }> = [
  { value: "all", labelKey: "common.all" },
  { value: "Tank", labelKey: "common.roles.tank" },
  { value: "Damage", labelKey: "common.roles.dps" },
  { value: "Support", labelKey: "common.roles.support" }
];

const ALPHABET = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

const parsePositiveInt = (value: string | null, fallback: number): number => {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.floor(parsed);
};

const parseOptionalInt = (value: string | null): number | undefined => {
  if (!value) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return undefined;
  return Math.floor(parsed);
};

const parseSort = (value: string | null): SortValue => {
  const allowed = SORT_OPTIONS.map((option) => option.value);
  return value && (allowed as string[]).includes(value) ? (value as SortValue) : "name";
};

const parseOrder = (value: string | null): OrderValue => {
  return value === "desc" ? "desc" : "asc";
};

const parseView = (value: string | null): ViewMode => {
  return value === "catalog" ? "catalog" : "analytics";
};

const toUserSlug = (name: string): string => name.replace("#", "-");

const formatPlaytime = (seconds: number, t: Translate): string => {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return t("users.list.hero.playtimeFormat", {
    h: String(hours),
    m: String(minutes),
    s: String(secs)
  });
};

const formatOptional = (value: number | null): string => {
  if (value === null) return "-";
  return value.toFixed(2);
};

function splitTag(name: string): { handle: string; tag: string | null } {
  const idx = name.lastIndexOf("#");
  if (idx === -1) {
    return { handle: name, tag: null };
  }
  return { handle: name.slice(0, idx), tag: name.slice(idx) };
}

function initials(name: string): string {
  const trimmed = name.replace(/#.*$/, "").trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/[\s_-]+/).filter(Boolean);
  if (parts.length === 0) return trimmed.slice(0, 2).toUpperCase();
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function primaryRoleLabel(roles: UserOverviewRoleDivision[], t: Translate): string {
  if (roles.length === 0) return t("users.list.roleLabel.unranked");
  if (roles.length === 1) return t(ROLE_LABEL_KEY[roles[0].role]);
  const abbr = roles.map((r) => t(ROLE_LABEL_KEY[r.role]).slice(0, 3).toUpperCase()).join(" / ");
  return `${t("common.roles.flex")} · ${abbr}`;
}

function placementWidth(placement: number | null): { width: number; warn: boolean } {
  if (placement === null || !Number.isFinite(placement)) {
    return { width: 0, warn: false };
  }
  const clamped = Math.max(1, Math.min(30, placement));
  const width = Math.round(((30 - clamped) / 29) * 88 + 12);
  return { width, warn: placement >= 8 };
}

type PaginatedRange = { start: number; end: number };

function visiblePages(current: number, total: number): Array<number | "ellipsis"> {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const result: Array<number | "ellipsis"> = [1];
  const left = Math.max(2, current - 1);
  const right = Math.min(total - 1, current + 1);
  if (left > 2) result.push("ellipsis");
  for (let i = left; i <= right; i += 1) result.push(i);
  if (right < total - 1) result.push("ellipsis");
  result.push(total);
  return result;
}

type FilterChipProps = {
  active?: boolean;
  count?: number;
  onClick?: () => void;
  children: React.ReactNode;
};

const FilterChip = ({ active = false, count, onClick, children }: FilterChipProps) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(styles.filterChip, active && styles.filterChipActive)}
    >
      <span>{children}</span>
      {typeof count === "number" ? <span className={styles.filterChipCount}>{count}</span> : null}
    </button>
  );
};

type DivisionHexProps = {
  role: UserRoleType;
  division: number;
  title?: string;
  size?: number;
};

const DivisionHex = ({ role, division, title, size = 36 }: DivisionHexProps) => {
  const t = useTranslations();
  return (
    <div
      className={styles.divisionBadge}
      title={title}
      style={{ width: size + 2, height: size + 2 }}
    >
      <DivisionIcon division={division} width={size} height={size} className="h-full w-full" />
      <div className={styles.divisionRoleDot}>
        <Image
          src={`/roles/${role}.png`}
          alt={t("users.list.a11y.roleAlt", { role: t(ROLE_LABEL_KEY[role]) })}
          width={12}
          height={12}
        />
      </div>
    </div>
  );
};


const UsersRedesignClient = () => {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const divisionGrid = useDivisionGrid();
  const workspaceId = useCurrentWorkspaceId();
  const t = useTranslations();

  const page = parsePositiveInt(searchParams.get("page"), 1);
  const perPage = parsePositiveInt(searchParams.get("per_page"), 20);
  const query = searchParams.get("query") ?? "";
  const sort = parseSort(searchParams.get("sort"));
  const order = parseOrder(searchParams.get("order"));
  const view = parseView(searchParams.get("view"));
  const role = (searchParams.get("role") as UserRoleType | null) ?? undefined;
  const divMin = clampDivisionToGrid(divisionGrid, parseOptionalInt(searchParams.get("div_min")));
  const divMax = clampDivisionToGrid(divisionGrid, parseOptionalInt(searchParams.get("div_max")));
  const letter = searchParams.get("letter") ?? undefined;

  const [searchInput, setSearchInput] = useState(query);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(() => new Set());
  const [debouncedSearch] = useDebounce(searchInput, 300);

  useEffect(() => {
    setSearchInput(query);
  }, [query]);

  const updateParams = useCallback(
    (updates: Record<string, string | number | undefined>, keepPage = false): void => {
      const next = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (value === undefined || value === "") {
          next.delete(key);
          return;
        }
        next.set(key, String(value));
      });
      if (!keepPage) {
        next.set("page", "1");
      }
      router.replace(`${pathname}?${next.toString()}`);
    },
    [pathname, router, searchParams]
  );

  useEffect(() => {
    const normalizedInput = debouncedSearch.trim();
    const normalizedQuery = query.trim();
    if (normalizedInput === normalizedQuery) return;
    updateParams({ query: normalizedInput || undefined });
  }, [debouncedSearch, query, updateParams]);

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: ["users-overview", workspaceId, page, perPage, query, sort, order, role, divMin, divMax],
    queryFn: () =>
      userService.getUsersOverview({
        page,
        perPage,
        sort,
        order,
        query: query || undefined,
        role,
        divMin,
        divMax,
        workspaceId
      }),
    placeholderData: (previousData) => previousData,
    staleTime: 30_000,
    enabled: view === "analytics"
  });

  const statsQuery = useQuery({
    queryKey: ["users-overview-stats", workspaceId, query, role, divMin, divMax],
    queryFn: () =>
      userService.getUsersOverviewStats({
        query: query || undefined,
        role,
        divMin,
        divMax,
        workspaceId
      }),
    placeholderData: (previousData) => previousData,
    staleTime: 30_000
  });

  const catalogQuery = useQuery({
    queryKey: ["users-overview-catalog", workspaceId, query, role, divMin, divMax, letter],
    queryFn: () =>
      userService.getUsersCatalog({
        query: query || undefined,
        role,
        divMin,
        divMax,
        letter,
        perLetter: 12,
        maxLetters: 27,
        workspaceId
      }),
    placeholderData: (previousData) => previousData,
    staleTime: 30_000,
    enabled: view === "catalog"
  });

  const stats = statsQuery.data;

  const maxPage = useMemo(() => {
    if (!data || data.per_page <= 0) return 1;
    return Math.max(1, Math.ceil(data.total / data.per_page));
  }, [data]);

  const range = useMemo<PaginatedRange | null>(() => {
    if (!data || data.results.length === 0) return null;
    const start = (data.page - 1) * data.per_page + 1;
    const end = start + data.results.length - 1;
    return { start, end };
  }, [data]);

  const toggleRow = useCallback((id: number): void => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleRoleChange = useCallback(
    (value: "all" | UserRoleType) => {
      updateParams({ role: value === "all" ? undefined : value });
    },
    [updateParams]
  );

  const handleDivMinChange = useCallback(
    (value: string) => {
      updateParams({
        div_min:
          value === "all"
            ? undefined
            : clampDivisionToGrid(divisionGrid, parseOptionalInt(value))
      });
    },
    [divisionGrid, updateParams]
  );

  const handleDivMaxChange = useCallback(
    (value: string) => {
      updateParams({
        div_max:
          value === "all"
            ? undefined
            : clampDivisionToGrid(divisionGrid, parseOptionalInt(value))
      });
    },
    [divisionGrid, updateParams]
  );

  const handleSortChange = useCallback(
    (value: SortValue) => {
      updateParams({ sort: value });
    },
    [updateParams]
  );

  const handleOrderChange = useCallback(
    (value: OrderValue) => {
      updateParams({ order: value });
    },
    [updateParams]
  );

  const handleViewChange = useCallback(
    (next: ViewMode) => {
      updateParams({ view: next === "analytics" ? undefined : next });
    },
    [updateParams]
  );

  const handleLetterChange = useCallback(
    (value: string | null) => {
      updateParams({ letter: value === null ? undefined : value });
    },
    [updateParams]
  );

  const goToPage = useCallback(
    (next: number) => {
      const clamped = Math.max(1, Math.min(maxPage, next));
      updateParams({ page: clamped }, true);
    },
    [maxPage, updateParams]
  );

  const divisionOptions = useMemo(() => getDivisionOptions(divisionGrid), [divisionGrid]);
  const sortLabelKey = SORT_OPTIONS.find((option) => option.value === sort)?.labelKey ?? "users.list.sort.name";
  const sortLabel = t(sortLabelKey);
  const divisionTitle = (roleType: UserRoleType, division: number): string =>
    t("users.list.division.badgeTitle", {
      role: t(ROLE_LABEL_KEY[roleType]),
      tier: getDivisionLabel(divisionGrid, division) ?? t("common.divisionWithId", { id: String(division) })
    });
  const showLoadingRows = isLoading && !data;
  const availableLetters = useMemo(
    () => new Set(catalogQuery.data?.available_letters ?? []),
    [catalogQuery.data]
  );

  return (
    <div className={styles.surface}>
      {/* ===== Hero ===== */}
      <PageHero
        eyebrow={
          <HeroCoord>
            <Link href="/" className="transition-colors hover:text-[color:var(--aqt-teal)]">
              {t("users.list.hero.eyebrowRoster")}
            </Link>{" "}
            · {t("users.list.hero.eyebrowCurrent")}
          </HeroCoord>
        }
        title={t.rich("users.list.hero.title", { em: (chunks) => <em>{chunks}</em> })}
        lede={t("users.list.hero.lede")}
        aside={
          <div className={styles.heroStats}>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>{t("users.list.stats.totalPlayers")}</span>
              <span className={styles.statValue}>
                {stats ? stats.total_players.toLocaleString("en") : "-"}
              </span>
              <span className={styles.statSub}>
                {stats
                  ? t("users.list.stats.roleBreakdown", {
                      tank: String(stats.tank_count),
                      dps: String(stats.damage_count),
                      support: String(stats.support_count)
                    })
                  : t("common.loading")}
              </span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>{t("users.list.stats.withLogs")}</span>
              <span className={styles.statValue}>
                {stats ? Math.round(stats.with_logs_pct) : "-"}
                <em>%</em>
              </span>
              <span className={styles.statSub}>
                {stats
                  ? t("users.list.stats.withParsedGames", { count: stats.with_logs_count.toLocaleString("en") })
                  : "—"}
              </span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>{t("users.list.stats.avgTournamentsPerPlayer")}</span>
              <span className={styles.statValue}>
                {stats ? stats.avg_tournaments_per_player.toFixed(1) : "-"}
              </span>
              <span className={styles.statSub}>
                {stats
                  ? t("users.list.stats.median", { value: stats.median_tournaments_per_player.toFixed(0) })
                  : "—"}
              </span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>{t("users.list.stats.activeLast30d")}</span>
              <span className={styles.statValue}>
                {stats ? stats.active_last_30d.toLocaleString("en") : "-"}
              </span>
              <span className={styles.statSub}>
                {stats ? t("users.list.stats.ofRoster", { pct: String(Math.round(stats.active_last_30d_pct)) }) : "—"}
              </span>
            </div>
          </div>
        }
      />

      {/* ===== View switcher + toolbar ===== */}
      <section className={styles.toolbar}>
        <div className={styles.viewSwitch} role="tablist" aria-label={t("users.list.a11y.viewMode")}>
          <button
            type="button"
            role="tab"
            aria-selected={view === "analytics"}
            className={cn(view === "analytics" && styles.viewSwitchActive)}
            onClick={() => handleViewChange("analytics")}
          >
            <BarChart3 size={14} aria-hidden /> {t("users.list.view.analytics")}
            <span className={styles.countBadge}>{t("users.list.view.analyticsBadge")}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "catalog"}
            className={cn(view === "catalog" && styles.viewSwitchActive)}
            onClick={() => handleViewChange("catalog")}
          >
            <LayoutGrid size={14} aria-hidden /> {t("users.list.view.catalog")}
            <span className={styles.countBadge}>{t("users.list.view.catalogBadge")}</span>
          </button>
        </div>
        <div className={styles.toolbarActions}>
          <span className={styles.pill}>
            <Trophy size={11} aria-hidden /> {t("users.list.view.rosterLive")}
          </span>
        </div>
      </section>

      {/* ===== Filters (shared) ===== */}
      <section>
        <div className={styles.filters}>
          {ROLE_FILTERS.map((option) => {
            let count: number | undefined;
            if (stats) {
              if (option.value === "all") count = stats.total_players;
              else if (option.value === "Tank") count = stats.tank_count;
              else if (option.value === "Damage") count = stats.damage_count;
              else if (option.value === "Support") count = stats.support_count;
            }
            return (
              <FilterChip
                key={option.value}
                active={(role ?? "all") === option.value}
                count={count}
                onClick={() => handleRoleChange(option.value)}
              >
                {t(option.labelKey)}
              </FilterChip>
            );
          })}

          {stats && stats.flex_count > 0 ? (
            <FilterChip count={stats.flex_count}>{t("common.roles.flex")}</FilterChip>
          ) : null}

          <span className={styles.filterDivider} />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(styles.filterChip, divMin != null && styles.filterChipActive)}
              >
                <span>
                  {t("users.list.filters.divMin", {
                    value: divMin != null ? getDivisionLabel(divisionGrid, divMin) ?? t("common.any") : t("common.any")
                  })}
                </span>
                <ChevronDown size={10} aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
              <DropdownMenuLabel>{t("users.list.filters.minDivision")}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={divMin != null ? String(divMin) : "all"}
                onValueChange={handleDivMinChange}
              >
                <DropdownMenuRadioItem value="all">{t("users.list.filters.allDivisions")}</DropdownMenuRadioItem>
                {divisionOptions.map((division) => (
                  <DropdownMenuRadioItem key={`min-${division}`} value={String(division)}>
                    {getDivisionLabel(divisionGrid, division)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(styles.filterChip, divMax != null && styles.filterChipActive)}
              >
                <span>
                  {t("users.list.filters.divMax", {
                    value: divMax != null ? getDivisionLabel(divisionGrid, divMax) ?? t("common.any") : t("common.any")
                  })}
                </span>
                <ChevronDown size={10} aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
              <DropdownMenuLabel>{t("users.list.filters.maxDivision")}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={divMax != null ? String(divMax) : "all"}
                onValueChange={handleDivMaxChange}
              >
                <DropdownMenuRadioItem value="all">{t("users.list.filters.allDivisions")}</DropdownMenuRadioItem>
                {divisionOptions.map((division) => (
                  <DropdownMenuRadioItem key={`max-${division}`} value={String(division)}>
                    {getDivisionLabel(divisionGrid, division)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>

          <div className={styles.filterSearch}>
            <Search size={14} className={styles.filterSearchIcon} aria-hidden />
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder={t("users.list.filters.searchPlaceholder")}
              aria-label={t("users.list.a11y.searchPlayers")}
            />
          </div>

          {view === "analytics" ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" className={cn(styles.filterChip, styles.filterSort)}>
                  <span>
                    {t("users.list.filters.sortValue", {
                      value: `${sortLabel} ${order === "desc" ? "▾" : "▴"}`
                    })}
                  </span>
                  <ChevronDown size={10} aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{t("common.sortBy")}</DropdownMenuLabel>
                <DropdownMenuRadioGroup
                  value={sort}
                  onValueChange={(value) => handleSortChange(value as SortValue)}
                >
                  {SORT_OPTIONS.map((option) => (
                    <DropdownMenuRadioItem key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{t("common.order")}</DropdownMenuLabel>
                <DropdownMenuCheckboxItem
                  checked={order === "asc"}
                  onCheckedChange={() => handleOrderChange("asc")}
                >
                  {t("common.ascending")}
                </DropdownMenuCheckboxItem>
                <DropdownMenuCheckboxItem
                  checked={order === "desc"}
                  onCheckedChange={() => handleOrderChange("desc")}
                >
                  {t("common.descending")}
                </DropdownMenuCheckboxItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </section>

      {/* ===== ANALYTICS VIEW ===== */}
      <div className={cn(styles.viewBlock, view === "analytics" && styles.viewBlockActive)}>
        <section>
          <div className={styles.sectionHead}>
            <h2>{t("users.list.table.allPlayers")}</h2>
            <span className={styles.sectionMeta}>
              {data
                ? t("users.list.table.pageMeta", {
                    page: String(data.page),
                    maxPage: String(maxPage),
                    x: `${sortLabel.toLowerCase()} ${order === "asc" ? "▴" : "▾"}`
                  })
                : t("common.loading")}
            </span>
          </div>

          <div className={styles.card}>
            {isError ? (
              <p className={styles.errorMsg}>
                {(error as Error)?.message || t("users.list.errors.overview")}
              </p>
            ) : (
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th style={{ width: "22%" }}>{t("users.list.table.player")}</th>
                      <th className="center">{t("users.list.table.divisions")}</th>
                      <th className="center">{t("common.tournaments")}</th>
                      <th className="center">{t("users.list.table.achievements")}</th>
                      <th>{t("users.list.table.avgPlacement")}</th>
                      <th className={cn(styles.hideMd, "center")}>{t("users.list.table.topHeroes")}</th>
                      <th className="center">{t("users.list.table.details")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {showLoadingRows ? (
                      Array.from({ length: 8 }).map((_, idx) => (
                        <tr key={`skel-${idx}`}>
                          <td colSpan={7} className={styles.skelRow} />
                        </tr>
                      ))
                    ) : data && data.results.length > 0 ? (
                      data.results.map((user: UserOverviewRow, index: number) => {
                        const isExpanded = expandedRows.has(user.id);
                        const { handle, tag } = splitTag(user.name);
                        const topHeroes = user.top_heroes.slice(0, 3);
                        const placement = user.averages.avg_placement;
                        const bar = placementWidth(placement);
                        const globalRank =
                          (data.page - 1) * data.per_page + index + 1;

                        return (
                          <React.Fragment key={user.id}>
                            <tr>
                              <td>
                                <div className={styles.playerCell}>
                                  <span className={styles.playerRank}>#{globalRank}</span>
                                  <div className={styles.playerAvatar} aria-hidden>
                                    {initials(user.name)}
                                  </div>
                                  <div className={styles.playerInfo}>
                                    <Link
                                      className={styles.playerName}
                                      href={`/users/${toUserSlug(user.name)}`}
                                      title={user.name}
                                    >
                                      {handle}
                                      {tag ? <span className="tag">{tag}</span> : null}
                                    </Link>
                                    <span className={styles.playerSub}>
                                      {primaryRoleLabel(user.roles, t)}
                                    </span>
                                  </div>
                                </div>
                              </td>

                              <td className="center">
                                {user.roles.length === 0 ? (
                                  <span className={styles.playerSub}>—</span>
                                ) : (
                                  <div className={styles.divisionCluster}>
                                    {user.roles.map((roleRow) => (
                                      <DivisionHex
                                        key={`${user.id}-${roleRow.role}-${roleRow.division}`}
                                        role={roleRow.role}
                                        division={roleRow.division}
                                        title={divisionTitle(roleRow.role, roleRow.division)}
                                      />
                                    ))}
                                  </div>
                                )}
                              </td>

                              <td className={cn("center", styles.tnum)}>
                                {user.tournaments_count}
                              </td>

                              <td className="center">
                                <span className={styles.achievementsCell}>
                                  <Trophy size={12} aria-hidden /> {user.achievements_count}
                                </span>
                              </td>

                              <td>
                                <div className={styles.placementBar}>
                                  <div className={styles.placementTrack}>
                                    <div
                                      className={cn(
                                        styles.placementFill,
                                        bar.warn && styles.placementFillWarn
                                      )}
                                      style={{ width: `${bar.width}%` }}
                                    />
                                  </div>
                                  <span className={styles.placementNum}>
                                    {formatOptional(placement)}
                                  </span>
                                </div>
                              </td>

                              <td className={cn(styles.hideMd, "center")}>
                                <HeroStrip heroes={topHeroes.map((h) => h.hero)} />
                              </td>

                              <td className="center">
                                <button
                                  type="button"
                                  aria-label={
                                    isExpanded
                                      ? t("users.list.a11y.collapseDetails")
                                      : t("users.list.a11y.expandDetails")
                                  }
                                  onClick={() => toggleRow(user.id)}
                                  className={styles.expandButton}
                                >
                                  {isExpanded ? (
                                    <ChevronUp size={14} aria-hidden />
                                  ) : (
                                    <ChevronDown size={14} aria-hidden />
                                  )}
                                </button>
                              </td>
                            </tr>

                            {isExpanded ? (
                              <tr className={styles.expandRow}>
                                <td colSpan={7}>
                                  <div className={styles.exGrid}>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>{t("users.list.expanded.avgPlacement")}</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_placement)}
                                      </span>
                                    </div>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>{t("users.list.expanded.avgPlayoff")}</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_playoff_placement)}
                                      </span>
                                    </div>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>{t("users.list.expanded.avgGroup")}</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_group_placement)}
                                      </span>
                                    </div>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>{t("users.list.expanded.avgCloseness")}</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_closeness)}
                                      </span>
                                    </div>
                                  </div>
                                  <div className={styles.exSectionTitle}>{t("users.list.expanded.topHeroesDetails")}</div>
                                  <p className={styles.exSectionNote}>
                                    {t("users.list.expanded.metricsNote")}
                                  </p>
                                  {user.top_heroes.length === 0 ? (
                                    <p className={styles.playerSub}>{t("users.list.expanded.noHeroData")}</p>
                                  ) : (
                                    <div className={styles.heroCards}>
                                      {user.top_heroes.map((heroRow) => (
                                        <div
                                          key={`${user.id}-${heroRow.hero.id}`}
                                          className={styles.heroCard}
                                        >
                                          <div className={styles.heroCardTop}>
                                            <div className={styles.heroCardAvatar}>
                                              <Image
                                                src={heroRow.hero.image_path}
                                                alt={heroRow.hero.name}
                                                width={40}
                                                height={40}
                                                className="object-contain select-none"
                                              />
                                            </div>
                                            <div className={styles.heroCardStack}>
                                              <span className={styles.heroCardName}>
                                                {heroRow.hero.name}
                                              </span>
                                              <span className={styles.heroCardPlaytime}>
                                                {t("users.list.expanded.playtime", {
                                                  value: formatPlaytime(heroRow.playtime_seconds, t)
                                                })}
                                              </span>
                                            </div>
                                          </div>
                                          <div className={styles.heroCardMetrics}>
                                            {heroRow.metrics.length === 0 ? (
                                              <span className={styles.playerSub}>{t("users.list.expanded.noMetrics")}</span>
                                            ) : (
                                              heroRow.metrics.map((metric) => {
                                                const metricKey = HERO_METRIC_LABEL_KEYS[metric.name];
                                                return (
                                                  <span
                                                    key={`${heroRow.hero.id}-${metric.name}`}
                                                    className={styles.metricBadge}
                                                  >
                                                    <span className={styles.metricBadgeKey}>
                                                      {metricKey ? t(metricKey) : metric.name}
                                                    </span>
                                                    <span className={styles.metricBadgeValue}>
                                                      {metric.avg_10.toFixed(2)}
                                                    </span>
                                                  </span>
                                                );
                                              })
                                            )}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </td>
                              </tr>
                            ) : null}
                          </React.Fragment>
                        );
                      })
                    ) : (
                      <tr>
                        <td colSpan={7} className={styles.empty}>
                          {t("users.list.empty")}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {data && data.results.length > 0 ? (
              <div className={styles.paginationBar}>
                <span className={styles.pageInfo}>
                  {range
                    ? t("users.list.pagination.showingPlayers", {
                        start: range.start,
                        end: range.end,
                        total: data.total
                      })
                    : null}
                  {isFetching ? ` · ${t("users.list.pagination.refreshing")}` : null}
                </span>
                <div className={styles.pageControls}>
                  <button
                    type="button"
                    className={styles.pageBtn}
                    onClick={() => goToPage(page - 1)}
                    disabled={page <= 1}
                  >
                    ‹ {t("common.prev")}
                  </button>
                  {visiblePages(page, maxPage).map((entry, idx) =>
                    entry === "ellipsis" ? (
                      <span
                        key={`ellipsis-${idx}`}
                        className={cn(styles.pageBtn, styles.pageBtnEllipsis)}
                      >
                        …
                      </span>
                    ) : (
                      <button
                        key={entry}
                        type="button"
                        onClick={() => goToPage(entry)}
                        className={cn(styles.pageBtn, entry === page && styles.pageBtnActive)}
                        aria-current={entry === page ? "page" : undefined}
                      >
                        {entry}
                      </button>
                    )
                  )}
                  <button
                    type="button"
                    className={styles.pageBtn}
                    onClick={() => goToPage(page + 1)}
                    disabled={page >= maxPage}
                  >
                    {t("common.next")} ›
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>

      {/* ===== CATALOG VIEW ===== */}
      <div className={cn(styles.viewBlock, view === "catalog" && styles.viewBlockActive)}>
        <section>
          <div className={styles.alphaBar}>
            <span className={styles.alphaLabel}>{t("users.list.catalog.jumpTo")}</span>
            <button
              type="button"
              className={cn(styles.alphaLink, !letter && styles.alphaLinkActive)}
              onClick={() => handleLetterChange(null)}
            >
              {t("common.all")}
            </button>
            {ALPHABET.map((alpha) => {
              const isAvailable = availableLetters.has(alpha);
              const isActive = letter === alpha;
              return (
                <button
                  key={alpha}
                  type="button"
                  className={cn(
                    styles.alphaLink,
                    isActive && styles.alphaLinkActive,
                    !isAvailable && !catalogQuery.isLoading && styles.alphaLinkDisabled
                  )}
                  disabled={!isAvailable && !catalogQuery.isLoading}
                  onClick={() => handleLetterChange(alpha)}
                >
                  {alpha}
                </button>
              );
            })}
          </div>

          {catalogQuery.isError ? (
            <p className={styles.errorMsg}>
              {(catalogQuery.error as Error)?.message || t("users.list.errors.catalog")}
            </p>
          ) : catalogQuery.data && catalogQuery.data.letters.length > 0 ? (
            <>
              {catalogQuery.data.letters.map((bucket) => (
                <div key={bucket.letter} className={styles.catSection}>
                  <h3 className={styles.catLetter}>{bucket.letter}</h3>
                  <div className={styles.catGrid}>
                    {bucket.users.map((cardUser) => (
                      <CatalogCard
                        key={cardUser.id}
                        user={cardUser}
                        divisionGrid={divisionGrid}
                      />
                    ))}
                  </div>
                </div>
              ))}
              <div
                className={styles.paginationBar}
                style={{
                  marginTop: 18,
                  border: "1px solid var(--u-border)",
                  borderRadius: 12,
                  borderTop: "1px solid var(--u-border)"
                }}
              >
                <span className={styles.pageInfo}>
                  {t("users.list.catalog.showing", {
                    count: catalogQuery.data.letters.reduce((acc, b) => acc + b.users.length, 0),
                    total: catalogQuery.data.total
                  })}
                </span>
                <span className={styles.pageInfo}>
                  {catalogQuery.isFetching ? t("users.list.pagination.refreshing") : null}
                </span>
              </div>
            </>
          ) : catalogQuery.isLoading ? (
            <div className={styles.catSection}>
              <div className={styles.catGrid}>
                {Array.from({ length: 8 }).map((_, idx) => (
                  <div
                    key={`cat-skel-${idx}`}
                    className={cn(styles.catCard, styles.skelRow)}
                    style={{ height: 160 }}
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className={styles.empty}>{t("users.list.empty")}</div>
          )}
        </section>
      </div>
    </div>
  );
};

type CatalogCardProps = {
  user: UserCatalogEntry;
  divisionGrid: ReturnType<typeof useDivisionGrid>;
};

const CatalogCard = ({ user, divisionGrid }: CatalogCardProps) => {
  const t = useTranslations();
  const { handle, tag } = splitTag(user.name);
  const topHeroes = user.top_heroes.slice(0, 3);

  return (
    <Link href={`/users/${toUserSlug(user.name)}`} className={styles.catCard}>
      <div className={styles.catCardTop}>
        <div className={styles.catCardAvatar} aria-hidden>
          {initials(user.name)}
        </div>
        <div className={styles.catCardInfo}>
          <div className={styles.catCardName} title={user.name}>
            {handle}
            {tag ? <span className="tag">{tag}</span> : null}
          </div>
          <div className={styles.catCardMeta}>{primaryRoleLabel(user.roles, t)}</div>
        </div>
        <div className={styles.catCardRoles}>
          {user.roles.map((roleRow) => (
            <DivisionHex
              key={`${user.id}-cat-${roleRow.role}-${roleRow.division}`}
              role={roleRow.role}
              division={roleRow.division}
              size={28}
              title={t("users.list.division.badgeTitle", {
                role: t(ROLE_LABEL_KEY[roleRow.role]),
                tier:
                  getDivisionLabel(divisionGrid, roleRow.division) ??
                  t("common.divisionWithId", { id: String(roleRow.division) })
              })}
            />
          ))}
        </div>
      </div>

      <div className={styles.catCardHeroes}>
        <span>{t("users.list.table.topHeroes")}</span>
        <div className={styles.catCardHeroesStrip}>
          {topHeroes.length === 0 ? (
            <span className={styles.playerSub}>—</span>
          ) : (
            topHeroes.map((heroRow) => (
              <div
                key={`${user.id}-heroes-${heroRow.hero.id}`}
                className={styles.heroChip}
                title={heroRow.hero.name}
              >
                <Image
                  src={heroRow.hero.image_path}
                  alt={heroRow.hero.name}
                  width={28}
                  height={28}
                  className="object-contain select-none"
                />
              </div>
            ))
          )}
        </div>
      </div>

      <div className={styles.catStats}>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>{t("users.list.catalog.tournaments")}</span>
          <span className={styles.catStatValue}>{user.tournaments_count}</span>
        </div>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>{t("users.list.catalog.achievements")}</span>
          <span className={styles.catStatValue}>{user.achievements_count}</span>
        </div>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>{t("users.list.catalog.avgPlacement")}</span>
          <span className={styles.catStatValue}>{formatOptional(user.avg_placement)}</span>
        </div>
      </div>
    </Link>
  );
};

export default UsersRedesignClient;
