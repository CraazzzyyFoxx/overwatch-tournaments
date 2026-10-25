"use client";

import { useState } from "react";
import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import { eyebrowClass } from "@/components/ui/eyebrow";
import { SearchField } from "@/components/ui/search-field";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";

import { sections, type StatRow } from "./hero-stats";
import StatGameLink from "./StatGameLink";
import { deltaColor, formatDelta, formatStatValue } from "./utils";

const HEAD = cn(
  eyebrowClass(),
  "aqt-tnum whitespace-nowrap border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right"
);
/** The stat column stays put while the figures scroll under it on a narrow screen. */
const STICKY = "sticky left-0 z-10 bg-[color:var(--aqt-card)]";

/**
 * Every stat of the hero in the overview's groups: the player's figure against every player's, the career total, the
 * player's best game and the hero's record, each game linking to its match and naming its map or holder.
 */
const HeroStatsTable = ({ rows, lowSampleNote }: { rows: StatRow[]; lowSampleNote: string | null }) => {
  const t = useTranslations();
  const format = useFormatter();
  const [search, setSearch] = useState("");
  const label = (row: StatRow) => t(row.labelKey as Parameters<typeof t>[0]);
  const query = search.trim().toLocaleLowerCase();
  const shown = sections(query ? rows.filter((row) => label(row).toLocaleLowerCase().includes(query)) : rows);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SearchField
          label={t("users.heroes.searchStats")}
          placeholder={t("users.heroes.searchStats")}
          value={search}
          onValueChange={setSearch}
          containerClassName="min-w-[180px] max-w-[280px] flex-1"
        />
        <span className="inline-flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-faint)]">
          <Crown aria-hidden className="size-3 text-[color:var(--aqt-amber)]" />
          {t("users.heroes.recordTitle")}
        </span>
      </div>
      <div
        role="region"
        aria-label={t("users.heroes.allStats")}
        tabIndex={0}
        // `relative`: the Δ head's screen-reader text is absolutely positioned, and would otherwise widen the page.
        className="relative overflow-x-auto rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--aqt-teal)]"
      >
        <table className="aqt-tnum w-full min-w-[46rem] border-collapse text-caption">
          <thead>
            <tr>
              <th scope="col" className={cn(HEAD, STICKY, "text-left")}>
                {t("users.heroes.col.stat")}
              </th>
              <th scope="col" className={HEAD}>
                {t("users.heroes.col.avg10")}
              </th>
              <th scope="col" className={HEAD}>
                {t("users.heroes.col.global10")}
              </th>
              <th scope="col" className={HEAD} title={lowSampleNote ?? undefined}>
                <span aria-hidden>Δ</span>
                <span className="sr-only">{t("users.heroes.col.delta")}</span>
              </th>
              <th scope="col" className={HEAD}>
                {t("users.heroes.col.overall")}
              </th>
              <th scope="col" className={HEAD}>
                {t("users.heroes.col.bestYou")}
              </th>
              <th scope="col" className={HEAD}>
                {t("users.heroes.col.bestAll")}
              </th>
            </tr>
          </thead>
          {shown.map((section) => (
            <tbody key={section.group}>
              <tr>
                <th scope="rowgroup" colSpan={7} className={cn(eyebrowClass("dim"), "px-3 pb-1.5 pt-4 text-left")}>
                  {t(`users.heroes.group.${section.group}`)}
                </th>
              </tr>
              {section.rows.map((row) => (
                <tr key={row.name} className="h-11 border-b border-[color:var(--aqt-border)] last:border-b-0">
                  <th scope="row" className={cn(STICKY, "px-3 py-2 text-left font-medium text-[color:var(--aqt-fg)]")}>
                    <span className="inline-flex items-center gap-1.5">
                      {label(row)}
                      {row.holdsRecord ? (
                        <Crown
                          role="img"
                          aria-label={t("users.heroes.recordTitle")}
                          className="size-3 shrink-0 text-[color:var(--aqt-amber)]"
                        />
                      ) : null}
                    </span>
                  </th>
                  <td className="px-3 py-2 text-right font-semibold text-[color:var(--aqt-fg)]">
                    {formatStatValue(format, row.name, row.value)}
                  </td>
                  <td className="px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">
                    {row.average == null ? "—" : formatStatValue(format, row.name, row.average)}
                  </td>
                  <td
                    className="px-3 py-2 text-right font-bold"
                    style={{ color: deltaColor(row.delta) }}
                    title={row.delta == null ? (lowSampleNote ?? undefined) : undefined}
                  >
                    {row.delta == null ? "—" : formatDelta(row.delta)}
                  </td>
                  <td className="px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {row.total == null ? "—" : formatStatValue(format, row.name, row.total)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-[color:var(--aqt-fg-faint)]">
                    {row.best ? (
                      <StatGameLink game={row.best} value={formatStatValue(format, row.name, row.best.value)} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right text-[color:var(--aqt-fg-faint)]">
                    {row.record ? (
                      <StatGameLink
                        game={row.record}
                        value={formatStatValue(format, row.name, row.record.value)}
                        holder
                      />
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
        {shown.length === 0 ? (
          <p className="py-8 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noStatsMatch")}</p>
        ) : null}
      </div>
    </div>
  );
};

export default HeroStatsTable;
