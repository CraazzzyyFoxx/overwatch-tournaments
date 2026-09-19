"use client";

import { useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import HeroImage from "@/components/hero/HeroImage";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { normalizeRole, type AqtRoleKey } from "@/lib/player-role";
import {
  formatSeconds,
  formatStatValue,
  type NumberFormatter
} from "@/app/(site)/users/components/heroes/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";

export interface HeroRow {
  id: number;
  hero: Hero;
  role: string;
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

const ROLE_FILTERS: ("all" | AqtRoleKey)[] = ["all", "tank", "damage", "support"];

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
}

/** Sticky, sortable hero rail. Left column of the Heroes tab: ranks every
 *  tracked hero by the chosen metric (so cross-hero comparison stays possible)
 *  while keeping the detail panel beside it — switching heroes needs no scroll. */
const HeroRail = ({ rows, selectedId, onSelect }: Props) => {
  const t = useTranslations();
  const format = useFormatter();
  const [sort, setSort] = useState<SortKey>("playtime");
  const [role, setRole] = useState<"all" | AqtRoleKey>("all");
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

  const roleLabel = (key: "all" | AqtRoleKey): string => {
    switch (key) {
      case "all":
        return t("common.all");
      case "tank":
        return t("common.roles.tank");
      case "damage":
        return t("common.roles.damage");
      case "support":
        return t("common.roles.support");
    }
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let filtered = role === "all" ? rows : rows.filter((r) => normalizeRole(r.role) === role);
    if (q) filtered = filtered.filter((r) => r.hero.name.toLowerCase().includes(q));
    return [...filtered].sort((a, b) => num(b[sort]) - num(a[sort]));
  }, [rows, role, query, sort]);

  return (
    <CardSurface
      flush
      title={t("users.heroes.yourHeroes")}
      subtitle={t("users.heroes.tracked", { count: rows.length })}
      className="xl:sticky xl:top-[var(--aqt-sticky-top)] xl:z-30"
    >
      <div className="flex flex-col gap-2 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
        <FilterChipGroup label={t("common.filters")}>
          {ROLE_FILTERS.map((rf) => (
            <FilterChip key={rf} active={role === rf} onClick={() => setRole(rf)}>
              {roleLabel(rf)}
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
              className="aqt-tnum h-9 w-[116px] shrink-0 border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] text-label text-[color:var(--aqt-fg)] shadow-none"
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
            <button
              key={r.id}
              type="button"
              onClick={() => onSelect(r.id)}
              className={cn(
                "grid w-full grid-cols-[36px_1fr_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-left transition-colors hover:bg-[hsl(0_0%_100%/0.025)]",
                active && "border-l-2 border-l-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,transparent)] pl-[10px]"
              )}
            >
              <HeroImage hero={r.hero} size="md" />
              <div className="min-w-0">
                <div className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">{r.hero.name}</div>
                <div className="truncate text-label capitalize text-[color:var(--aqt-fg-dim)]">
                  {r.role} · {t("users.heroes.wr", { value: r.winratePct == null ? "—" : `${r.winratePct.toFixed(0)}%` })} · {(r.share * 100).toFixed(0)}%
                </div>
                <div className="mt-1 h-1 w-full overflow-hidden rounded-sm bg-[hsl(0_0%_100%/0.05)]">
                  <div
                    className="h-full rounded-sm"
                    style={{
                      width: `${Math.round(r.impact * 100)}%`,
                      background:
                        r.impact >= 0.6 ? "var(--aqt-emerald)" : r.impact >= 0.4 ? "var(--aqt-amber)" : "var(--aqt-rose)"
                    }}
                  />
                </div>
              </div>
              <span className="aqt-tnum text-right text-body font-bold text-[color:var(--aqt-fg)]">
                {metricValue(format, sort, r)}
              </span>
            </button>
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
