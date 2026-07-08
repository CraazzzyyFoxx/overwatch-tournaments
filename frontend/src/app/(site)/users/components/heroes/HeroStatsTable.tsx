"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { LogStatsName } from "@/types/stats.types";
import { formatDelta, formatStatValue } from "@/app/(site)/users/components/heroes/utils";

export type StatSortKey = "delta" | "overall" | "avg10" | "name";

export interface AllStatsRow {
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
  // Plain render helper (not a component) to avoid recreating a component during render.
  const sortTh = (label: string, k: StatSortKey, align: "left" | "right" = "right") => (
    <th
      onClick={() => onSortChange(k)}
      className={cn(
        "aqt-mono cursor-pointer select-none border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-[11px] font-bold uppercase tracking-[0.1em]",
        align === "right" ? "text-right" : "text-left",
        sort === k ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)] hover:text-[color:var(--aqt-fg-muted)]"
      )}
    >
      {label}
      {sort === k ? " ↓" : ""}
    </th>
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative min-w-[180px] max-w-[280px] flex-1">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder={t("users.heroes.searchStats")}
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[13.5px] text-[color:var(--aqt-fg)] outline-none"
          />
        </div>
        <span className="aqt-mono text-[11.5px] text-[color:var(--aqt-fg-faint)]">{t("users.heroes.recordLegend")}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="aqt-tnum w-full border-collapse text-[13.5px]">
          <thead>
            <tr>
              {sortTh(t("users.heroes.col.stat"), "name", "left")}
              {sortTh(t("users.heroes.col.overall"), "overall")}
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">{t("users.heroes.col.bestYou")}</th>
              {sortTh(t("users.heroes.col.avg10"), "avg10")}
              {sortTh("Δ", "delta")}
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">{t("users.heroes.col.bestAll")}</th>
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">{t("users.heroes.col.global10")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                <td className="px-3 py-2 text-left font-medium text-[color:var(--aqt-fg)]">
                  {r.label}
                  {r.isRecord ? <span className="ml-1.5 text-[color:var(--aqt-amber)]" title={t("users.heroes.recordTitle")}>♔</span> : null}
                </td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{formatStatValue(r.name, r.overall)}</td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                  {r.bestYou != null ? formatStatValue(r.name, r.bestYou) : "—"}
                </td>
                <td className="aqt-mono px-3 py-2 text-right font-semibold text-[color:var(--aqt-fg)]">{formatStatValue(r.name, r.avg10)}</td>
                <td
                  className="aqt-mono px-3 py-2 text-right font-bold"
                  style={{ color: r.delta == null ? "var(--aqt-fg-faint)" : r.delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                >
                  {r.delta != null ? formatDelta(r.delta) : "—"}
                </td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">
                  {r.bestAll != null ? formatStatValue(r.name, r.bestAll) : "—"}
                </td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">{formatStatValue(r.name, r.global10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noStatsMatch")}</div>
        ) : null}
      </div>
    </div>
  );
};

export default HeroStatsTable;
