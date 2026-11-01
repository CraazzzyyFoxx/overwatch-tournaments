"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import { LogStatsName } from "../stat-names";
import PlayerName from "@/components/PlayerName";
import { TeamLogo } from "@/components/TeamName";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { Button } from "@/components/ui/button";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useHeroClass } from "@/disciplines/overwatch/character/classes";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { MvpPlacementBadge, MvpTooltip } from "./MvpOrdinal";
import { MVP_SORT, columnBest, hasStat, orderPlayers, sortsAscending, type SortKey } from "./scoreboard.model";
import {
  PRESET_BANDS,
  PRESET_ORDER,
  STAT_META,
  columnMaxima,
  formatStat,
  playerClass,
  playerStat,
  resolveMatchMvpPlacement,
  teamAggregate,
  type MatchStatsPlayer,
  type MatchStatsTeam,
  type PresetKey
} from "./stats";

/** Widest a magnitude bar grows, in px. */
const BAR_MAX_PX = 56;
/** Heroes drawn before the rest fold into the strip's `+N`. */
const MAX_HEROES = 3;
const MINUS = "\u2212";

/** Every cell wears its own bottom hairline: a `separate` table (sticky cells keep their borders) draws none on a row. */
const CELL = "h-11 whitespace-nowrap border-b border-[color:var(--aqt-border)] px-2.5 py-0";
const HAIRLINE = "border-l border-[color:var(--aqt-border)]";
/** The player column: pinned left, opaque, a right hairline. */
const STICKY = "sticky left-0 z-10 border-r border-[color:var(--aqt-border)] text-left";
/** An opaque stand-in for the row's `--aqt-overlay-2` hover, so a pinned cell never turns see-through. */
const STICKY_HOVER =
  "bg-[color:var(--aqt-card)] group-hover/row:[background-image:linear-gradient(var(--aqt-overlay-2),var(--aqt-overlay-2))]";
const PLAYER_WIDTH = "min-w-48 max-sm:min-w-36";

const seatColor = (isHome: boolean) => (isHome ? "var(--aqt-teal)" : "var(--aqt-rose)");

interface HeroClass {
  label: (cls: string | null | undefined) => string;
  color: (cls: string | null | undefined) => string;
  icon: (cls: string | null | undefined, size: number) => ReactNode;
}

const PlayerCell = ({ player, heroClass }: { player: MatchStatsPlayer; heroClass: HeroClass }) => {
  const cls = playerClass(player, 0);
  const icon = heroClass.icon(cls, 15);
  const classLabel = heroClass.label(cls);

  return (
    <div className={cn("flex items-center gap-2.5 max-sm:gap-2", PLAYER_WIDTH)}>
      {icon ? (
        <span
          role="img"
          aria-label={classLabel}
          title={classLabel}
          className="inline-grid w-4.5 shrink-0 place-items-center"
          style={{ color: heroClass.color(cls) }}
        >
          {icon}
        </span>
      ) : (
        <span aria-hidden className="w-4.5 shrink-0" />
      )}
      <PlayerName
        display={player.display}
        className="text-body text-[color:var(--aqt-fg)] max-sm:[&_bdi+span]:hidden"
      />
    </div>
  );
};

interface ScoreboardProps {
  home: MatchStatsTeam;
  away: MatchStatsTeam;
  /** 0 = the whole map, otherwise a segment. */
  round: number;
  metadata: DisciplineMetadata;
}

/**
 * The two teams' players in one table, so both scroll sideways together: a column preset, a team line with
 * the column totals, then the players (tank, damage, support) with each column's best marked in bold. A head
 * sorts the players of both teams.
 */
