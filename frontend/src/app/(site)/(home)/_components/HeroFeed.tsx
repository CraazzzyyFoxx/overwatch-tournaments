import type { ReactNode } from "react";
import Link from "next/link";
import { Crown, Flame, type LucideIcon, MapIcon, Trophy } from "lucide-react";
import { useTranslations } from "next-intl";

import { RecordContext, RecordFigure, RecordHolder } from "@/app/(site)/statistics/_components/records";
import { Badge } from "@/components/ui/badge";
import Image from "@/components/ui/image";
import type { Formatter } from "@/lib/datetime";
import { getFormatter } from "@/lib/datetime/server";
import { duelSeats, isLobby } from "@/lib/encounter/seats";
import { getEncounterWinner } from "@/lib/encounter/status";
import { loadGameScopeInit } from "@/lib/site/discipline-server";
import { cn } from "@/lib/utils";
import encounterService from "@/services/encounter.service";
import statisticsService from "@/services/statistics.service";
import type { Encounter, EncounterFilters, EncounterTeam, Match } from "@/types/encounter.types";
import type { StatRecord, StatRecordCode } from "@/types/statistics.types";

import { type FeedItem, type FeedKind, HeroFeedRotator } from "./HeroFeedRotator";
import { LEADER_RECORDS } from "./home-records";
import { FEATURED_GLOW } from "./NowOnPlatform";

/** The latest finals read: a handful. */
const FINALS = 6;

const CARD_CLASS = cn(
  "relative isolate block overflow-hidden rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[radial-gradient(130%_120%_at_0%_0%,var(--aqt-card-2),var(--aqt-card)_62%)] px-4 py-3.5 shadow-[inset_0_1px_0_var(--aqt-overlay-3)] transition-[border-color,box-shadow] duration-300",
  FEATURED_GLOW
);

/** A card's first line: its kind, where it comes from, when. */
const TOP_CLASS = "flex min-w-0 items-center gap-2 text-label text-[color:var(--aqt-fg-faint)]";

/** Each kind's tag: its icon and hue. */
const KIND_TAG: Record<FeedKind, { icon: LucideIcon; hue: string }> = {
  won: { icon: Trophy, hue: "[--badge-hue:var(--aqt-medal-gold)]" },
  carried: { icon: Flame, hue: "[--badge-hue:var(--aqt-amber)]" },
  maps: { icon: MapIcon, hue: "[--badge-hue:var(--aqt-blue)]" }
};

/** A record about a title is filed with the finals, a map's length with the maps; the rest are a player's night. */
const RECORD_KIND: Partial<Record<StatRecordCode, FeedKind>> = {
  closest_final: "won",
  biggest_upset: "won",
  underdog_champion: "won",
  longest_map: "maps"
};

/** The newest completed series across every community, by play date; a failed read is none. */
function latestSeries(perPage: number, filters: EncounterFilters & { entities: string[] }) {
  return encounterService
    .getAll(1, "", null, perPage, "played_at", "desc", "all", { status: "completed", ...filters })
    .then((page) => page.results)
    .catch(() => []);
}

/**
 * The first installed game's records (the rule the leaders block follows under
 * all games), less the ones the leaders block features. Without the games, the
 * results-based records alone; a failed read is none.
 */
async function feedRecords(): Promise<StatRecord[]> {
  const game = (await loadGameScopeInit()).disciplines?.find((entry) => entry.enabled);
  const data = await statisticsService.getRecords(game?.code ?? null, { skipWorkspace: true }).catch(() => null);
  return data?.records.filter((record) => !LEADER_RECORDS.some((code) => code === record.code)) ?? [];
}

/** A duel's two seats, the winner first; `decided` is false on a draw. */
interface Duel {
  won: EncounterTeam;
  lost: EncounterTeam;
  decided: boolean;
}

/** `null` for a lobby or an empty seat. */
function duel(encounter: Encounter): Duel | null {
  const [one, two] = duelSeats(encounter.teams);
  if (isLobby(encounter) || !one || !two) return null;
  const winner = getEncounterWinner(encounter);
  return winner === 2 ? { won: two, lost: one, decided: true } : { won: one, lost: two, decided: winner === 1 };
}

