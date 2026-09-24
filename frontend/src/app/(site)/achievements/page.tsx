"use client";

import React, { Suspense, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Award, Crown, Flame, Gem, Sparkles } from "lucide-react";

import achievementsService from "@/services/achievements.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { cn } from "@/lib/utils";
import { useQueryParams } from "@/hooks/useQueryParams";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { PageStateCard } from "@/components/ui/page-state-card";
import { SearchField } from "@/components/ui/search-field";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { Achievement, AchievementCategory } from "@/types/achievement.types";
import {
  classifyRarity,
  rarityRanges,
  rarityVarClass,
  RARITY_ORDER,
  rarityTitles,
  type Rarity
} from "@/app/(site)/users/components/achievements/rarity";

import AchievementsHero from "./components/AchievementsHero";
import AchievementTile from "./components/AchievementTile";
import AchievementConditionsDialog from "./components/AchievementConditionsDialog";

type SortBy = "rarity" | "name" | "count";

const SORT_VALUES: SortBy[] = ["rarity", "name", "count"];

const RARITY_ICON: Record<Rarity, React.ReactNode> = {
  mythic: <Flame size={15} />,
  legendary: <Crown size={15} />,
  epic: <Gem size={15} />,
  rare: <Sparkles size={15} />,
  uncommon: <Award size={15} />,
  common: <Award size={15} />
};

const emptyBuckets = (): Record<Rarity, Achievement[]> => ({
  mythic: [],
  legendary: [],
  epic: [],
  rare: [],
  uncommon: [],
  common: []
});

const isRarity = (value: string | null): value is Rarity =>
  value != null && (RARITY_ORDER as string[]).includes(value);

const PageSkeleton = () => (
  <div className="aqt-player space-y-6">
    <Skeleton className="h-[220px] w-full rounded-2xl" />
    <Skeleton className="h-[92px] w-full rounded-xl" />
    <Skeleton className="h-10 w-full rounded-lg" />
    <div className="aqt-ach-tiles">
      {Array.from({ length: 12 }).map((_, i) => (
        <Skeleton key={i} className="aspect-square rounded-xl" />
      ))}
    </div>
  </div>
);

