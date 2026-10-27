"use client";

import { useState } from "react";
import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import { SearchField } from "@/components/ui/search-field";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";

import { sections, type StatRow } from "./hero-stats";
import StatGameLink from "./StatGameLink";
import { deltaColor, formatDelta, formatStatValue } from "./utils";

const HEAD = "aqt-tnum whitespace-nowrap px-3 py-2.5 text-right";
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
        {/* The region above owns the scroll (and the sticky stat column), so the table's own wrapper stays inert. */}
        <Table wrapperClassName="overflow-visible" className="aqt-tnum min-w-[46rem] border-collapse">
          <TableHeader>
            <TableRow>
              <TableHead scope="col" className={cn(HEAD, STICKY, "text-left")}>
                {t("users.heroes.col.stat")}
              </TableHead>
              <TableHead scope="col" className={HEAD}>
                {t("users.heroes.col.avg10")}
              </TableHead>
              <TableHead scope="col" className={HEAD}>
                {t("users.heroes.col.global10")}
              </TableHead>
              <TableHead scope="col" className={HEAD} title={lowSampleNote ?? undefined}>
                <span aria-hidden>Δ</span>
                <span className="sr-only">{t("users.heroes.col.delta")}</span>
              </TableHead>
              <TableHead scope="col" className={HEAD}>
                {t("users.heroes.col.overall")}
              </TableHead>
              <TableHead scope="col" className={HEAD}>
                {t("users.heroes.col.bestYou")}
              </TableHead>
              <TableHead scope="col" className={HEAD}>
                {t("users.heroes.col.bestAll")}
              </TableHead>
            </TableRow>
          </TableHeader>
          {shown.map((section) => (
            <TableBody key={section.group}>
              <TableRow className="border-b-0 hover:bg-transparent">
                <TableHead
                  scope="rowgroup"
                  colSpan={7}
                  className="px-3 pb-1.5 pt-4 text-[color:var(--aqt-fg-dim)]"
                >
                  {t(`users.heroes.group.${section.group}`)}
                </TableHead>
              </TableRow>
              {section.rows.map((row) => (
                <TableRow key={row.name} className="group h-11">
                  {/* Opaque, so the figures scroll under it; the row hover is layered on top. */}
                  <TableHead
                    scope="row"
                    className={cn(
                      STICKY,
                      "px-3 py-2 text-caption font-medium normal-case tracking-normal text-[color:var(--aqt-fg)] group-hover:bg-[image:linear-gradient(var(--aqt-overlay-2),var(--aqt-overlay-2))]"
                    )}
                  >
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
                  </TableHead>
                  <TableCell className="px-3 py-2 text-right font-semibold text-[color:var(--aqt-fg)]">
                    {formatStatValue(format, row.name, row.value)}
                  </TableCell>
                  <TableCell className="px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">
                    {row.average == null ? "—" : formatStatValue(format, row.name, row.average)}
                  </TableCell>
                  <TableCell
                    className="px-3 py-2 text-right font-bold"
                    style={{ color: deltaColor(row.delta) }}
                    title={row.delta == null ? (lowSampleNote ?? undefined) : undefined}
                  >
                    {row.delta == null ? "—" : formatDelta(row.delta)}
                  </TableCell>
                  <TableCell className="px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {row.total == null ? "—" : formatStatValue(format, row.name, row.total)}
                  </TableCell>
                  <TableCell className="px-3 py-1.5 text-right text-[color:var(--aqt-fg-faint)]">
                    {row.best ? (
                      <StatGameLink game={row.best} value={formatStatValue(format, row.name, row.best.value)} />
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="px-3 py-1.5 text-right text-[color:var(--aqt-fg-faint)]">
                    {row.record ? (
                      <StatGameLink
                        game={row.record}
                        value={formatStatValue(format, row.name, row.record.value)}
                        holder
                      />
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          ))}
        </Table>
        {shown.length === 0 ? (
          <p className="py-8 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noStatsMatch")}</p>
        ) : null}
      </div>
    </div>
  );
};

export default HeroStatsTable;