export default function Scoreboard({ home, away, round, metadata }: Readonly<ScoreboardProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  const [preset, setPreset] = useState<PresetKey>("overview");
  const [sort, setSort] = useState<SortKey | null>(null);

  const bands = PRESET_BANDS[preset];
  const columns = useMemo(() => bands.flatMap((band) => band.columns), [bands]);
  const bandStart = new Set(bands.slice(1).map((band) => band.columns[0]));
  // A sort on a column the preset does not show would reorder rows with nothing to explain it.
  const activeSort = sort !== null && (sort === MVP_SORT || columns.includes(sort)) ? sort : null;
  const best = useMemo(() => columnBest(home, away, round, columns), [home, away, round, columns]);
  const maxima = useMemo(() => columnMaxima(home, away, round, columns), [home, away, round, columns]);

  const text = (name: LogStatsName, value: number) =>
    name === LogStatsName.DamageDelta && value !== 0
      ? `${value > 0 ? "+" : MINUS}${formatStat(name, Math.abs(value), format)}`
      : formatStat(name, value, format);
  const label = (name: string) => (STAT_META[name] ? t(STAT_META[name].labelKey as Parameters<typeof t>[0]) : name);
  const toggleSort = (key: SortKey) => setSort(activeSort === key ? null : key);

  const sortHead = (key: SortKey, abbr: string, full: string, className?: string) => {
    const active = activeSort === key;
    const ascending = sortsAscending(key);
    const Arrow = ascending ? ArrowUp : ArrowDown;
    return (
      <TableHead
        key={key}
        scope="col"
        aria-sort={active ? (ascending ? "ascending" : "descending") : undefined}
        className={cn("h-8.5 text-right", className)}
      >
        <Button
          variant="ghost"
          size="label"
          title={full}
          aria-label={t("matches.scoreboard.sortBy", { stat: full })}
          onClick={() => toggleSort(key)}
          className={cn("hover:bg-transparent", active && "text-[color:var(--aqt-fg)]")}
        >
          {active ? <Arrow aria-hidden /> : null}
          {abbr}
        </Button>
      </TableHead>
    );
  };

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <ToggleGroup
            value={preset}
            onValueChange={(value) => value && setPreset(value as PresetKey)}
            variant="pill"
            size="sm"
            aria-label={t("matches.scoreboard.columns")}
            className="max-w-full overflow-x-auto"
          >
            {PRESET_ORDER.map((key) => (
              // Items keep their padding; the group scrolls on a narrow screen instead of squeezing them.
              <ToggleGroupItem key={key} value={key} className="shrink-0">
                {t(`matches.preset.${key}`)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <span className="text-caption text-[color:var(--aqt-fg-faint)]">{t("matches.scoreboard.hint")}</span>
        </div>

        <Table
          aria-label={t("matches.scoreboard.scrollHint")}
          wrapperClassName="rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
          className="border-separate border-spacing-0 text-caption"
        >
          <TableHeader>
            {bands.length > 1 ? (
              <TableRow>
                <TableHead
                  scope="colgroup"
                  aria-label={t("matches.scoreboard.player")}
                  className={cn("h-7 bg-[color:var(--aqt-card)]", STICKY)}
                />
                <TableHead scope="colgroup" className="h-7" />
                <TableHead scope="colgroup" className="h-7" />
                {bands.map((band, index) => (
                  <TableHead
                    key={band.columns[0]}
                    scope="colgroup"
                    colSpan={band.columns.length}
                    className={cn("h-7 pt-2 text-[color:var(--aqt-fg-dim)]", index > 0 && HAIRLINE)}
                  >
                    {band.labelKey ? t(band.labelKey as Parameters<typeof t>[0]) : null}
                  </TableHead>
                ))}
              </TableRow>
            ) : null}
            <TableRow>
              <TableHead
                scope="col"
                className={cn("h-8.5 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]", STICKY)}
              >
                {t("matches.scoreboard.player")}
              </TableHead>
              <TableHead scope="col" className="h-8.5 text-left">
                {t("common.heroes")}
              </TableHead>
              {sortHead(MVP_SORT, t("matches.scoreboard.mvp"), t("matches.scoreboard.mvpTitle"))}
              {columns.map((name) =>
                sortHead(name, STAT_META[name]?.abbr ?? name, label(name), bandStart.has(name) ? HAIRLINE : undefined)
              )}
            </TableRow>
          </TableHeader>

          {[home, away].map((team, index) => {
            const seat = seatColor(index === 0);
            const tint = `color-mix(in srgb, ${seat} 7%, var(--aqt-card))`;
            return (
              <TableBody
                key={team.id}
                className={cn(
                  "[&_tr:last-child>*]:border-b-0",
                  index > 0 && "[&_tr:first-child>*]:border-t [&_tr:first-child>*]:border-t-[color:var(--aqt-border-2)]"
                )}
              >
                <TableRow style={{ backgroundColor: tint }}>
                  <TableHead
                    scope="rowgroup"
                    className={cn(
                      CELL,
                      STICKY,
                      "h-10 text-caption font-semibold normal-case tracking-normal text-[color:var(--aqt-fg)]"
                    )}
                    style={{ backgroundColor: tint }}
                  >
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="h-5 w-[3px] shrink-0 rounded-full" style={{ background: seat }} />
                      <TeamLogo team={team.team} size="sm" />
                      <span className="max-w-64 truncate" title={team.name}>
                        {team.name}
                      </span>
                    </span>
                  </TableHead>
                  <TableCell className={cn(CELL, "h-10")} />
                  <TableCell className={cn(CELL, "h-10", eyebrowClass("faint", "text-right"))}>
                    {t("matches.scoreboard.total")}
                  </TableCell>
                  {columns.map((name) => {
                    const total = teamAggregate(team, round, name);
                    return (
                      <TableCell
                        key={name}
                        className={cn(
                          CELL,
                          "aqt-tnum h-10 text-right font-semibold text-[color:var(--aqt-fg-dim)]",
                          bandStart.has(name) && HAIRLINE
                        )}
                      >
                        {total === null ? null : text(name, total)}
                      </TableCell>
                    );
                  })}
                </TableRow>

                {orderPlayers(team, round, activeSort).map((player) => {
                  const placement = resolveMatchMvpPlacement(player, round);
                  return (
                    <TableRow key={player.workspace_member_id} className="group/row">
                      <TableHead
                        scope="row"
                        className={cn(
                          CELL,
                          STICKY,
                          STICKY_HOVER,
                          "text-body font-normal normal-case tracking-normal text-[color:var(--aqt-fg)]"
                        )}
                      >
                        <PlayerCell player={player} heroClass={heroClass} />
                      </TableHead>
                      <TableCell className={CELL}>
                        <CatalogEntityStrip entities={player.heroes[round] ?? []} size="sm" limit={MAX_HEROES} />
                      </TableCell>
                      <TableCell className={cn(CELL, "text-right")}>
                        {placement === null ? null : (
                          <MvpTooltip facts={player.stats[round]}>
                            <MvpPlacementBadge placement={placement} size="sm" />
                          </MvpTooltip>
                        )}
                      </TableCell>
                      {columns.map((name) => {
                        const cell = cn(CELL, "aqt-tnum text-right", bandStart.has(name) && HAIRLINE);
                        if (!hasStat(player, round, name)) return <TableCell key={name} className={cell} />;
                        const value = playerStat(player, round, name);
                        const isBest = best[name] === value;
                        const tone =
                          name === LogStatsName.DamageDelta
                            ? value > 0
                              ? "text-[color:var(--aqt-up)]"
                              : value < 0
                                ? "text-[color:var(--aqt-rose)]"
                                : "text-[color:var(--aqt-fg-faint)]"
                            : value === 0
                              ? "text-[color:var(--aqt-fg-faint)]"
                              : isBest
                                ? "font-bold text-[color:var(--aqt-fg)]"
                                : "text-[color:var(--aqt-fg-muted)]";
                        const max = maxima[name] ?? 0;
                        return (
                          <TableCell key={name} className={cell}>
                            <div className="flex flex-col items-end">
                              <span className={tone}>{text(name, value)}</span>
                              {STAT_META[name]?.bar && max > 0 && value > 0 ? (
                                <span
                                  aria-hidden
                                  className={cn(
                                    "mt-[3px] block h-0.5 rounded-sm",
                                    isBest ? "bg-[color:var(--aqt-fg-muted)]" : "bg-[color:var(--aqt-border-3)]"
                                  )}
                                  style={{ width: Math.max(2, (value / max) * BAR_MAX_PX) }}
                                />
                              ) : null}
                            </div>
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  );
                })}
              </TableBody>
            );
          })}
        </Table>
      </div>
    </TooltipProvider>
  );
}
