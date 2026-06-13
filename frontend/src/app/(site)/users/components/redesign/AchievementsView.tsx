"use client";

import React, { useMemo, useState, useTransition } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { AchievementRarity } from "@/types/achievement.types";
import type { UserTournamentSummary } from "@/types/user.types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

const TOURNAMENT_QUERY_KEY = "achievementTournamentId";

interface Props {
  achievements: AchievementRarity[];
  tournaments?: UserTournamentSummary[];
  selectedTournamentValue?: string;
}

type Rarity = "legendary" | "epic" | "rare" | "uncommon" | "common";

const classifyRarity = (rarityPercent: number): Rarity => {
  if (rarityPercent < 5) return "legendary";
  if (rarityPercent < 15) return "epic";
  if (rarityPercent < 30) return "rare";
  if (rarityPercent < 50) return "uncommon";
  return "common";
};

const RARITY_ORDER: Rarity[] = ["legendary", "epic", "rare", "uncommon", "common"];

const RARITY_TITLES: Record<Rarity, string> = {
  legendary: "Legendary · < 5% of all players",
  epic: "Epic · 5-15%",
  rare: "Rare · 15-30%",
  uncommon: "Uncommon · 30-50%",
  common: "Common · > 50%"
};

const RARITY_RANGE: Record<Rarity, string> = {
  legendary: "< 5% earn",
  epic: "5-15%",
  rare: "15-30%",
  uncommon: "30-50%",
  common: "> 50%"
};