/**
 * The hero's feed, read on the server and handed to the rotator: the latest
 * finals (who won), the records the leaders block leaves out (who carried) and
 * the latest series with parsed logs, by its map stills (which maps). Finals
 * and records take turns, the maps card third. Each read fails on its own and
 * only drops its cards; with none left there is no feed.
 */
export async function HeroFeed() {
  const [format, finals, played, records] = await Promise.all([
    getFormatter(),
    latestSeries(FINALS, { is_final: true, entities: ["tournament", "teams"] }),
    latestSeries(1, { has_logs: true, entities: ["tournament", "teams", "matches", "matches.map"] }),
    feedRecords()
  ]);

  const latest = played.at(0);
  const latestDuel = latest ? duel(latest) : null;
  const maps = (latest?.matches ?? [])
    .filter((match) => match.map)
    .sort((left, right) => (left.map_index ?? -1) - (right.map_index ?? -1) || left.id - right.id);
  const mapsItem: FeedItem | null =
    latest && latestDuel && maps.length > 0
      ? {
          key: `maps-${latest.id}`,
          kind: "maps",
          card: <MapsCard encounter={latest} seats={latestDuel} maps={maps} format={format} />
        }
      : null;

  const finalItems = finals.flatMap((encounter): FeedItem[] => {
    const seats = duel(encounter);
    // The latest series can be a final: it shows once, as the maps card.
    if (!seats?.decided || (mapsItem && encounter.id === latest?.id)) return [];
    return [
      { key: `final-${encounter.id}`, kind: "won", card: <FinalCard encounter={encounter} seats={seats} format={format} /> }
    ];
  });
  const recordItems = records.map((record): FeedItem => {
    const kind = RECORD_KIND[record.code] ?? "carried";
    return { key: `record-${record.code}`, kind, card: <RecordCard record={record} kind={kind} format={format} /> };
  });

  const items = Array.from({ length: Math.max(finalItems.length, recordItems.length) }, (_, index) => [
    finalItems[index],
    recordItems[index]
  ])
    .flat()
    .filter((item) => item !== undefined);
  if (mapsItem) items.splice(2, 0, mapsItem);

  return items.length === 0 ? null : <HeroFeedRotator items={items} />;
}

function Tag({ kind, children }: Readonly<{ kind: FeedKind; children: ReactNode }>) {
  const { icon: Icon, hue } = KIND_TAG[kind];
  return (
    <Badge palette="aqt" voice="label" size="sm" className={cn("flex-none py-[3px] [&_svg]:size-3", hue)}>
      <Icon aria-hidden />
      {children}
    </Badge>
  );
}

/** When the series was played; imported history without a trustworthy stamp falls back to its tournament's end. */
function PlayedOn({ encounter, format }: Readonly<{ encounter: Encounter; format: Formatter }>) {
  const at = new Date(encounter.played_at ?? encounter.tournament.end_date);
  return (
    <time dateTime={at.toISOString()} className="ml-auto flex-none">
      {format.dateTime(at, { day: "numeric", month: "short" })}
    </time>
  );
}

/** A final: the champion first under a crown, the series score with the winner's side teal. One link, to the series. */
function FinalCard({ encounter, seats, format }: Readonly<{ encounter: Encounter; seats: Duel; format: Formatter }>) {
  const t = useTranslations("home.hero.feed");
  return (
    <Link href={`/encounters/${encounter.id}`} prefetch={false} className={CARD_CLASS}>
      <span className={TOP_CLASS}>
        <Tag kind="won">{t("final")}</Tag>
        <span className="min-w-0 truncate">{encounter.tournament.name}</span>
        <PlayedOn encounter={encounter} format={format} />
      </span>
      <span className="mt-2.5 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 font-display text-heading font-semibold">
        <span className="flex min-w-0 items-center gap-1.5 text-[color:var(--aqt-fg)]">
          <Crown aria-hidden className="size-4 flex-none text-[color:var(--aqt-medal-gold)]" />
          <span className="sr-only">{t("winner")}</span>
          <span className="truncate">{seats.won.name}</span>
        </span>
        <Score won={seats.won} lost={seats.lost} className="text-title" />
        <span className="truncate text-right text-[color:var(--aqt-fg-muted)]">{seats.lost.name}</span>
      </span>
    </Link>
  );
}

