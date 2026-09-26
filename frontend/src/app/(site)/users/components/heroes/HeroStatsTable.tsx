"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { ArrowDown, Crown } from "lucide-react";
import { cn } from "@/lib/utils";
import { LogStatsName } from "@/types/stats.types";
import { formatDelta, formatStatValue } from "@/app/(site)/users/components/heroes/utils";
import { SearchField } from "@/components/ui/search-field";

export type StatSortKey = "delta" | "overall" | "avg10" | "name";

interface AllStatsRow {
  name: LogStatsName;
  label: string;
  overall: number;
  bestYou: number | undefined;
  avg10: number;
  delta: number | null;
  bestAll: number | null;
  global10: number;
  isRecord: boolean;
}

const HeroStatsTable = ({
  rows,
  sort,
  onSortChange,
  search,
  onSearchChange
}: {
  rows: AllStatsRow[];
  sort: StatSortKey;
  onSortChange: (key: StatSortKey) => void;
  search: string;
  onSearchChange: (value: string) => void;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  // Plain render helper (not a component) to avoid recreating a component during render.
  // `srLabel` names the column for assistive tech when the visible header is a
  // bare symbol (the Δ column) that reads as nonsense on its own.
  const sortTh = (label: string, k: StatSortKey, align: "left" | "right" = "right", srLabel?: string) => (
    <th
      scope="col"
      aria-sort={sort === k ? "descending" : "none"}
      className={cn(
        "border-b border-[color:var(--aqt-border)] px-3 py-2.5",
        align === "right" ? "text-right" : "text-left"
      )}
    >
      <button
        type="button"
        onClick={() => onSortChange(k)}
        className={cn(
          "aqt-tnum inline-flex select-none items-center gap-1 rounded-sm text-label font-bold uppercase tracking-label outline-none transition-colors",
          "focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
          sort === k ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)] hover:text-[color:var(--aqt-fg-muted)]"
        )}
      >
        {srLabel ? (
          <>
            <span aria-hidden>{label}</span>
            <span className="sr-only">{srLabel}</span>
          </>
        ) : (
          label
        )}
        {sort === k ? <ArrowDown aria-hidden className="h-3 w-3" /> : null}
      </button>
    </th>
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SearchField
          label={t("users.heroes.searchStats")}
          placeholder={t("users.heroes.searchStats")}
          value={search}
          onValueChange={onSearchChange}
          containerClassName="min-w-[180px] max-w-[280px] flex-1"
        />
        <span className="aqt-tnum inline-flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-faint)]">
          <Crown aria-hidden className="h-3 w-3 text-[color:var(--aqt-amber)]" />
          {t("users.heroes.recordTitle")}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="aqt-tnum w-full border-collapse text-caption">
          <thead>
            <tr>
              {sortTh(t("users.heroes.col.stat"), "name", "left")}
              {sortTh(t("users.heroes.col.overall"), "overall")}
              <th scope="col" className="aqt-tnum border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">{t("users.heroes.col.bestYou")}</th>
              {sortTh(t("users.heroes.col.avg10"), "avg10")}
              {sortTh("Δ", "delta", "right", t("users.heroes.col.delta"))}
              <th scope="col" className="aqt-tnum border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">{t("users.heroes.col.bestAll")}</th>
              <th scope="col" className="aqt-tnum border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">{t("users.heroes.col.global10")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                <td className="px-3 py-2 text-left font-medium text-[color:var(--aqt-fg)]">
                  {r.label}
                  {r.isRecord ? (
                    <Crown
                      role="img"
                      aria-label={t("users.heroes.recordTitle")}
                      className="ml-1.5 inline h-3 w-3 text-[color:var(--aqt-amber)]"
                    />
                  ) : null}
                </td>
                <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{formatStatValue(format, r.name, r.overall)}</td>
                <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                  {r.bestYou != null ? formatStatValue(format, r.name, r.bestYou) : "—"}
                </td>
                <td className="aqt-tnum px-3 py-2 text-right font-semibold text-[color:var(--aqt-fg)]">{formatStatValue(format, r.name, r.avg10)}</td>
                <td
                  className="aqt-tnum px-3 py-2 text-right font-bold"
                  style={{ color: r.delta == null ? "var(--aqt-fg-faint)" : r.delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                >
                  {r.delta != null ? formatDelta(r.delta) : "—"}
                </td>
                <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">
                  {r.bestAll != null ? formatStatValue(format, r.name, r.bestAll) : "—"}
                </td>
                <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">{formatStatValue(format, r.name, r.global10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <div className="py-8 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noStatsMatch")}</div>
        ) : null}
      </div>
    </div>
  );
};

export default HeroStatsTable;
