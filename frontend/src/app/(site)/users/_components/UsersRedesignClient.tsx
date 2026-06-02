"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import { BarChart3, ChevronDown, ChevronUp, LayoutGrid, Search, Trophy } from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
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

type SortValue = "name" | "tournaments_count" | "achievements_count" | "avg_placement";
type OrderValue = "asc" | "desc";
type ViewMode = "analytics" | "catalog";

const SORT_OPTIONS: Array<{ value: SortValue; label: string }> = [
  { value: "name", label: "Name" },
  { value: "tournaments_count", label: "Tournaments" },
  { value: "achievements_count", label: "Achievements" },
  { value: "avg_placement", label: "Avg placement" }
];

const HERO_METRIC_LABELS: Record<string, string> = {
  [LogStatsName.Eliminations]: "Elims",
  [LogStatsName.FinalBlows]: "FB",
  [LogStatsName.HeroDamageDealt]: "Dmg",
  [LogStatsName.HealingDealt]: "Heal"
};

const ROLE_FILTERS: Array<{ value: "all" | UserRoleType; label: string }> = [
  { value: "all", label: "All" },
  { value: "Tank", label: "Tank" },
  { value: "Damage", label: "Damage" },
  { value: "Support", label: "Support" }
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

const formatPlaytime = (seconds: number): string => {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${hours}h ${minutes}m ${secs}s`;
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

function primaryRoleLabel(roles: UserOverviewRoleDivision[]): string {
  if (roles.length === 0) return "Unranked";
  if (roles.length === 1) return roles[0].role;
  return `Flex · ${roles.map((r) => r.role.slice(0, 3).toUpperCase()).join(" / ")}`;
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
  return (
    <div
      className={styles.divisionBadge}
      title={title}
      style={{ width: size + 2, height: size + 2 }}
    >
      <DivisionIcon division={division} width={size} height={size} className="h-full w-full" />
      <div className={styles.divisionRoleDot}>
        <Image src={`/roles/${role}.png`} alt={`${role} role`} width={12} height={12} />
      </div>
    </div>
  );
};


const UsersRedesignClient = () => {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const divisionGrid = useDivisionGrid();

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
    queryKey: ["users-overview", page, perPage, query, sort, order, role, divMin, divMax],
    queryFn: () =>
      userService.getUsersOverview({
        page,
        perPage,
        sort,
        order,
        query: query || undefined,
        role,
        divMin,
        divMax
      }),
    placeholderData: (previousData) => previousData,
    staleTime: 30_000,
    enabled: view === "analytics"
  });

  const statsQuery = useQuery({
    queryKey: ["users-overview-stats", query, role, divMin, divMax],
    queryFn: () =>
      userService.getUsersOverviewStats({
        query: query || undefined,
        role,
        divMin,
        divMax
      }),
    placeholderData: (previousData) => previousData,
    staleTime: 30_000
  });

  const catalogQuery = useQuery({
    queryKey: ["users-overview-catalog", query, role, divMin, divMax, letter],
    queryFn: () =>
      userService.getUsersCatalog({
        query: query || undefined,
        role,
        divMin,
        divMax,
        letter,
        perLetter: 12,
        maxLetters: 27
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
  const sortLabel = SORT_OPTIONS.find((option) => option.value === sort)?.label ?? "Name";
  const showLoadingRows = isLoading && !data;
  const availableLetters = useMemo(
    () => new Set(catalogQuery.data?.available_letters ?? []),
    [catalogQuery.data]
  );

  return (
    <div className={styles.surface}>
      {/* ===== Hero ===== */}
      <section className={styles.hero}>
        <div className={styles.hex} />
        <div className={styles.glow1} />
        <div className={styles.glow2} />
        <div className={styles.heroGrid}>
          <div>
            <p className={styles.crumb}>
              <Link href="/">Roster</Link> · Users
            </p>
            <h1 className={styles.title}>
              The <em className={styles.titleAccent}>players</em> behind the tags
            </h1>
            <p className={styles.subtitle}>
              Every competitor across every tournament — sliceable by role, division and hero
              pool. Switch between deep analytics and a fast browsing catalog.
            </p>
          </div>
          <div className={styles.heroStats}>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>Total players</span>
              <span className={styles.statValue}>
                {stats ? stats.total_players.toLocaleString("en") : "-"}
              </span>
              <span className={styles.statSub}>
                {stats
                  ? `Tank ${stats.tank_count} · Dmg ${stats.damage_count} · Sup ${stats.support_count}`
                  : "Loading…"}
              </span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>With logs</span>
              <span className={styles.statValue}>
                {stats ? Math.round(stats.with_logs_pct) : "-"}
                <em>%</em>
              </span>
              <span className={styles.statSub}>
                {stats ? `${stats.with_logs_count.toLocaleString("en")} with parsed games` : "—"}
              </span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>Avg tournaments / player</span>
              <span className={styles.statValue}>
                {stats ? stats.avg_tournaments_per_player.toFixed(1) : "-"}
              </span>
              <span className={styles.statSub}>
                {stats ? `median ${stats.median_tournaments_per_player.toFixed(0)}` : "—"}
              </span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.statLabel}>Active last 30d</span>
              <span className={styles.statValue}>
                {stats ? stats.active_last_30d.toLocaleString("en") : "-"}
              </span>
              <span className={styles.statSub}>
                {stats ? `${Math.round(stats.active_last_30d_pct)}% of roster` : "—"}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ===== View switcher + toolbar ===== */}
      <section className={styles.toolbar}>
        <div className={styles.viewSwitch} role="tablist" aria-label="View mode">
          <button
            type="button"
            role="tab"
            aria-selected={view === "analytics"}
            className={cn(view === "analytics" && styles.viewSwitchActive)}
            onClick={() => handleViewChange("analytics")}
          >
            <BarChart3 size={14} aria-hidden /> Analytics
            <span className={styles.countBadge}>deep dive</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "catalog"}
            className={cn(view === "catalog" && styles.viewSwitchActive)}
            onClick={() => handleViewChange("catalog")}
          >
            <LayoutGrid size={14} aria-hidden /> Catalog
            <span className={styles.countBadge}>fast browse</span>
          </button>
        </div>
        <div className={styles.toolbarActions}>
          <span className={styles.pill}>
            <Trophy size={11} aria-hidden /> Roster · live
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
                {option.label}
              </FilterChip>
            );
          })}

          {stats && stats.flex_count > 0 ? (
            <FilterChip count={stats.flex_count}>Flex</FilterChip>
          ) : null}

          <span className={styles.filterDivider} />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(styles.filterChip, divMin != null && styles.filterChipActive)}
              >
                <span>
                  Div min: {divMin != null ? getDivisionLabel(divisionGrid, divMin) : "Any"}
                </span>
                <ChevronDown size={10} aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
              <DropdownMenuLabel>Minimum division</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={divMin != null ? String(divMin) : "all"}
                onValueChange={handleDivMinChange}
              >
                <DropdownMenuRadioItem value="all">All divisions</DropdownMenuRadioItem>
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
                  Div max: {divMax != null ? getDivisionLabel(divisionGrid, divMax) : "Any"}
                </span>
                <ChevronDown size={10} aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
              <DropdownMenuLabel>Maximum division</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={divMax != null ? String(divMax) : "all"}
                onValueChange={handleDivMaxChange}
              >
                <DropdownMenuRadioItem value="all">All divisions</DropdownMenuRadioItem>
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
              placeholder="Search by name or BattleTag…"
              aria-label="Search players"
            />
          </div>

          {view === "analytics" ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" className={cn(styles.filterChip, styles.filterSort)}>
                  <span>
                    Sort: {sortLabel} {order === "desc" ? "▾" : "▴"}
                  </span>
                  <ChevronDown size={10} aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Sort by</DropdownMenuLabel>
                <DropdownMenuRadioGroup
                  value={sort}
                  onValueChange={(value) => handleSortChange(value as SortValue)}
                >
                  {SORT_OPTIONS.map((option) => (
                    <DropdownMenuRadioItem key={option.value} value={option.value}>
                      {option.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Order</DropdownMenuLabel>
                <DropdownMenuCheckboxItem
                  checked={order === "asc"}
                  onCheckedChange={() => handleOrderChange("asc")}
                >
                  Ascending
                </DropdownMenuCheckboxItem>
                <DropdownMenuCheckboxItem
                  checked={order === "desc"}
                  onCheckedChange={() => handleOrderChange("desc")}
                >
                  Descending
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
            <h2>All players</h2>
            <span className={styles.sectionMeta}>
              {data
                ? `Page ${data.page} of ${maxPage} · sorted by ${sortLabel.toLowerCase()} ${order === "asc" ? "▴" : "▾"}`
                : "Loading…"}
            </span>
          </div>

          <div className={styles.card}>
            {isError ? (
              <p className={styles.errorMsg}>
                {(error as Error)?.message || "Failed to load users overview."}
              </p>
            ) : (
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th style={{ width: "22%" }}>Player</th>
                      <th className="center">Divisions</th>
                      <th className="center">Tournaments</th>
                      <th className="center">Achievements</th>
                      <th>Avg placement</th>
                      <th className={cn(styles.hideMd, "center")}>Top heroes</th>
                      <th className="center">Details</th>
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
                                      {primaryRoleLabel(user.roles)}
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
                                        title={`${roleRow.role} • ${getDivisionLabel(divisionGrid, roleRow.division) ?? `Division ${roleRow.division}`}`}
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
                                      ? "Collapse user details"
                                      : "Expand user details"
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
                                      <span className={styles.exStatLabel}>Avg placement</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_placement)}
                                      </span>
                                    </div>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>Avg playoff</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_playoff_placement)}
                                      </span>
                                    </div>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>Avg group</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_group_placement)}
                                      </span>
                                    </div>
                                    <div className={styles.exStat}>
                                      <span className={styles.exStatLabel}>Avg closeness</span>
                                      <span className={styles.exStatValue}>
                                        {formatOptional(user.averages.avg_closeness)}
                                      </span>
                                    </div>
                                  </div>
                                  <div className={styles.exSectionTitle}>Top heroes details</div>
                                  <p className={styles.exSectionNote}>
                                    All hero metrics are averages per 10 minutes.
                                  </p>
                                  {user.top_heroes.length === 0 ? (
                                    <p className={styles.playerSub}>No hero data.</p>
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
                                              />
                                            </div>
                                            <div className={styles.heroCardStack}>
                                              <span className={styles.heroCardName}>
                                                {heroRow.hero.name}
                                              </span>
                                              <span className={styles.heroCardPlaytime}>
                                                Playtime: {formatPlaytime(heroRow.playtime_seconds)}
                                              </span>
                                            </div>
                                          </div>
                                          <div className={styles.heroCardMetrics}>
                                            {heroRow.metrics.length === 0 ? (
                                              <span className={styles.playerSub}>No metrics</span>
                                            ) : (
                                              heroRow.metrics.map((metric) => (
                                                <span
                                                  key={`${heroRow.hero.id}-${metric.name}`}
                                                  className={styles.metricBadge}
                                                >
                                                  <span className={styles.metricBadgeKey}>
                                                    {HERO_METRIC_LABELS[metric.name] ?? metric.name}
                                                  </span>
                                                  <span className={styles.metricBadgeValue}>
                                                    {metric.avg_10.toFixed(2)}
                                                  </span>
                                                </span>
                                              ))
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
                          No users found for the current filters.
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
                  {range ? `Showing ${range.start} – ${range.end} of ${data.total} players` : null}
                  {isFetching ? " · refreshing…" : null}
                </span>
                <div className={styles.pageControls}>
                  <button
                    type="button"
                    className={styles.pageBtn}
                    onClick={() => goToPage(page - 1)}
                    disabled={page <= 1}
                  >
                    ‹ Prev
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
                    Next ›
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
            <span className={styles.alphaLabel}>Jump to</span>
            <button
              type="button"
              className={cn(styles.alphaLink, !letter && styles.alphaLinkActive)}
              onClick={() => handleLetterChange(null)}
            >
              All
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
              {(catalogQuery.error as Error)?.message || "Failed to load catalog."}
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
                  Showing {catalogQuery.data.letters.reduce((acc, b) => acc + b.users.length, 0)}{" "}
                  of {catalogQuery.data.total} players
                </span>
                <span className={styles.pageInfo}>
                  {catalogQuery.isFetching ? "refreshing…" : null}
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
            <div className={styles.empty}>No users found for the current filters.</div>
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
          <div className={styles.catCardMeta}>{primaryRoleLabel(user.roles)}</div>
        </div>
        <div className={styles.catCardRoles}>
          {user.roles.map((roleRow) => (
            <DivisionHex
              key={`${user.id}-cat-${roleRow.role}-${roleRow.division}`}
              role={roleRow.role}
              division={roleRow.division}
              size={28}
              title={`${roleRow.role} • ${getDivisionLabel(divisionGrid, roleRow.division) ?? `Division ${roleRow.division}`}`}
            />
          ))}
        </div>
      </div>

      <div className={styles.catCardHeroes}>
        <span>Top heroes</span>
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
                />
              </div>
            ))
          )}
        </div>
      </div>

      <div className={styles.catStats}>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>Tourn.</span>
          <span className={styles.catStatValue}>{user.tournaments_count}</span>
        </div>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>Ach.</span>
          <span className={styles.catStatValue}>{user.achievements_count}</span>
        </div>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>Avg pl.</span>
          <span className={styles.catStatValue}>{formatOptional(user.avg_placement)}</span>
        </div>
      </div>
    </Link>
  );
};

export default UsersRedesignClient;