const AchievementsView = ({ achievements, tournaments = [], selectedTournamentValue = "all" }: Props) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const [rarityFilter, setRarityFilter] = useState<Rarity | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"rarity" | "name" | "count">("rarity");

  const uniqueTournaments = useMemo(() => {
    const seen = new Set<number>();
    return tournaments.filter((t) => {
      if (seen.has(t.id)) return false;
      seen.add(t.id);
      return true;
    });
  }, [tournaments]);

  const onTournamentChange = (value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    if (value === "all") {
      next.delete(TOURNAMENT_QUERY_KEY);
    } else {
      next.set(TOURNAMENT_QUERY_KEY, value);
    }
    startTransition(() => {
      router.push(`${pathname}?${next.toString()}`);
    });
  };

  const grouped = useMemo(() => {
    const buckets: Record<Rarity, AchievementRarity[]> = {
      legendary: [],
      epic: [],
      rare: [],
      uncommon: [],
      common: []
    };
    for (const ach of achievements) {
      const rarity = classifyRarity(ach.rarity * 100);
      buckets[rarity].push(ach);
    }
    return buckets;
  }, [achievements]);

  const counts = useMemo(() => {
    return {
      legendary: grouped.legendary.length,
      epic: grouped.epic.length,
      rare: grouped.rare.length,
      uncommon: grouped.uncommon.length,
      common: grouped.common.length
    };
  }, [grouped]);

  const totalUnlocked = achievements.length;

  const visibleGrouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filteredEntry = (rarity: Rarity): AchievementRarity[] => {
      if (rarityFilter && rarityFilter !== rarity) return [];
      let list = grouped[rarity];
      if (q) {
        list = list.filter((a) =>
          (a.name?.toLowerCase().includes(q)) ||
          (a.description_en?.toLowerCase().includes(q)) ||
          (a.description_ru?.toLowerCase().includes(q))
        );
      }
      const sorted = [...list].sort((a, b) => {
        if (sort === "name") return (a.name ?? "").localeCompare(b.name ?? "");
        if (sort === "count") return b.count - a.count;
        return a.rarity - b.rarity; // rarest first
      });
      return sorted;
    };
    return Object.fromEntries(RARITY_ORDER.map((r) => [r, filteredEntry(r)])) as Record<Rarity, AchievementRarity[]>;
  }, [grouped, rarityFilter, search, sort]);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {/* Rarity rank */}
      <div className="aqt-ach-rank">
        {RARITY_ORDER.map((r) => (
          <div key={r} className={cn("aqt-tier", r)}>
            <span className="aqt-l">{r}</span>
            <span className="aqt-n">{counts[r]}</span>
            <span className="aqt-sub">{RARITY_RANGE[r]}</span>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="aqt-filters">
        <span
          className={cn("aqt-filter-chip", rarityFilter === null && "active")}
          onClick={() => setRarityFilter(null)}
          role="button"
          tabIndex={0}
        >
          All <span className="aqt-count">{totalUnlocked}</span>
        </span>
        <span className="aqt-filter-divider" />
        {RARITY_ORDER.map((r) => (
          <span
            key={r}
            className={cn("aqt-filter-chip", rarityFilter === r && "active")}
            onClick={() => setRarityFilter(rarityFilter === r ? null : r)}
            role="button"
            tabIndex={0}
          >
            <span className="capitalize">{r}</span>
            <span className="aqt-count">{counts[r]}</span>
          </span>
        ))}
        <span className="aqt-filter-divider" />
        {uniqueTournaments.length > 0 && (
          <Select value={selectedTournamentValue} onValueChange={onTournamentChange}>
            <SelectTrigger className="h-8 w-48 border-white/[0.07] bg-white/[0.02] text-[13px] text-white/80 shadow-none hover:border-white/[0.13] hover:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.15] focus:ring-offset-0">
              <SelectValue placeholder="All tournaments" />
            </SelectTrigger>
            <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
              <SelectItem value="all">All tournaments</SelectItem>
              <SelectItem value="none">Without tournament</SelectItem>
              {uniqueTournaments.map((t) => (
                <SelectItem key={t.id} value={`t-${t.id}`}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as "rarity" | "name" | "count")}
          title="Sort achievements"
          className="aqt-mono cursor-pointer rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-2.5 py-1.5 text-[12px] text-[color:var(--aqt-fg)] outline-none"
        >
          <option value="rarity" className="bg-[#10151c]">Sort: Rarity</option>
          <option value="name" className="bg-[#10151c]">Sort: Name</option>
          <option value="count" className="bg-[#10151c]">Sort: Earned</option>
        </select>
        <div className="filter-search relative ml-auto min-w-[200px] max-w-[300px] flex-1">
          <input
            placeholder="Search achievements…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-1.5 pl-8 text-[13px] outline-none"
          />
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        </div>
      </div>

      {/* Sections per rarity */}
      {RARITY_ORDER.map((r) => {
        const list = visibleGrouped[r];
        if (list.length === 0) return null;
        return (
          <div key={r} className="aqt-card-surface">
            <div className="aqt-card-head">
              <div className="aqt-card-title">
                <span className="aqt-card-title-ic">{r === "legendary" ? "★" : r === "epic" ? "▲" : r === "rare" ? "◆" : "●"}</span>
                <span>{RARITY_TITLES[r]}</span>
              </div>
              <span className="aqt-card-sub">{list.length} unlocked</span>
            </div>
            <div className="aqt-card-body">
              <div className="aqt-ach-grid">
                {list.map((ach) => {
                  const imgSrc = ach.image_url ?? `/achievements/${ach.slug}.webp`;
                  const initial = (ach.name ?? "?").slice(0, 1).toUpperCase();
                  return (
                    <Link
                      key={ach.id}
                      href={`/achievements/${ach.id}`}
                      className={cn("aqt-ach-card", r)}
                    >
                      {ach.count > 0 ? (
                        <span className="aqt-stamp x">×{ach.count}</span>
                      ) : null}
                      <div className="flex items-start gap-2.5">
                        <div className="aqt-ic-circle relative">
                          {imgSrc ? (
                            <Image
                              src={imgSrc}
                              alt={ach.name}
                              fill
                              sizes="48px"
                              className="object-cover"
                            />
                          ) : (
                            <span className="relative z-[1]">{initial}</span>
                          )}
                        </div>
                        <div className="flex min-w-0 flex-col gap-0.5">
                          <div className="text-[13.5px] font-semibold leading-tight">{ach.name}</div>
                          <div className="text-[11px] leading-snug text-[color:var(--aqt-fg-dim)]">
                            {ach.description_ru || ach.description_en}
                          </div>
                        </div>
                      </div>
                      <div className="mt-auto flex items-center justify-between border-t border-[color:var(--aqt-border)] pt-2 text-[10.5px] text-[color:var(--aqt-fg-muted)]">
                        <span className="aqt-rarity">◆ <span className="capitalize">{r}</span></span>
                        <span className="aqt-mono">{(ach.rarity * 100).toFixed(2)}%</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}

      {achievements.length === 0 ? (
        <div className="aqt-card-surface">
          <div className="aqt-card-body text-center text-[color:var(--aqt-fg-dim)]">
            У пользователя пока нет достижений.
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default AchievementsView;
