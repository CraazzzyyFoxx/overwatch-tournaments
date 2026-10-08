"use client";

import { useMemo, useState, useTransition } from "react";
import Image from "next/image";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
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
  localizedText,
  RARITY_ORDER,
  rarityRanges,
  rarityVarClass,
  type Rarity
} from "@/app/(site)/users/components/achievements/rarity";
import { AchievementDetailDialog } from "@/app/(site)/users/components/achievements/AchievementDetailDialog";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { CardSurface, ProfileStat } from "@/app/(site)/users/components/shared/atoms";

const TOURNAMENT_QUERY_KEY = "achievementTournamentId";

interface Props {
  achievements: AchievementRarity[];
  tournaments?: UserTournamentSummary[];
  selectedTournamentValue?: string;
}

const AchievementsView = ({ achievements, tournaments = [], selectedTournamentValue = "all" }: Props) => {
  const tr = useTranslations();
  const locale = useLocale();
  const ranges = rarityRanges(tr);
  const tierNames = useMemo(
    () =>
      Object.fromEntries(RARITY_ORDER.map((r) => [r, tr(`achievements.rarityName.${r}`)])) as Record<
        Rarity,
        string
      >,
    [tr]
  );

  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const [rarityFilter, setRarityFilter] = useState<Rarity | null>(null);
  // Opening the tab shows what the player earned; locked entries stay one chip away.
  const [lockFilter, setLockFilter] = useState<"all" | "unlocked" | "locked">("unlocked");
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
  // Without any locked entry the Unlocked/Locked chips are not rendered, so the
  // default "unlocked" state must read as "all" — otherwise no chip looks active.
  const effectiveLock = hasLocked ? lockFilter : "all";

  const visibleGrouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filteredEntry = (rarity: Rarity): AchievementRarity[] => {
      if (rarityFilter && rarityFilter !== rarity) return [];
      let list = grouped[rarity];
      if (effectiveLock === "unlocked") list = list.filter((a) => a.count > 0);
      else if (effectiveLock === "locked") list = list.filter((a) => a.count === 0);
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
  }, [grouped, rarityFilter, effectiveLock, search, sort]);

  const visibleTotal = RARITY_ORDER.reduce((n, r) => n + visibleGrouped[r].length, 0);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {/* Rarity rank — unlocked per tier, rarity hue on the label only. */}
      <CardSurface>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
          {RARITY_ORDER.map((r) => (
            <ProfileStat
              key={r}
              size="md"
              title={tierNames[r]}
              label={<span className={cn(rarityVarClass(r), "aqt-rar-fg")}>{tierNames[r]}</span>}
              value={unlockedCounts[r]}
              sub={ranges[r]}
            />
          ))}
        </div>
      </CardSurface>

      {/* Filters */}
      <FilterChipGroup label={tr("common.filters")}>
        <FilterChip
          active={rarityFilter === null && effectiveLock === "all"}
          count={totalCount}
          onClick={() => {
            setRarityFilter(null);
            setLockFilter("all");
          }}
        >
          {tr("common.all")}
        </FilterChip>
        {hasLocked ? (
          <>
            <FilterChip
              active={effectiveLock === "unlocked"}
              count={unlockedCount}
              onClick={() => setLockFilter(lockFilter === "unlocked" ? "all" : "unlocked")}
            >
              {tr("users.achievements.unlocked")}
            </FilterChip>
            <FilterChip
              active={effectiveLock === "locked"}
              count={lockedCount}
              onClick={() => setLockFilter(lockFilter === "locked" ? "all" : "locked")}
            >
              {tr("users.achievements.locked")}
            </FilterChip>
          </>
        ) : null}
        <span aria-hidden className="aqt-filter-divider" />
        {RARITY_ORDER.map((r) => (
          <FilterChip
            key={r}
            active={rarityFilter === r}
            count={counts[r]}
            onClick={() => setRarityFilter(rarityFilter === r ? null : r)}
          >
            <span className="capitalize">{r}</span>
          </FilterChip>
        ))}
        <span aria-hidden className="aqt-filter-divider" />
        {uniqueTournaments.length > 0 && (
          <Select value={selectedTournamentValue} onValueChange={onTournamentChange}>
            <SelectTrigger className="h-8 w-48 border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-body text-[color:var(--aqt-fg-muted)] shadow-none hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)] focus:ring-1 focus:ring-[color:var(--aqt-teal)] focus:ring-offset-0">
              <SelectValue placeholder={tr("users.achievements.filter.allTournaments")} />
            </SelectTrigger>
            <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
              <SelectItem value="all">{tr("users.achievements.filter.allTournaments")}</SelectItem>
              <SelectItem value="none">{tr("users.achievements.filter.withoutTournament")}</SelectItem>
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
            title={tr("users.achievements.sort.title")}
            className="aqt-tnum h-8 w-[150px] shadow-none border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-caption text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)] focus:ring-1 focus:ring-[color:var(--aqt-teal)] focus:ring-offset-0"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="rarity">{tr("users.achievements.sort.rarity")}</SelectItem>
            <SelectItem value="name">{tr("users.achievements.sort.name")}</SelectItem>
            <SelectItem value="count">{tr("users.achievements.sort.earned")}</SelectItem>
          </SelectContent>
        </Select>
        <SearchField
          label={tr("users.achievements.searchLabel")}
          placeholder={tr("users.achievements.searchPlaceholder")}
          value={search}
          onValueChange={setSearch}
          containerClassName="ml-auto min-w-[200px] max-w-[300px] flex-1"
        />
      </FilterChipGroup>

      {/* Sections per rarity */}
      {RARITY_ORDER.map((r) => {
        const list = visibleGrouped[r];
        if (list.length === 0) return null;
        return (
          <CardSurface
            key={r}
            title={tierNames[r]}
            subtitle={ranges[r]}
            action={
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {/* Tier totals, not the filtered list: under the default
                    Unlocked filter `list` holds only earned entries, which
                    turned "1 of 19 unlocked" into "1 of 1". */}
                {tr("users.achievements.sectionUnlocked", {
                  unlocked: String(unlockedCounts[r]),
                  total: String(counts[r])
                })}
              </span>
            }
          >
            <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((ach) => {
                const imgSrc = ach.image_url ?? `/achievements/${ach.slug}.webp`;
                const locked = ach.count === 0;
                return (
                  <button
                    key={ach.id}
                    type="button"
                    onClick={() => setSelected(ach)}
                    className="-m-2 flex items-start gap-3 rounded-lg p-2 text-left transition-colors hover:bg-[hsl(0_0%_100%/0.03)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--aqt-teal)]"
                  >
                    <div className="relative size-12 shrink-0 overflow-hidden rounded-[11px]">
                      <Image
                        src={imgSrc}
                        alt={ach.name}
                        fill
                        sizes="48px"
                        className={cn("object-cover", locked && "opacity-45 grayscale")}
                      />
                    </div>
                    <div className="flex min-w-0 flex-col gap-1">
                      <div
                        className={cn(
                          "truncate text-body font-semibold leading-tight",
                          locked ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
                        )}
                      >
                        {ach.name}
                      </div>
                      <div
                        className={cn(
                          "text-label leading-snug",
                          locked ? "text-[color:var(--aqt-fg-faint)]" : "text-[color:var(--aqt-fg-dim)]"
                        )}
                      >
                        {localizedText(locale, ach.description_ru, ach.description_en)}
                      </div>
                      <div className="flex items-center gap-2 text-label text-[color:var(--aqt-fg-muted)]">
                        {locked ? (
                          <span className="text-[color:var(--aqt-fg-faint)]">
                            {tr("users.achievements.locked")}
                          </span>
                        ) : (
                          <span className={cn(rarityVarClass(r), "aqt-rar-fg")}>{tierNames[r]}</span>
                        )}
                        <span className="aqt-tnum">{(ach.rarity * 100).toFixed(2)}%</span>
                        {ach.count > 0 ? <span className="aqt-tnum">×{ach.count}</span> : null}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </CardSurface>
        );
      })}

      {visibleTotal === 0 ? (
        <CardSurface bodyClassName="text-center text-[color:var(--aqt-fg-dim)]">
          {achievements.length === 0
            ? tr("users.achievements.emptyState")
            : tr("common.pageState.filteredEmpty.description")}
        </CardSurface>
      ) : null}

      <AchievementDetailDialog achievement={selected} onClose={() => setSelected(null)} />
    </div>
  );
};

export default AchievementsView;
