"use client";

import { Fragment, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerName from "@/components/PlayerName";
import { Button } from "@/components/ui/button";
import { triggerChevronClass } from "@/components/ui/chevron";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { BuildRow } from "./Build";
import { PRESETS, type Column, type PresetKey } from "./columns";
import { heldAt, sampleTimeAt, shopPurchases, statsAt, type DlPlayer, type DlTeam, type MatchFeed, type MetricContext } from "./model";
import { FAINT, GAME_SIDE_COLOR, SEAT, useItems, useStatFormat } from "./parts";
import PlayerPanel from "./PlayerPanel";

/** Widest a magnitude bar grows, in px. */
const BAR_MAX_PX = 56;
/** Every cell wears its own bottom hairline: a `separate` table (sticky cells keep their borders) draws none on a row. */
const CELL = "h-12 whitespace-nowrap border-b border-[color:var(--aqt-border)] px-2.5 py-0";
/** The player column: pinned left, opaque, a right hairline. */
const STICKY = "sticky left-0 z-10 border-r border-[color:var(--aqt-border)] text-left";
/** An opaque stand-in for the row's hover, so a pinned cell never turns see-through. */
const STICKY_HOVER =
  "bg-[color:var(--aqt-card)] group-hover/row:[background-image:linear-gradient(var(--aqt-overlay-2),var(--aqt-overlay-2))]";

interface ScoreboardProps {
  teams: readonly [DlTeam, DlTeam];
  /** `null` while the events load; builds and the moment wait for them. */
  feed: MatchFeed | null;
  minutes: number | null;
  durationS: number;
  /** The moment on screen, in seconds; `durationS` is the end of the match. */
  t: number;
  /** The column set; the shell draws its switch in the tab row. */
  preset: PresetKey;
}

/** The hero portrait with the level the player had reached, the game's own corner badge. */
export function HeroBadge({ player, level, size = 32 }: Readonly<{ player: DlPlayer; level: number | undefined; size?: number }>) {
  return (
    <span className="relative shrink-0">
      {player.hero ? <CatalogEntityImage entity={player.hero} size={size} /> : <span className="block" style={{ width: size, height: size }} />}
      {level ? (
        <span className="aqt-tnum absolute -bottom-1 -right-1.5 min-w-[18px] rounded-[4px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] px-1 text-center text-label font-semibold leading-4 text-[color:var(--aqt-fg)]">
          {level}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Both teams' players in one table so they scroll sideways together: a column set, a team line with the totals,
 * then the players by end-of-match souls, each column's best in bold. Everything reads the moment on screen: the
 * figures from the game's last sample by then, the inventory exactly. A player's row opens his panel.
 */
export default function Scoreboard({ teams, feed, minutes, durationS, t, preset }: Readonly<ScoreboardProps>) {
  const tr = useTranslations();
  const text = useStatFormat();
  const items = useItems();
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const columns: Column[] = PRESETS[preset];
  const withBuild = preset === "overview";
  const span = 1 + columns.length + (withBuild ? 1 : 0);
  const atEnd = t >= durationS || !feed;
  const sampled = feed && !atEnd ? sampleTimeAt(feed, t) : null;

  const statsOf = useMemo(
    () => new Map(teams.flatMap((team) => team.players).map((player) => [player.memberId, statsAt(player, feed, t, atEnd)])),
    [teams, feed, t, atEnd]
  );

  const contexts = useMemo(() => {
    const kills = (team: DlTeam) => team.players.reduce((total, player) => total + (statsOf.get(player.memberId)?.kills ?? 0), 0);
    const played = atEnd ? minutes : sampled ? sampled / 60 : null;
    return new Map(teams.map((team) => [team.side, { minutes: played, teamKills: kills(team) } satisfies MetricContext]));
  }, [teams, minutes, statsOf, atEnd, sampled]);

  const valueOf = (column: Column, player: DlPlayer) =>
    atEnd || column.timed ? column.value(statsOf.get(player.memberId)!, contexts.get(player.side)!) : null;

  const { best, maxima } = useMemo(() => {
    const best: Record<string, number> = {};
    const maxima: Record<string, number> = {};
    for (const column of columns) {
      const values = teams
        .flatMap((team) => team.players.map((player) => valueOf(column, player)))
        .filter((value): value is number => value != null && value > 0);
      if (!values.length) continue;
      best[column.key] = column.fewer ? Math.min(...values) : Math.max(...values);
      maxima[column.key] = Math.max(...values);
    }
    return { best, maxima };
    // `valueOf` reads `statsOf` and `contexts`, which the deps cover.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teams, columns, statsOf, contexts, atEnd]);

  const everyone = useMemo(() => teams.flatMap((team) => team.players), [teams]);
  const toggle = (memberId: number) =>
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(memberId)) next.delete(memberId);
      else next.add(memberId);
      return next;
    });
  const title = (key: string) => tr(`matches.deadlock.colTitle.${key}` as never);

  const buildCell = (memberId: number) => {
    if (!feed || !items) return <Skeleton className="h-9 w-64" />;
    const purchases = shopPurchases(feed, memberId, (id) => items.byId.get(id)?.type === "upgrade");
    return <BuildRow held={heldAt(purchases, atEnd ? durationS : t)} t={t} atEnd={atEnd} />;
  };

  return (
    <div className="flex flex-col gap-3">
      <Table
        aria-label={tr("matches.scoreboard.scrollHint")}
        wrapperClassName="rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
        className="border-separate border-spacing-0 text-caption"
      >
        <TableHeader>
          <TableRow>
            <TableHead scope="col" className={cn("h-9 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]", STICKY)}>
              {tr("matches.scoreboard.player")}
            </TableHead>
            {columns.map((column) => (
              <TableHead key={column.key} scope="col" title={title(column.key)} className="h-9 text-right">
                {tr(`matches.deadlock.col.${column.key}` as never)}
              </TableHead>
            ))}
            {withBuild ? (
              <TableHead scope="col" className="h-9 text-left">
                {tr("matches.deadlock.build")}
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>

        {teams.map((team, index) => {
          const seat = SEAT[team.side];
          const tint = `color-mix(in srgb, ${seat} 8%, var(--aqt-card))`;
          const ctx = contexts.get(team.side)!;
          const stats = team.players.map((player) => statsOf.get(player.memberId)!);
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
                  className={cn(CELL, STICKY, "h-11 text-caption font-semibold normal-case tracking-normal text-[color:var(--aqt-fg)]")}
                  style={{ backgroundColor: tint }}
                >
                  <span className="flex items-center gap-2.5">
                    <span aria-hidden className="h-5 w-[3px] shrink-0 rounded-full" style={{ background: seat }} />
                    <span className="max-w-56 truncate" title={team.name}>
                      {team.name}
                    </span>
                    {team.gameSide ? (
                      <span className="inline-flex items-center gap-1.5 text-label font-medium" style={{ color: seat }}>
                        <span aria-hidden className="size-1.5 rotate-45" style={{ background: GAME_SIDE_COLOR[team.gameSide] }} />
                        {tr(`matches.deadlock.side.${team.gameSide}`)}
                      </span>
                    ) : null}
                    <span className={eyebrowClass("faint", "ms-auto ps-3")}>{tr("matches.scoreboard.total")}</span>
                  </span>
                </TableHead>
                {columns.map((column) => {
                  const total = atEnd || column.timed ? column.total(stats, ctx) : null;
                  return (
                    <TableCell key={column.key} className={cn(CELL, "aqt-tnum h-11 text-right font-semibold text-[color:var(--aqt-fg-dim)]")}>
                      {total === null ? null : text(total, column.format)}
                    </TableCell>
                  );
                })}
                {withBuild ? <TableCell className={cn(CELL, "h-11")} /> : null}
              </TableRow>

              {team.players.map((player) => {
                const expanded = open.has(player.memberId);
                const level = statsOf.get(player.memberId)?.level;
                return (
                  <Fragment key={player.memberId}>
                    <TableRow className="group/row">
                      <TableHead
                        scope="row"
                        className={cn(CELL, STICKY, STICKY_HOVER, "font-normal normal-case tracking-normal text-[color:var(--aqt-fg)]")}
                      >
                        <div className="flex min-w-56 items-center gap-2.5 max-sm:min-w-44">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            aria-expanded={expanded}
                            aria-label={tr(expanded ? "matches.deadlock.collapse" : "matches.deadlock.expand", {
                              name: player.display.name
                            })}
                            onClick={() => toggle(player.memberId)}
                            className="group/trigger shrink-0"
                          >
                            <ChevronDown aria-hidden className={cn("size-4", triggerChevronClass)} />
                          </Button>
                          <HeroBadge player={player} level={level} />
                          <PlayerName display={player.display} className="ms-1 min-w-0 text-body text-[color:var(--aqt-fg)]" />
                        </div>
                      </TableHead>
                      {columns.map((column) => {
                        const value = valueOf(column, player);
                        const cell = cn(CELL, "aqt-tnum text-right");
                        if (value == null) {
                          return (
                            <TableCell key={column.key} className={cn(cell, FAINT)} title={atEnd ? undefined : tr("matches.deadlock.scoreboard.endOnly")}>
                              —
                            </TableCell>
                          );
                        }
                        const isBest = best[column.key] === value;
                        const tone =
                          value === 0
                            ? "text-[color:var(--aqt-fg-faint)]"
                            : isBest
                              ? "font-bold text-[color:var(--aqt-fg)]"
                              : "text-[color:var(--aqt-fg-muted)]";
                        const max = maxima[column.key] ?? 0;
                        return (
                          <TableCell key={column.key} className={cell}>
                            <div className="flex flex-col items-end">
                              <span className={tone}>{text(value, column.format)}</span>
                              {column.bar && max > 0 && value > 0 ? (
                                <span
                                  aria-hidden
                                  className="mt-[3px] block h-0.5 rounded-sm"
                                  style={{
                                    width: Math.max(2, (value / max) * BAR_MAX_PX),
                                    background: isBest ? SEAT[player.side] : "var(--aqt-border-3)"
                                  }}
                                />
                              ) : null}
                            </div>
                          </TableCell>
                        );
                      })}
                      {withBuild ? <TableCell className={CELL}>{buildCell(player.memberId)}</TableCell> : null}
                    </TableRow>
                    {expanded ? (
                      <TableRow>
                        <TableCell colSpan={span} className="border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-0">
                          <PlayerPanel player={player} everyone={everyone} feed={feed} durationS={durationS} t={t} />
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                );
              })}
            </TableBody>
          );
        })}
      </Table>
    </div>
  );
}
