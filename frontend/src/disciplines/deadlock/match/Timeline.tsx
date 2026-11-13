"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { ArrowRight, Crosshair, RotateCw, Skull } from "lucide-react";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { cn } from "@/lib/utils";
import { groupKills, type DlPlayer, type DlTeam, type Kill, type KillGroup, type MatchFeed, type MidBoss, type Objective, type Side } from "./model";
import { LANE_KEY, OBJECTIVE_ICON, objectiveOf } from "./objectives";
import { DIM, FAINT, MUTED, PairScore, SEAT, SEAT_TEXT, formatClock } from "./parts";

type Mark = { kind: "objective"; t: number; objective: Objective } | { kind: "boss"; t: number; boss: MidBoss };
type Row = { kind: "kill"; t: number; kill: Kill } | Mark;

const other = (side: Side): Side => (side === "home" ? "away" : "home");

interface TimelineProps {
  teams: readonly [DlTeam, DlTeam];
  feed: MatchFeed | null;
  status: "pending" | "error" | "success";
  onRetry: () => void;
  durationS: number;
  t: number;
  onTime: (t: number) => void;
}

/**
 * The match as it happened, engagement by engagement: each fight with its score and time, the picks between them,
 * and the structures and mid bosses that fell during each. The engagement under the moment on screen is marked;
 * what comes after it waits faint. Any engagement can be put on the ribbon.
 */
