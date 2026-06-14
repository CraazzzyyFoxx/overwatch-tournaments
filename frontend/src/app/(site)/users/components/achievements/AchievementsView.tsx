"use client";

import React, { useMemo, useState, useTransition } from "react";
import { Award, Crown, Flame, Gem, Sparkles } from "lucide-react";
import Image from "next/image";
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
import {
  classifyRarity,
  RARITY_ORDER,
  RARITY_RANGE,
  RARITY_TITLES,
  type Rarity
} from "@/app/(site)/users/components/achievements/rarity";
import { AchievementDetailDialog } from "@/app/(site)/users/components/achievements/AchievementDetailDialog";

const TOURNAMENT_QUERY_KEY = "achievementTournamentId";

interface Props {
  achievements: AchievementRarity[];
  tournaments?: UserTournamentSummary[];
  selectedTournamentValue?: string;
}

const AchievementsView = ({ achievements, tournaments = [], selectedTournamentValue = "all" }: Props) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const [rarityFilter, setRarityFilter] = useState<Rarity | null>(null);
  const [lockFilter, setLockFilter] = useState<"all" | "unlocked" | "locked">("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"rarity" | "name" | "count">("rarity");
  const [selected, setSelected] = useState<AchievementRarity | null>(null);

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
      mythic: [],
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
      mythic: grouped.mythic.length,
      legendary: grouped.legendary.length,
      epic: grouped.epic.length,
      rare: grouped.rare.length,
      uncommon: grouped.uncommon.length,
      common: grouped.common.length
    };
  }, [grouped]);

  // An achievement with count === 0 is a not-yet-earned (locked) entry.
  const unlockedCounts = useMemo(() => {
    const f = (list: AchievementRarity[]) => list.filter((a) => a.count > 0).length;
    return {
      mythic: f(grouped.mythic),
      legendary: f(grouped.legendary),
      epic: f(grouped.epic),
      rare: f(grouped.rare),
      uncommon: f(grouped.uncommon),
      common: f(grouped.common)
    };
  }, [grouped]);

  const totalCount = achievements.length;
  const unlockedCount = useMemo(() => achievements.filter((a) => a.count > 0).length, [achievements]);
  const lockedCount = totalCount - unlockedCount;
  const hasLocked = lockedCount > 0;

  const visibleGrouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filteredEntry = (rarity: Rarity): AchievementRarity[] => {
      if (rarityFilter && rarityFilter !== rarity) return [];
      let list = grouped[rarity];
      if (lockFilter === "unlocked") list = list.filter((a) => a.count > 0);
      else if (lockFilter === "locked") list = list.filter((a) => a.count === 0);
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
  }, [grouped, rarityFilter, lockFilter, search, sort]);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {/* Rarity rank */}
      <div className="aqt-ach-rank">
        {RARITY_ORDER.map((r) => (
          <div key={r} className={cn("aqt-tier", r)}>
            <span className="aqt-l">{r}</span>
            <span className="aqt-n">{unlockedCounts[r]}</span>
            <span className="aqt-sub">{RARITY_RANGE[r]}</span>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="aqt-filters">
        <span
          className={cn("aqt-filter-chip", rarityFilter === null && lockFilter === "all" && "active")}
          onClick={() => {
            setRarityFilter(null);
            setLockFilter("all");
          }}
          role="button"
          tabIndex={0}
        >
          All <span className="aqt-count">{totalCount}</span>
        </span>
        {hasLocked ? (
          <>
            <span
              className={cn("aqt-filter-chip", lockFilter === "unlocked" && "active")}
              onClick={() => setLockFilter(lockFilter === "unlocked" ? "all" : "unlocked")}
              role="button"
              tabIndex={0}
            >
              Unlocked <span className="aqt-count">{unlockedCount}</span>
            </span>
            <span
              className={cn("aqt-filter-chip", lockFilter === "locked" && "active")}
              onClick={() => setLockFilter(lockFilter === "locked" ? "all" : "locked")}
              role="button"
              tabIndex={0}
            >
              Locked <span className="aqt-count">{lockedCount}</span>
            </span>
          </>
        ) : null}
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
        <Select value={sort} onValueChange={(v) => setSort(v as "rarity" | "name" | "count")}>
          <SelectTrigger
            title="Sort achievements"
            className="aqt-mono h-8 w-[150px] shadow-none border-white/[0.07] bg-white/[0.02] text-[12px] text-white/80 hover:border-white/[0.13] hover:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.15] focus:ring-offset-0"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="rarity">Sort: Rarity</SelectItem>
            <SelectItem value="name">Sort: Name</SelectItem>
            <SelectItem value="count">Sort: Earned</SelectItem>
          </SelectContent>
        </Select>
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
        const sectionUnlocked = list.filter((a) => a.count > 0).length;
        return (
          <div key={r} className="aqt-card-surface">
            <div className="aqt-card-head">
              <div className="aqt-card-title">
                <span className="aqt-card-title-ic">
                  {r === "mythic" ? <Flame size={15} /> : r === "legendary" ? <Crown size={15} /> : r === "epic" ? <Gem size={15} /> : r === "rare" ? <Sparkles size={15} /> : <Award size={15} />}
                </span>
                <span>{RARITY_TITLES[r]}</span>
              </div>
              <span className="aqt-card-sub">{sectionUnlocked} of {list.length} unlocked</span>
            </div>
            <div className="aqt-card-body">
              <div className="aqt-ach-grid">
                {list.map((ach) => {
                  const imgSrc = ach.image_url ?? `/achievements/${ach.slug}.webp`;
                  const initial = (ach.name ?? "?").slice(0, 1).toUpperCase();
                  const locked = ach.count === 0;
                  return (
                    <button
                      key={ach.id}
                      type="button"
                      onClick={() => setSelected(ach)}
                      className={cn("aqt-ach-card w-full text-left", r, locked && "locked")}
                      style={locked ? { opacity: 0.6, filter: "grayscale(0.5)" } : undefined}
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
                        {locked ? (
                          <span className="aqt-rarity">Locked</span>
                        ) : (
                          <span className="aqt-rarity">◆ <span className="capitalize">{r}</span></span>
                        )}
                        <span className="aqt-mono">{(ach.rarity * 100).toFixed(2)}%</span>
                      </div>
                    </button>
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

      <AchievementDetailDialog achievement={selected} onClose={() => setSelected(null)} />
    </div>
  );
};

export default AchievementsView;
