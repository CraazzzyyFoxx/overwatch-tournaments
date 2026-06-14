"use client";

import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Award, Sparkles, Users, ScrollText } from "lucide-react";
import achievementsService from "@/services/achievements.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import AchievementCard from "@/components/AchievementCard";
import StatisticsCard from "@/components/StatisticsCard";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Achievement, AchievementCategory } from "@/types/achievement.types";
import ConditionTreeView from "@/app/(site)/achievements/components/ConditionTreeView";

const CATEGORY_LABELS: Record<AchievementCategory, string> = {
  overall: "Overall",
  hero: "Hero",
  division: "Division",
  team: "Team",
  standing: "Standing",
  match: "Match",
};

const SCOPE_LABELS: Record<string, string> = {
  global: "Global",
  tournament: "Tournament",
  match: "Match",
};

type CategoryFilter = "all" | AchievementCategory;
type SortBy = "rarity_asc" | "rarity_desc" | "count_desc" | "count_asc" | "name_asc";

const AchievementCardSkeleton = () => (
  <div className="aspect-square rounded-xl border border-white/[0.07] bg-white/[0.02]">
    <Skeleton className="h-full w-full rounded-xl" />
  </div>
);

const PageSkeleton = () => (
  <div className="space-y-8">
    <div className="flex flex-col gap-1">
      <Skeleton className="h-9 w-52" />
      <Skeleton className="h-4 w-80" />
    </div>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-20 rounded-xl" />
      ))}
    </div>
    <div className="flex gap-4">
      <Skeleton className="h-9 w-80" />
      <Skeleton className="h-9 w-44" />
    </div>
    <div className="grid 2xl:grid-cols-5 xl:grid-cols-4 lg:grid-cols-3 sm:grid-cols-2 gap-3">
      {Array.from({ length: 12 }).map((_, i) => (
        <AchievementCardSkeleton key={i} />
      ))}
    </div>
  </div>
);

