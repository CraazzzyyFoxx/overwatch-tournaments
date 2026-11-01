"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import PlayerName from "@/components/PlayerName";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { BuildRow } from "./Build";
import { heldAt, shopPurchases, statsAt, teamAt, type DlPlayer, type DlTeam, type MatchFeed } from "./model";
import { DIM, FAINT, GAME_SIDE_COLOR, SEAT, useItems, useStatFormat } from "./parts";
import PlayerPanel from "./PlayerPanel";
import { HeroBadge } from "./Scoreboard";

interface RostersProps {
  teams: readonly [DlTeam, DlTeam];
  feed: MatchFeed | null;
  durationS: number;
  t: number;
}

/**
 * The two teams side by side, as the game's own scoreboard lays them out: a team line with its kills, souls and
 * structures at the moment, then each player as two lines (hero, name, K/D/A and souls; the inventory below). The
 * best souls and kills of the match are bold. A player opens his panel under his card.
 */
export default function Rosters({ teams, feed, durationS, t }: Readonly<RostersProps>) {
  const tr = useTranslations();
  const text = useStatFormat();
  const items = useItems();
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const atEnd = t >= durationS || !feed;
  const everyone = useMemo(() => teams.flatMap((team) => team.players), [teams]);
  const statsOf = useMemo(
    () => new Map(everyone.map((player) => [player.memberId, statsAt(player, feed, t, atEnd)])),
    [everyone, feed, t, atEnd]
  );
  const best = (code: string) => Math.max(0, ...everyone.map((player) => statsOf.get(player.memberId)?.[code] ?? 0));
  const bestSouls = best("net_worth");
  const bestKills = best("kills");
  const toggle = (memberId: number) =>
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(memberId)) next.delete(memberId);
      else next.add(memberId);
      return next;
    });

  const row = (player: DlPlayer) => {
    const stats = statsOf.get(player.memberId) ?? {};
    const expanded = open.has(player.memberId);
    const held =
      feed && items ? heldAt(shopPurchases(feed, player.memberId, (id) => items.byId.get(id)?.type === "upgrade"), atEnd ? durationS : t) : null;
    return (
      <li key={player.memberId} className="border-t border-[color:var(--aqt-border)] first:border-t-0">
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 px-3 py-2.5 hover:bg-[color:var(--aqt-overlay-2)]">
          <div className="row-span-2 flex items-center gap-1.5 self-start pt-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-expanded={expanded}
              aria-label={tr(expanded ? "matches.deadlock.collapse" : "matches.deadlock.expand", { name: player.display.name })}
              onClick={() => toggle(player.memberId)}
              className="group/trigger shrink-0"
            >
              <ChevronDown aria-hidden className={cn("size-4", triggerChevronClass)} />
            </Button>
            <HeroBadge player={player} level={stats.level} size={36} />
          </div>
          <PlayerName display={player.display} className="min-w-0 text-body text-[color:var(--aqt-fg)]" />
          <p className="aqt-tnum m-0 flex items-baseline gap-3 whitespace-nowrap text-caption">
            <span className={DIM}>
              <span className={cn((stats.kills ?? 0) > 0 && stats.kills === bestKills && "font-bold text-[color:var(--aqt-fg)]")}>
                {stats.kills ?? 0}
              </span>
              /{stats.deaths ?? 0}/{stats.assists ?? 0}
            </span>
            <span
              className={cn(
                "min-w-16 text-end",
                (stats.net_worth ?? 0) > 0 && stats.net_worth === bestSouls ? "font-bold text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]"
              )}
              title={tr("matches.deadlock.colTitle.net_worth")}
            >
              {text(stats.net_worth ?? 0, "int")}
            </span>
          </p>
          {/* Positioned, so the item cards' corner badges clip here instead of widening the page. */}
          <div className="relative col-span-2 col-start-2 min-w-0 overflow-x-auto [scrollbar-width:none]">
            {held ? <BuildRow held={held} t={t} atEnd={atEnd} /> : <Skeleton className="h-8 w-60" />}
          </div>
        </div>
        {expanded ? (
          <div className="border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]">
            <PlayerPanel player={player} everyone={everyone} feed={feed} durationS={durationS} t={t} />
          </div>
        ) : null}
      </li>
    );
  };

  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      {teams.map((team) => {
        const seat = SEAT[team.side];
        const head = feed ? teamAt(team, feed, t, atEnd) : null;
        return (
          <Card asChild key={team.id} className="overflow-hidden p-0">
            <section aria-label={team.name}>
              <header
                className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[color:var(--aqt-border)] px-3.5 py-2.5"
                style={{ background: `color-mix(in srgb, ${seat} 9%, var(--aqt-card))` }}
              >
                <span aria-hidden className="h-5 w-[3px] shrink-0 rounded-full" style={{ background: seat }} />
                <h3 className="m-0 truncate text-ui font-semibold" title={team.name}>
                  {team.name}
                </h3>
                {team.gameSide ? (
                  <span className="inline-flex items-center gap-1.5 text-label font-medium" style={{ color: seat }}>
                    <span aria-hidden className="size-1.5 rotate-45" style={{ background: GAME_SIDE_COLOR[team.gameSide] }} />
                    {tr(`matches.deadlock.side.${team.gameSide}`)}
                  </span>
                ) : null}
                {head ? (
                  <dl className={cn("aqt-tnum m-0 ms-auto flex gap-4 text-caption", FAINT)}>
                    {[
                      [tr("matches.deadlock.colTitle.kills"), head.kills],
                      [tr("matches.deadlock.colTitle.net_worth"), head.souls],
                      [tr("matches.deadlock.breakdown.objectives"), head.objectives]
                    ].map(([label, value]) => (
                      <div key={label} className="flex items-baseline gap-1.5">
                        <dt>{label}</dt>
                        <dd className="m-0 font-semibold text-[color:var(--aqt-fg)]">{text(Number(value), "int")}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </header>
              <ul className="m-0">{team.players.map(row)}</ul>
            </section>
          </Card>
        );
      })}
    </div>
  );
}