const AchievementsPage = () => {
  const t = useTranslations();
  const ranges = rarityRanges(t);
  const titles = rarityTitles(t);
  const tierNames = useMemo(
    () =>
      Object.fromEntries(
        RARITY_ORDER.map((r) => [r, t(`achievements.rarityName.${r}`)])
      ) as Record<Rarity, string>,
    [t]
  );

  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });

  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const workspaceName = workspaces.find((w) => w.id === workspaceId)?.name;

  const rarityParam = searchParams.get("rarity");
  const rarityFilter: Rarity | null = isRarity(rarityParam) ? rarityParam : null;
  const categoryFilter = (searchParams.get("category") as AchievementCategory | null) ?? null;
  const search = searchParams.get("q") ?? "";
  const sortParam = searchParams.get("sort") as SortBy | null;
  const sort: SortBy = sortParam && SORT_VALUES.includes(sortParam) ? sortParam : "rarity";

  const [rulesFor, setRulesFor] = useState<Achievement | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["achievements", "all", workspaceId],
    queryFn: () => achievementsService.getAll(1, -1, workspaceId)
  });

  const results = useMemo(() => data?.results ?? [], [data?.results]);

  const grouped = useMemo(() => {
    const buckets = emptyBuckets();
    for (const ach of results) {
      buckets[classifyRarity(ach.rarity * 100)].push(ach);
    }
    return buckets;
  }, [results]);

  const counts = useMemo(
    () =>
      Object.fromEntries(RARITY_ORDER.map((r) => [r, grouped[r].length])) as Record<Rarity, number>,
    [grouped]
  );

  const categories = useMemo(() => {
    const present = new Set<AchievementCategory>();
    for (const ach of results) {
      if (ach.category) present.add(ach.category);
    }
    // Collate explicitly: these become filter chips, and bare `.sort()` orders
    // by UTF-16 code unit rather than by how the labels actually read.
    return Array.from(present).sort((a, b) => a.localeCompare(b));
  }, [results]);

  const stats = useMemo(() => {
    if (results.length === 0) return { total: 0, rarest: 0, totalEarned: 0 };
    return {
      total: results.length,
      rarest: Math.min(...results.map((a) => a.rarity)) * 100,
      totalEarned: results.reduce((sum, a) => sum + (a.count ?? 0), 0)
    };
  }, [results]);

  const visibleGrouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const forTier = (r: Rarity): Achievement[] => {
      if (rarityFilter && rarityFilter !== r) return [];
      let list = grouped[r];
      if (categoryFilter) list = list.filter((a) => a.category === categoryFilter);
      if (q) {
        list = list.filter(
          (a) =>
            a.name.toLowerCase().includes(q) ||
            a.description_ru?.toLowerCase().includes(q) ||
            a.description_en?.toLowerCase().includes(q)
        );
      }
      return [...list].sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name);
        if (sort === "count") return (b.count ?? 0) - (a.count ?? 0);
        return a.rarity - b.rarity; // rarest first
      });
    };
    return Object.fromEntries(RARITY_ORDER.map((r) => [r, forTier(r)])) as Record<
      Rarity,
      Achievement[]
    >;
  }, [grouped, rarityFilter, categoryFilter, search, sort]);

  const visibleCount = useMemo(
    () => RARITY_ORDER.reduce((sum, r) => sum + visibleGrouped[r].length, 0),
    [visibleGrouped]
  );

  const filtersActive = rarityFilter !== null || categoryFilter !== null || search.trim() !== "";

  const clearFilters = () => setParams({ rarity: null, category: null, q: null });

  if (isLoading) return <PageSkeleton />;

  if (isError) {
    return (
      <div className="aqt-player">
        <PageStateCard
          state="error"
          description={t("common.loadError")}
          onAction={() => void refetch()}
        />
      </div>
    );
  }

  return (
    <div className="aqt-player space-y-6">
      <AchievementsHero
        workspaceName={workspaceName}
        total={stats.total}
        rarestPct={stats.rarest}
        totalEarned={stats.totalEarned}
        mythicCount={counts.mythic}
      />

      {/* Rarity distribution strip — activate a tier to filter to it. */}
      <div className="aqt-ach-rank">
        {RARITY_ORDER.map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={rarityFilter === r}
            onClick={() => setParams({ rarity: rarityFilter === r ? null : r })}
            className={cn(
              "aqt-tier cursor-pointer text-left transition-opacity outline-none",
              "focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
              r,
              rarityFilter && rarityFilter !== r && "opacity-40"
            )}
          >
            <span className="aqt-l">{tierNames[r]}</span>
            <span className="aqt-n tabular-nums">{counts[r]}</span>
            <span className="aqt-sub">{ranges[r]}</span>
          </button>
        ))}
      </div>

      {/* Toolbar: rarity + category filters, sort, search */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChipGroup label={t("common.filters")}>
          <FilterChip
            active={!filtersActive}
            count={stats.total}
            onClick={clearFilters}
          >
            {t("common.all")}
          </FilterChip>

          <span aria-hidden className="aqt-filter-divider" />

          {RARITY_ORDER.map((r) => (
            <FilterChip
              key={r}
              active={rarityFilter === r}
              count={counts[r]}
              onClick={() => setParams({ rarity: rarityFilter === r ? null : r })}
            >
              {tierNames[r]}
            </FilterChip>
          ))}

          {categories.length > 0 ? (
            <>
              <span aria-hidden className="aqt-filter-divider" />
              {categories.map((cat) => (
                <FilterChip
                  key={cat}
                  active={categoryFilter === cat}
                  onClick={() => setParams({ category: categoryFilter === cat ? null : cat })}
                >
                  {t(`achievements.category.${cat}`)}
                </FilterChip>
              ))}
            </>
          ) : null}
        </FilterChipGroup>

        {/* Wraps at narrow widths: as one no-wrap row the count + sort + search
            reached 400px inside a 375px viewport and scrolled the page. */}
        <div className="flex flex-wrap items-center gap-2 sm:ml-auto sm:flex-nowrap">
          <span className="aqt-tnum text-label tabular-nums text-[color:var(--aqt-fg-dim)]">
            {t("achievements.results", { count: visibleCount })}
          </span>
          <Select value={sort} onValueChange={(v) => setParams({ sort: v })}>
            <SelectTrigger
              aria-label={t("users.achievements.sort.title")}
              className="aqt-tnum h-8 w-[150px] border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] text-caption text-[color:var(--aqt-fg-muted)] shadow-none hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-3)]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="rarity">{t("users.achievements.sort.rarity")}</SelectItem>
              <SelectItem value="name">{t("users.achievements.sort.name")}</SelectItem>
              <SelectItem value="count">{t("users.achievements.sort.earned")}</SelectItem>
            </SelectContent>
          </Select>
          <SearchField
            value={search}
            onValueChange={(value) => setParams({ q: value })}
            label={t("common.searchLabel")}
            placeholder={t("achievements.searchPlaceholder")}
            containerClassName="w-full sm:w-auto sm:min-w-[180px]"
          />
        </div>
      </div>

      {/* Rarity sections */}
      {visibleCount === 0 ? (
        <PageStateCard
          state={filtersActive ? "filtered-empty" : "empty"}
          title={t("achievements.empty.title")}
          description={filtersActive ? undefined : t("achievements.empty.body")}
          onAction={filtersActive ? clearFilters : undefined}
        />
      ) : (
        RARITY_ORDER.map((r) => {
          const list = visibleGrouped[r];
          if (list.length === 0) return null;
          return (
            <section key={r} className={cn("aqt-card-surface", rarityVarClass(r))}>
              <div className="aqt-card-head">
                <div className="aqt-card-title">
                  <span className="aqt-card-title-ic aqt-rar-fg">{RARITY_ICON[r]}</span>
                  <span>{titles[r]}</span>
                </div>
                <span className="aqt-card-sub tabular-nums">
                  {t("achievements.sectionCount", { count: list.length })}
                </span>
              </div>
              <div className="aqt-card-body">
                <div className="aqt-ach-tiles">
                  {list.map((ach) => (
                    <AchievementTile key={ach.id} achievement={ach} onViewRules={setRulesFor} />
                  ))}
                </div>
              </div>
            </section>
          );
        })
      )}

      <AchievementConditionsDialog achievement={rulesFor} onClose={() => setRulesFor(null)} />
    </div>
  );
};

const AchievementsPageWrapper = () => (
  <Suspense fallback={<PageSkeleton />}>
    <AchievementsPage />
  </Suspense>
);

export default AchievementsPageWrapper;
