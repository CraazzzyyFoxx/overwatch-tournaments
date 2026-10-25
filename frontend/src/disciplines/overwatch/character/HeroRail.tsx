"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { CardSurface } from "@/components/profile/atoms";
import { formatSeconds } from "@/lib/format";
import { formatStatValue, type NumberFormatter } from "./utils";
import { useHeroClass } from "./classes";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import { RowButton } from "@/components/ui/row-button";

export interface HeroRow {
  id: number;
  hero: CatalogEntityRead;
  role: string | undefined;
  playtime: number;
  share: number;
  winratePct: number | null;
  kda: number | null;
  dmg10: number | null;
  /** Share of comparable stats where the player beats the global average (0..1). */
  impact: number;
}

type SortKey = "playtime" | "winratePct" | "kda" | "dmg10" | "impact";

const SORT_OPTIONS: SortKey[] = ["playtime", "winratePct", "kda", "dmg10", "impact"];
const num = (v: number | null) => (v == null || !Number.isFinite(v) ? -Infinity : v);

const metricValue = (format: NumberFormatter, key: SortKey, r: HeroRow): string => {
  switch (key) {
    case "playtime":
      return formatSeconds(r.playtime);
    case "winratePct":
      return r.winratePct == null ? "—" : `${r.winratePct.toFixed(0)}%`;
    case "kda":
      return r.kda == null ? "—" : r.kda.toFixed(2);
    case "dmg10":
      return r.dmg10 == null ? "—" : formatStatValue(format, "dmg", r.dmg10);
    case "impact":
      return `${Math.round(r.impact * 100)}`;
  }
};

interface Props {
  rows: HeroRow[];
  selectedId: number;
  onSelect: (id: number) => void;
  metadata: DisciplineMetadata;
}

/** Sticky, sortable hero rail beside the hero's detail from `xl` up: ranks every tracked hero by the chosen metric
 *  (so cross-hero comparison stays possible) and switches heroes without a scroll. Narrower screens pick the hero
 *  from the tab's toolbar instead. */
const HeroRail = ({ rows, selectedId, onSelect, metadata }: Props) => {
  const t = useTranslations();
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  const [sort, setSort] = useState<SortKey>("playtime");
  // `null` = every class; otherwise one of the game's declared character classes.
  const [role, setRole] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const sortLabel = (key: SortKey): string => {
    switch (key) {
      case "playtime":
        return t("users.heroes.sort.playtime");
      case "winratePct":
        return t("users.heroes.sort.winrate");
      case "kda":
        return t("users.heroes.sort.kda");
      case "dmg10":
        return t("users.heroes.sort.dmg10");
      case "impact":
        return t("users.heroes.sort.impact");
    }
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let filtered = role === null ? rows : rows.filter((r) => r.role === role);
    if (q) filtered = filtered.filter((r) => r.hero.name.toLowerCase().includes(q));
    return [...filtered].sort((a, b) => num(b[sort]) - num(a[sort]));
  }, [rows, role, query, sort]);

  return (
    <CardSurface
      flush
      title={t("users.heroes.yourHeroes")}
      subtitle={t("users.heroes.tracked", { count: rows.length })}
      className="hidden xl:sticky xl:top-[var(--aqt-sticky-top)] xl:z-30 xl:block"
    >
      <div className="flex flex-col gap-2 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
        <FilterChipGroup label={t("common.filters")}>
          <FilterChip active={role === null} onClick={() => setRole(null)}>
            {t("common.all")}
          </FilterChip>
          {metadata.discipline.character_classes.map((cls) => (
            <FilterChip key={cls} active={role === cls} onClick={() => setRole(cls)}>
              {heroClass.label(cls)}
            </FilterChip>
          ))}
        </FilterChipGroup>
        <div className="flex items-center gap-2">
          <SearchField
            label={t("users.heroes.searchHeroes")}
            placeholder={t("common.search")}
            value={query}
            onValueChange={setQuery}
            containerClassName="flex-1"
          />
          <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
            <SelectTrigger
              aria-label={t("users.heroes.sortHeroes")}
              size="sm"
              className="aqt-tnum w-[116px] shrink-0 border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] text-[color:var(--aqt-fg)] shadow-none"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((o) => (
                <SelectItem key={o} value={o}>
                  {sortLabel(o)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="max-h-[calc(100vh-200px)] overflow-y-auto">
        {visible.map((r) => {
          const active = r.id === selectedId;
          return (
            <RowButton
              key={r.id}
              aria-current={active || undefined}
              onClick={() => onSelect(r.id)}
              className={cn(
                "grid grid-cols-[36px_1fr_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3 py-2.5",
                active &&
                  "border-l-2 border-l-[color:var(--aqt-teal)] pl-[10px] aria-[current=true]:bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,transparent)]"
              )}
            >
              <CatalogEntityImage entity={r.hero} size="md" />
              <div className="min-w-0">
                <div className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">{r.hero.name}</div>
                <div className="flex min-w-0 items-center gap-2 text-label text-[color:var(--aqt-fg-dim)]">
                  <span className="truncate">{heroClass.label(r.role)}</span>
                  {r.winratePct == null ? null : (
                    <span className="aqt-tnum shrink-0">
                      {t("users.heroes.wr", { value: `${r.winratePct.toFixed(0)}%` })}
                    </span>
                  )}
                  <span
                    className="aqt-tnum shrink-0"
                    title={t("users.heroes.poolShare", { pct: (r.share * 100).toFixed(0) })}
                  >
                    {(r.share * 100).toFixed(0)}%
                  </span>
                </div>
                <div
                  className="mt-1 h-1 w-full overflow-hidden rounded-sm bg-[hsl(0_0%_100%/0.05)]"
                  title={t("users.heroes.sort.impact")}
                >
                  <div
                    className="h-full rounded-sm bg-[color:var(--aqt-fg-faint)]"
                    style={{ width: `${Math.round(r.impact * 100)}%` }}
                  />
                </div>
              </div>
              <span className="aqt-tnum text-right text-body font-bold text-[color:var(--aqt-fg)]">
                {metricValue(format, sort, r)}
              </span>
            </RowButton>
          );
        })}
        {visible.length === 0 ? (
          <div className="px-3 py-8 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noHeroes")}</div>
        ) : null}
      </div>
    </CardSurface>
  );
};

export default HeroRail;
