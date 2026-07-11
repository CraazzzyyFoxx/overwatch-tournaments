"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, Award, Crown, Flame, Gem, Search, Sparkles } from "lucide-react";

import achievementsService from "@/services/achievements.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { cn } from "@/lib/utils";
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
  rarityTitles,
  rarityVarClass,
  RARITY_ORDER,
  type Rarity
} from "@/app/(site)/users/components/achievements/rarity";

import AchievementsHero from "./components/AchievementsHero";
import AchievementTile from "./components/AchievementTile";
import AchievementConditionsDialog from "./components/AchievementConditionsDialog";

type SortBy = "rarity" | "name" | "count";

const RARITY_ICON: Record<Rarity, React.ReactNode> = {
  mythic: <Flame size={15} />,
  legendary: <Crown size={15} />,
  epic: <Gem size={15} />,
  rare: <Sparkles size={15} />,
  uncommon: <Award size={15} />,
  common: <Award size={15} />
};

// Enter/Space activation for the `role="button"` filter chips + rarity strip
// (native buttons do this for free; ARIA buttons must wire it themselves).
const activateOnKey =
  (fn: () => void) =>
  (e: React.KeyboardEvent): void => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  };

const emptyBuckets = (): Record<Rarity, Achievement[]> => ({
  mythic: [],
  legendary: [],
  epic: [],
  rare: [],
  uncommon: [],
  common: []
});

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
  const titles = rarityTitles(t);
  const ranges = rarityRanges(t);

  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const workspaceName = workspaces.find((w) => w.id === workspaceId)?.name;

  const [rarityFilter, setRarityFilter] = useState<Rarity | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<AchievementCategory | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortBy>("rarity");
  const [rulesFor, setRulesFor] = useState<Achievement | null>(null);

  const { data, isLoading, isError } = useQuery({
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
    return Array.from(present).sort();
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

  if (isLoading) return <PageSkeleton />;

  if (isError) {
    return (
      <div className="aqt-player">
        <div className="aqt-card-surface">
          <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
            <AlertTriangle
              className="mb-1 h-10 w-10 text-[color:var(--aqt-rose)]"
              aria-hidden
            />
            <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("common.loadError")}</p>
          </div>
        </div>
      </div>
    );
  }

  const filtersActive = rarityFilter !== null || categoryFilter !== null || search.trim() !== "";

  return (
    <div className="aqt-player space-y-6">
      <AchievementsHero
        workspaceName={workspaceName}
        total={stats.total}
        rarestPct={stats.rarest}
        totalEarned={stats.totalEarned}
        mythicCount={counts.mythic}
      />

      {/* Rarity distribution strip — click a tier to filter to it */}
      <div className="aqt-ach-rank">
        {RARITY_ORDER.map((r) => (
          <div
            key={r}
            role="button"
            tabIndex={0}
            aria-pressed={rarityFilter === r}
            onClick={() => setRarityFilter(rarityFilter === r ? null : r)}
            onKeyDown={activateOnKey(() => setRarityFilter(rarityFilter === r ? null : r))}
            className={cn(
              "aqt-tier cursor-pointer transition-opacity",
              r,
              rarityFilter && rarityFilter !== r && "opacity-40"
            )}
          >
            <span className="aqt-l">{r}</span>
            <span className="aqt-n">{counts[r]}</span>
            <span className="aqt-sub">{ranges[r]}</span>
          </div>
        ))}
      </div>

      {/* Toolbar: rarity + category filters, sort, search */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn("aqt-filter-chip", !filtersActive && "active")}
          onClick={() => {
            setRarityFilter(null);
            setCategoryFilter(null);
            setSearch("");
          }}
          onKeyDown={activateOnKey(() => {
            setRarityFilter(null);
            setCategoryFilter(null);
            setSearch("");
          })}
          role="button"
          tabIndex={0}
        >
          {t("common.all")} <span className="aqt-count">{stats.total}</span>
        </span>

        <span className="aqt-filter-divider" />

        {RARITY_ORDER.map((r) => (
          <span
            key={r}
            className={cn("aqt-filter-chip", rarityFilter === r && "active")}
            onClick={() => setRarityFilter(rarityFilter === r ? null : r)}
            onKeyDown={activateOnKey(() => setRarityFilter(rarityFilter === r ? null : r))}
            role="button"
            tabIndex={0}
          >
            <span className="capitalize">{r}</span>
            <span className="aqt-count">{counts[r]}</span>
          </span>
        ))}

        {categories.length > 0 ? (
          <>
            <span className="aqt-filter-divider" />
            {categories.map((cat) => (
              <span
                key={cat}
                className={cn("aqt-filter-chip", categoryFilter === cat && "active")}
                onClick={() => setCategoryFilter(categoryFilter === cat ? null : cat)}
                onKeyDown={activateOnKey(() =>
                  setCategoryFilter(categoryFilter === cat ? null : cat)
                )}
                role="button"
                tabIndex={0}
              >
                {t(`achievements.category.${cat}`)}
              </span>
            ))}
          </>
        ) : null}

        <div className="ml-auto flex items-center gap-2">
          <span className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">
            {t("achievements.results", { count: visibleCount })}
          </span>
          <Select value={sort} onValueChange={(v) => setSort(v as SortBy)}>
            <SelectTrigger
              title={t("users.achievements.sort.title")}
              className="aqt-mono h-8 w-[150px] border-white/[0.07] bg-white/[0.02] text-[13px] text-white/80 shadow-none hover:border-white/[0.13] hover:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.15] focus:ring-offset-0"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="rarity">{t("users.achievements.sort.rarity")}</SelectItem>
              <SelectItem value="name">{t("users.achievements.sort.name")}</SelectItem>
              <SelectItem value="count">{t("users.achievements.sort.earned")}</SelectItem>
            </SelectContent>
          </Select>
          <div className="relative min-w-[180px]">
            <input
              placeholder={t("achievements.searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] py-1.5 pl-8 pr-3 text-[14px] outline-none focus:border-[color:var(--aqt-border-3)]"
            />
            <Search
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]"
              aria-hidden
            />
          </div>
        </div>
      </div>

      {/* Rarity sections */}
      {visibleCount === 0 ? (
        <div className="aqt-card-surface">
          <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
            <Award className="mb-1 h-10 w-10 text-[color:var(--aqt-fg-faint)]" aria-hidden />
            <h2 className="font-onest text-lg font-semibold text-[color:var(--aqt-fg)]">
              {t("achievements.empty.title")}
            </h2>
            <p className="text-sm text-[color:var(--aqt-fg-dim)]">{t("achievements.empty.body")}</p>
          </div>
        </div>
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
                <span className="aqt-card-sub">
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

export default AchievementsPage;