/** Teal for the winner's side, muted for the loser's (DESIGN: colour the score). */
function Score({ won, lost, className }: Readonly<{ won: EncounterTeam; lost: EncounterTeam; className: string }>) {
  return (
    <b className={cn("whitespace-nowrap font-display font-bold tabular-nums", className)}>
      <span className="text-[color:var(--aqt-teal)]">{won.score}</span>
      <span className="mx-[0.12em] text-[color:var(--aqt-fg-faint)]">:</span>
      <span className="text-[color:var(--aqt-fg-muted)]">{lost.score}</span>
    </b>
  );
}

/**
 * A record, as `/statistics` words it: the figure, its holder and where it
 * happened. Not a link itself, since its holder and context are. A record on
 * one map carries that map's still on the right.
 */
function RecordCard({ record, kind, format }: Readonly<{ record: StatRecord; kind: FeedKind; format: Formatter }>) {
  const t = useTranslations("home.hero.feed");
  const tRecords = useTranslations("statistics.records");
  const still = record.map?.image_path;
  return (
    <div className={cn(CARD_CLASS, still && "sm:pr-36")}>
      {still ? (
        <span
          aria-hidden
          className="absolute inset-y-0 right-0 -z-10 w-[46%] opacity-55 [mask-image:linear-gradient(90deg,transparent,var(--aqt-bg)_75%)] sm:w-[210px] sm:opacity-80"
        >
          <Image src={still} alt="" fill sizes="210px" className="object-cover" />
        </span>
      ) : null}
      <span className={TOP_CLASS}>
        <Tag kind={kind}>{t("record")}</Tag>
        <span className="min-w-0 truncate">{tRecords(`code.${record.code}`)}</span>
      </span>
      <RecordFigure record={record} format={format} size="lg" />
      <RecordHolder record={record} className="mt-1 truncate text-body font-semibold text-[color:var(--aqt-fg)]" />
      <RecordContext record={record} format={format} className="mt-0.5 truncate" />
    </div>
  );
}

/** The latest series with parsed logs: the matchup and score, then a still per map in play order. One link, to the series. */
function MapsCard({
  encounter,
  seats,
  maps,
  format
}: Readonly<{ encounter: Encounter; seats: Duel; maps: Match[]; format: Formatter }>) {
  const t = useTranslations("home.hero.feed");
  return (
    <Link href={`/encounters/${encounter.id}`} prefetch={false} className={cn(CARD_CLASS, "group")}>
      <span className={TOP_CLASS}>
        <Tag kind="maps">{t("maps")}</Tag>
        <span className="min-w-0 truncate">{encounter.tournament.name}</span>
        <PlayedOn encounter={encounter} format={format} />
      </span>
      <span className="mt-2 flex min-w-0 items-baseline gap-2 text-body text-[color:var(--aqt-fg-muted)]">
        <span className="min-w-0 truncate">
          {t.rich("matchup", {
            winner: seats.won.name,
            loser: seats.lost.name,
            won: (chunks) =>
              seats.decided ? <span className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</span> : chunks
          })}
        </span>
        <Score won={seats.won} lost={seats.lost} className="flex-none text-heading" />
      </span>
      <span className="mt-2.5 flex gap-1.5">
        {maps.map((match) => (
          <span
            key={match.id}
            className="relative aspect-[16/10] min-w-0 flex-1 overflow-hidden rounded-[var(--aqt-radius-sm)] bg-[color:var(--aqt-card-2)]"
          >
            {match.map?.image_path ? (
              <Image src={match.map.image_path} alt="" fill sizes="120px" className="aqt-zoom object-cover" />
            ) : null}
            <span className="absolute inset-0 bg-gradient-to-b from-transparent from-40% to-[color:color-mix(in_srgb,var(--aqt-bg)_80%,transparent)]" />
            <span className="absolute inset-x-1.5 bottom-1 truncate text-label font-semibold text-[color:var(--aqt-fg)]">
              {match.map?.name}
            </span>
          </span>
        ))}
      </span>
    </Link>
  );
}
