"use client";

import { useMemo, useState, useTransition, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { AchievementRarity } from "@/types/achievement.types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { classifyRarity, localizedText, RARITY_ORDER, rarityVarClass, type Rarity } from "@/lib/achievements/rarity";
import { AchievementDetailDialog } from "@/app/(site)/users/components/achievements/AchievementDetailDialog";
import { AchievementArt } from "@/components/achievements/AchievementArt";
import { RarityStrip } from "@/components/achievements/RarityStrip";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { PageStateCard } from "@/components/ui/page-state-card";
import { RowButton } from "@/components/ui/row-button";
import { Separator } from "@/components/ui/separator";
import { CardSurface } from "@/components/profile/atoms";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import { GameIcon } from "@/components/workspace/GameIcon";

const TOURNAMENT_QUERY_KEY = "achievementTournamentId";

interface Props {
  achievements: AchievementRarity[];
  tournaments?: readonly { id: number; name: string }[];
  /** Tournament id; `"none"` = earned outside any tournament; `undefined` = all. */
  selectedTournament?: number | "none";
  /** "All games": every tile marks its rule's game. */
  showGames?: boolean;
}

const AchievementsView = ({ achievements, tournaments = [], selectedTournament, showGames = false }: Props) => {
  const tr = useTranslations();
  const locale = useLocale();
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

  const onTournamentChange = (value: number | "none" | undefined) => {
    const next = new URLSearchParams(searchParams.toString());
    if (value === undefined) {
      next.delete(TOURNAMENT_QUERY_KEY);
    } else {
      next.set(TOURNAMENT_QUERY_KEY, value === "none" ? value : `t-${value}`);
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
      <RarityStrip
        values={
          Object.fromEntries(
            RARITY_ORDER.map((r) => [
              r,
              <>
                {unlockedCounts[r]}
                <span className="text-caption font-semibold text-[color:var(--aqt-fg-faint)]"> / {counts[r]}</span>
              </>
            ])
          ) as Record<Rarity, ReactNode>
        }
        active={rarityFilter}
        onToggle={setRarityFilter}
      />

      {/* Filters */}
      <FilterChipGroup label={tr("common.filters")}>
        <FilterChip active={effectiveLock === "all"} count={totalCount} onClick={() => setLockFilter("all")}>
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
        <Separator orientation="vertical" className="mx-0.5 h-5" />
        {tournaments.length > 0 && (
          <div className="w-48">
            <TournamentCombobox
              tournaments={tournaments}
              value={selectedTournament}
              onValueChange={onTournamentChange}
              extraOptions={[{ value: "none", label: tr("users.achievements.filter.withoutTournament") }]}
              size="sm"
              variant="surface"
            />
          </div>
        )}
        <Select value={sort} onValueChange={(v) => setSort(v as "rarity" | "name" | "count")}>
          <SelectTrigger
            title={tr("users.achievements.sort.title")}
            size="sm"
            variant="surface"
            className="aqt-tnum w-auto min-w-[150px] gap-2"
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
            className={rarityVarClass(r)}
            title={tierNames[r]}
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
                const locked = ach.count === 0;
                return (
                  <RowButton
                    key={ach.id}
                    onClick={() => setSelected(ach)}
                    className="-m-2 flex w-auto items-start gap-3 rounded-lg p-2"
                  >
                    <AchievementArt
                      achievement={ach}
                      sizes="48px"
                      className="size-12 shrink-0 rounded-[11px]"
                      imgClassName={cn(locked && "opacity-45 grayscale")}
                    />
                    <div className="flex min-w-0 flex-col gap-1">
                      <div
                        className={cn(
                          "flex min-w-0 items-center gap-1.5 text-body font-semibold leading-tight",
                          locked ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
                        )}
                      >
                        {showGames ? <GameIcon slug={ach.discipline} /> : null}
                        <span className="truncate">{ach.name}</span>
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
                          <span className="text-[hsl(var(--rar))]">{tierNames[r]}</span>
                        )}
                        <span className="aqt-tnum">{(ach.rarity * 100).toFixed(2)}%</span>
                        {ach.count > 0 ? <span className="aqt-tnum">×{ach.count}</span> : null}
                      </div>
                    </div>
                  </RowButton>
                );
              })}
            </div>
          </CardSurface>
        );
      })}

      {visibleTotal === 0 ? (
        achievements.length === 0 ? (
          <PageStateCard state="empty" description={tr("users.achievements.emptyState")} />
        ) : (
          <PageStateCard
            state="filtered-empty"
            onAction={() => {
              setRarityFilter(null);
              setLockFilter("all");
              setSearch("");
            }}
          />
        )
      ) : null}

      <AchievementDetailDialog achievement={selected} onClose={() => setSelected(null)} />
    </div>
  );
};

export default AchievementsView;