const AchievementsPage = () => {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [sortBy, setSortBy] = useState<SortBy>("rarity_asc");
  const [ruleDialogAchievement, setRuleDialogAchievement] = useState<Achievement | null>(null);
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const { data, isLoading } = useQuery({
    queryKey: ["achievements", "all", workspaceId],
    queryFn: () => achievementsService.getAll(1, -1, workspaceId),
  });

  const filtered = useMemo(() => {
    const results = data?.results;
    if (!results) return [];

    let items = results;

    if (categoryFilter !== "all") {
      items = items.filter((a) => a.category === categoryFilter);
    }

    const sorted = [...items].sort((a, b) => {
      switch (sortBy) {
        case "rarity_asc":
          return a.rarity - b.rarity;
        case "rarity_desc":
          return b.rarity - a.rarity;
        case "count_desc":
          return (b.count ?? 0) - (a.count ?? 0);
        case "count_asc":
          return (a.count ?? 0) - (b.count ?? 0);
        case "name_asc":
          return a.name.localeCompare(b.name);
        default:
          return 0;
      }
    });

    return sorted;
  }, [data?.results, categoryFilter, sortBy]);

  const stats = useMemo(() => {
    const results = data?.results;
    if (!results) return { total: 0, rarest: 0, avgRarity: 0, totalEarned: 0 };

    const rarestPct = results.length > 0 ? Math.min(...results.map((a) => a.rarity)) * 100 : 0;
    const avgRarity = results.length > 0
      ? (results.reduce((sum, a) => sum + a.rarity, 0) / results.length) * 100
      : 0;
    const totalEarned = results.reduce((sum, a) => sum + (a.count ?? 0), 0);

    return {
      total: results.length,
      rarest: rarestPct,
      avgRarity,
      totalEarned,
    };
  }, [data?.results]);

  const categories = useMemo(() => {
    const results = data?.results;
    if (!results) return new Set<AchievementCategory>();
    return new Set(results.map((a) => a.category).filter(Boolean) as AchievementCategory[]);
  }, [data?.results]);

  if (isLoading) return <PageSkeleton />;

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold leading-none tracking-tight">
          Achievements
        </h1>
        <p className="text-sm text-muted-foreground">
          Browse all achievements, filter by category, and view earning conditions.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatisticsCard
          name="Total Achievements"
          value={stats.total}
          icon={<Award className="h-4 w-4" />}
          iconClassName="bg-indigo-500/10 text-indigo-400"
        />
        <StatisticsCard
          name="Rarest"
          value={`${stats.rarest.toFixed(2)}%`}
          icon={<Sparkles className="h-4 w-4" />}
          iconClassName="bg-amber-500/10 text-amber-400"
        />
        <StatisticsCard
          name="Avg Rarity"
          value={`${stats.avgRarity.toFixed(1)}%`}
          icon={<ScrollText className="h-4 w-4" />}
          iconClassName="bg-purple-500/10 text-purple-400"
        />
        <StatisticsCard
          name="Total Earned"
          value={stats.totalEarned}
          icon={<Users className="h-4 w-4" />}
          iconClassName="bg-emerald-500/10 text-emerald-400"
        />
      </div>

      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center">
        <ToggleGroup
          type="single"
          value={categoryFilter}
          onValueChange={(value) => value && setCategoryFilter(value as CategoryFilter)}
          variant="outline"
        >
          <ToggleGroupItem value="all">All</ToggleGroupItem>
          {Array.from(categories)
            .sort()
            .map((cat) => (
              <ToggleGroupItem key={cat} value={cat}>
                {CATEGORY_LABELS[cat]}
              </ToggleGroupItem>
            ))}
        </ToggleGroup>

        <Select value={sortBy} onValueChange={(value) => setSortBy(value as SortBy)}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Sort by..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="rarity_asc">Rarest First</SelectItem>
            <SelectItem value="rarity_desc">Most Common First</SelectItem>
            <SelectItem value="count_desc">Most Earned</SelectItem>
            <SelectItem value="count_asc">Least Earned</SelectItem>
            <SelectItem value="name_asc">Name A-Z</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Award className="w-16 h-16 text-muted-foreground mb-4" />
          <h2 className="text-xl font-semibold mb-2">No achievements found</h2>
          <p className="text-muted-foreground">
            Try adjusting your filters.
          </p>
        </div>
      ) : (
        <div className="grid 2xl:grid-cols-5 xl:grid-cols-4 lg:grid-cols-3 sm:grid-cols-2 gap-3 w-full">
          {filtered.map((achievement) => (
            <div key={achievement.id} className="relative group/wrapper">
              <AchievementCard
                achievement={achievement}
                href={`/achievements/${achievement.id}`}
                descriptionLocale="ru"
              />
              {achievement.condition_tree && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setRuleDialogAchievement(achievement);
                  }}
                  className="absolute bottom-2 left-2 z-[15] inline-flex cursor-pointer items-center justify-center rounded-full border border-white/[0.12] bg-black/55 p-1.5 text-white/60 backdrop-blur-sm transition-colors hover:bg-black/75 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
                  aria-label={`View rules for ${achievement.name}`}
                >
                  <ScrollText className="h-3.5 w-3.5" aria-hidden />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <Dialog
        open={!!ruleDialogAchievement}
        onOpenChange={(open) => !open && setRuleDialogAchievement(null)}
      >
        {ruleDialogAchievement && (
          <DialogContent className="gap-0 border-white/[0.07] p-5 sm:max-w-lg max-h-[80vh] overflow-y-auto">
            <DialogHeader className="mb-4">
              <DialogTitle className="text-base font-semibold leading-snug text-white">
                {ruleDialogAchievement.name}
              </DialogTitle>
              <DialogDescription className="text-sm leading-relaxed text-white/55">
                {ruleDialogAchievement.description_ru}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap gap-2">
                {ruleDialogAchievement.category && (
                  <span className="rounded-full border border-white/[0.1] bg-white/[0.04] px-2.5 py-0.5 text-xs text-white/60">
                    {CATEGORY_LABELS[ruleDialogAchievement.category]}
                  </span>
                )}
                {ruleDialogAchievement.scope && (
                  <span className="rounded-full border border-white/[0.1] bg-white/[0.04] px-2.5 py-0.5 text-xs text-white/60">
                    {SCOPE_LABELS[ruleDialogAchievement.scope] ?? ruleDialogAchievement.scope}
                  </span>
                )}
                <span className="rounded-full border border-white/[0.1] bg-white/[0.04] px-2.5 py-0.5 text-xs text-white/60">
                  {(ruleDialogAchievement.rarity * 100).toFixed(2)}% rarity
                </span>
              </div>

              <div className="flex flex-col gap-2">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-white/35">
                  Conditions
                </div>
                <div className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                  {ruleDialogAchievement.condition_tree ? (
                    <ConditionTreeView tree={ruleDialogAchievement.condition_tree} />
                  ) : (
                    <span className="text-xs text-white/30">No conditions defined</span>
                  )}
                </div>
              </div>
            </div>
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
};

export default AchievementsPage;