export default function Timeline({ teams, feed, status, onRetry, durationS, t: moment, onTime }: Readonly<TimelineProps>) {
  const t = useTranslations();
  const players = useMemo(() => new Map<number, DlPlayer>(teams.flatMap((team) => team.players.map((player) => [player.memberId, player]))), [teams]);
  const groups = useMemo(() => (feed ? groupKills(feed.kills) : []), [feed]);

  if (status === "pending") {
    return (
      <div role="status" className="grid gap-3 lg:grid-cols-2">
        <span className="sr-only">{t("matches.timeline.loading")}</span>
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} aria-hidden className="h-44 w-full rounded-xl" />
        ))}
      </div>
    );
  }
  if (status === "error" || !feed) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-8 text-center">
        <p className="text-caption text-[color:var(--aqt-rose)]">{t("matches.timeline.error")}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          {t("common.retry")}
        </Button>
      </div>
    );
  }
  if (!feed.kills.length && !feed.objectives.length) {
    return <p className={cn("py-8 text-center text-caption", DIM)}>{t("matches.timeline.empty")}</p>;
  }

  const atEnd = moment >= durationS;
  const name = (memberId: number | null) => (memberId == null ? "—" : (players.get(memberId)?.display.name ?? "—"));
  const teamName = (side: Side) => (side === "home" ? teams[0].name : teams[1].name);

  // A mark belongs to the engagement in progress: the latest one that began by then (the first, before any).
  const marks: Mark[] = [
    ...feed.objectives.map((objective): Mark => ({ kind: "objective", t: objective.t, objective })),
    ...feed.midBoss.map((boss): Mark => ({ kind: "boss", t: boss.t, boss }))
  ];
  const blocks: { group: KillGroup | null; rows: Row[] }[] = groups.length
    ? groups.map((group) => ({ group, rows: group.kills.map((kill): Row => ({ kind: "kill", t: kill.t, kill })) }))
    : [{ group: null, rows: [] }];
  for (const mark of marks) {
    let index = 0;
    blocks.forEach((block, i) => {
      if (block.group && block.group.from <= mark.t) index = i;
    });
    blocks[index].rows.push(mark);
  }
  for (const block of blocks) block.rows.sort((a, b) => a.t - b.t);
  // The engagement under the moment: the last one begun by then.
  let current = -1;
  if (!atEnd) blocks.forEach((block, i) => {
    if (block.group && block.group.from <= moment) current = i;
  });

  const objectiveLabel = (objective: Objective) => {
    const { kind, lane } = objectiveOf(objective.objective);
    const what = t(`matches.deadlock.timeline.objective.${kind}` as never);
    return lane ? `${what} · ${t(`matches.deadlock.lanes.name.${LANE_KEY[lane] ?? "unknown"}` as never)}` : what;
  };
  const future = (time: number) => !atEnd && time > moment;

  const killRow = (kill: Kill, key: string) => {
    const killer = kill.killer == null ? undefined : players.get(kill.killer);
    const victim = kill.victim == null ? undefined : players.get(kill.victim);
    return (
      <li
        key={key}
        className={cn(
          "grid h-8 grid-cols-[44px_minmax(0,1fr)_16px_minmax(0,1fr)] items-center gap-2 rounded-md px-2 hover:bg-[color:var(--aqt-overlay-2)]",
          future(kill.t) && "opacity-40"
        )}
      >
        <span className={cn("aqt-tnum text-label", FAINT)}>{formatClock(kill.t)}</span>
        <span className="flex min-w-0 items-center gap-2">
          {killer?.hero ? <CatalogEntityImage entity={killer.hero} size={24} /> : null}
          <span className={cn("truncate text-caption font-semibold", kill.side ? SEAT_TEXT[kill.side] : MUTED)}>{name(kill.killer)}</span>
        </span>
        <ArrowRight className={cn("size-3.5", FAINT)} aria-hidden="true" />
        <span className="flex min-w-0 items-center gap-2">
          {victim?.hero ? (
            <span className="opacity-60 grayscale">
              <CatalogEntityImage entity={victim.hero} size={24} />
            </span>
          ) : null}
          <span className={cn("truncate text-caption", DIM)}>{name(kill.victim)}</span>
        </span>
      </li>
    );
  };

  const markRow = (mark: Mark, key: string) => {
    const base = cn("flex h-8 items-center gap-2 rounded-md px-2", future(mark.t) && "opacity-40");
    if (mark.kind === "objective") {
      const { objective } = mark;
      const Icon = OBJECTIVE_ICON[objectiveOf(objective.objective).kind];
      const by = objective.owner ? other(objective.owner) : null;
      return (
        <li
          key={key}
          className={base}
          style={by ? { background: `color-mix(in srgb, ${SEAT[by]} 8%, transparent)` } : undefined}
        >
          <span className={cn("aqt-tnum w-[44px] shrink-0 text-label", FAINT)}>{formatClock(objective.t)}</span>
          <Icon className={cn("size-4 shrink-0", by ? SEAT_TEXT[by] : MUTED)} aria-hidden="true" />
          {by ? <span className={cn("truncate text-caption font-semibold", SEAT_TEXT[by])}>{teamName(by)}</span> : null}
          <span className={cn("truncate text-caption", MUTED)}>{t("matches.deadlock.timeline.destroyed", { what: objectiveLabel(objective) })}</span>
        </li>
      );
    }
    const { boss } = mark;
    const stolen = boss.killer && boss.claimer && boss.killer !== boss.claimer;
    return (
      <li
        key={key}
        className={base}
        style={boss.claimer ? { background: `color-mix(in srgb, ${SEAT[boss.claimer]} 8%, transparent)` } : undefined}
      >
        <span className={cn("aqt-tnum w-[44px] shrink-0 text-label", FAINT)}>{formatClock(boss.t)}</span>
        <Skull className={cn("size-4 shrink-0", boss.claimer ? SEAT_TEXT[boss.claimer] : MUTED)} aria-hidden="true" />
        {boss.claimer ? <span className={cn("truncate text-caption font-semibold", SEAT_TEXT[boss.claimer])}>{teamName(boss.claimer)}</span> : null}
        <span className={cn("truncate text-caption", MUTED)}>
          {t(stolen ? "matches.deadlock.timeline.midBossStolen" : "matches.deadlock.timeline.midBossTaken")}
        </span>
      </li>
    );
  };

  return (
    <ol className="m-0 lg:columns-2 lg:gap-3">
      {blocks.map((block, index) => {
        const group = block.group;
        const isCurrent = index === current;
        const span = group ? (group.from === group.to ? formatClock(group.from) : `${formatClock(group.from)}\u2013${formatClock(group.to)}`) : null;
        return (
          <Card
            asChild
            key={index}
            className={cn(
              "mb-3 break-inside-avoid p-2 transition-colors",
              isCurrent && "border-[color:var(--aqt-border-3)] bg-[color:var(--aqt-overlay-3)]",
              group && future(group.from) && "border-dashed"
            )}
          >
            <li aria-current={isCurrent ? "true" : undefined}>
              {group ? (
                <div className="flex items-center gap-2 px-2 pb-1.5 pt-1">
                  {group.no !== null ? <Crosshair className="size-4 shrink-0 text-[color:var(--aqt-fg-muted)]" aria-hidden /> : null}
                  <h3 className="text-ui font-semibold">
                    {group.no !== null ? t("matches.timeline.fight", { n: group.no }) : t("matches.deadlock.timeline.picks")}
                  </h3>
                  <Button
                    type="button"
                    variant="link"
                    size="inline"
                    onClick={() => onTime(group.to)}
                    aria-label={t("matches.deadlock.timeline.show", { time: span ?? "" })}
                    className="aqt-tnum text-caption"
                  >
                    {span}
                  </Button>
                  <span className="ms-auto text-body font-semibold">
                    <PairScore home={group.home} away={group.away} winner={group.winner} loseClass={FAINT} className={group.winner ? undefined : FAINT} />
                  </span>
                </div>
              ) : null}
              <ul className="m-0 grid">
                {block.rows.map((row, i) => (row.kind === "kill" ? killRow(row.kill, `${index}-k${i}`) : markRow(row, `${index}-m${i}`)))}
              </ul>
            </li>
          </Card>
        );
      })}
    </ol>
  );
}
