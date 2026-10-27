import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Crosshair, Crown, Flame, Timer, Zap, type LucideIcon } from "lucide-react";

import { RecordContext, RecordHolder, useRecordFigure } from "@/app/(site)/statistics/_components/records";
import { HandleLabel } from "@/components/HandleLabel";
import { MoreLink, OpenEmptyRow, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { ServerGameScopeNotice } from "@/components/workspace/ServerGameScopeNotice";
import type { Formatter } from "@/lib/datetime";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug, splitHandle } from "@/lib/player";
import { resolveServerPageGame } from "@/lib/site/discipline-server";
import { cn, initials } from "@/lib/utils";
import statisticsService from "@/services/statistics.service";
import userService from "@/services/user.service";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { PlayerStatistics, StatRecord } from "@/types/statistics.types";
import type { UserProfile } from "@/types/user.types";

import { LEADER_RECORDS } from "./home-records";
import { NumbersReveal } from "./NumbersReveal";
import styles from "./PlatformLeaders.module.css";
import numbers from "./PlatformNumbers.module.css";

const TITLE_ID = "home-leaders-title";
const TOP = 5;
const PODIUM = 3;
const GRID_CLASS =
  "mt-8 grid grid-cols-1 items-start gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]";
const RECORDS_CLASS = "mt-[18px] grid grid-cols-1 gap-3 sm:grid-cols-2";

/** By place: #1 stands in the middle, #2 on its left, #3 on its right. */
const PLACE_CLASS = [styles.p1, styles.p2, styles.p3];

type LeaderRecord = (typeof LEADER_RECORDS)[number];

const RECORD_LOOK: Record<LeaderRecord, { icon: LucideIcon; hue: string }> = {
  win_streak: { icon: Flame, hue: "var(--aqt-teal)" },
  biggest_upset: { icon: Zap, hue: "var(--aqt-amber)" },
  eliminations: { icon: Crosshair, hue: "var(--aqt-rose)" },
  longest_map: { icon: Timer, hue: "var(--aqt-blue)" }
};

/**
 * A slice of the almanac for the landing: the players with the most titles on a podium (#4–5 as rows under it)
 * beside four records of the platform. Titles span every game under "all games" and the game's own under one
 * (spec §6.5). The records, and the podium's main characters and careers, are one game's: the page's, or under all
 * games the first one installed, named in the records' line. An invalid or empty game reads nothing and shows its
 * notice, never another game's. Each read fails soft: its board says so, a profile leaves the player's initial.
 */
export async function PlatformLeaders({ discipline }: Readonly<{ discipline: string | string[] | undefined }>) {
  const { init, resolution } = await resolveServerPageGame("multi", discipline);
  const page = resolution?.game ?? null;
  const boards = page?.kind === "all" || page?.kind === "game";
  const game = page?.kind === "game" ? page.code : null;
  const installed = init.disciplines ?? [];
  const recordGame = !boards
    ? null
    : (installed.find((entry) => (game === null ? entry.enabled : entry.code === game)) ?? null);

  const [t, format, champions, records] = await Promise.all([
    getTranslations("home.leaders"),
    getFormatter(),
    boards ? statisticsService.getChampions(game, { skipWorkspace: true }).catch(() => null) : null,
    recordGame
      ? statisticsService.getRecords(recordGame.code, { skipWorkspace: true }).catch(() => null)
      : null
  ]);
  const top = champions === null ? null : champions.results.slice(0, TOP);
  const profiles = await Promise.all(
    (top ?? [])
      .slice(0, PODIUM)
      .map((player) =>
        recordGame ? userService.getUserProfile(player.id, recordGame.code, "all").catch(() => null) : null
      )
  );

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("title")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={
          <MoreLink href="/statistics" className="min-h-11 whitespace-nowrap">
            {t("more")}
          </MoreLink>
        }
      />
      <ServerGameScopeNotice initial={init} />
      {boards ? (
        <NumbersReveal className={GRID_CLASS}>
          <div className="min-w-0">
            <BoardHead title={t("mostWins")} sub={t("winsSub")} />
            {top === null ? (
              <OpenLoadError />
            ) : top.length === 0 ? (
              <OpenEmptyRow />
            ) : (
              <Podium players={top} profiles={profiles} format={format} />
            )}
          </div>
          {recordGame ? (
            <div className="min-w-0">
              <BoardHead
                title={t("records")}
                sub={t("recordsSub", { game: recordGame.name })}
                aside={
                  // The game's own records page, at its records section.
                  <MoreLink
                    href={`/statistics?discipline=${encodeURIComponent(recordGame.code)}#records`}
                    className="whitespace-nowrap"
                  >
                    {t("allRecords")}
                  </MoreLink>
                }
              />
              <Records records={records === null ? null : records.records} format={format} />
            </div>
          ) : null}
        </NumbersReveal>
      ) : null}
    </Section>
  );
}

function BoardHead({ title, sub, aside }: Readonly<{ title: string; sub: string; aside?: ReactNode }>) {
  return (
    <div className="flex items-end justify-between gap-4 border-b border-[color:var(--aqt-border)] pb-3.5">
      <div className="min-w-0">
        <h3 className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]">{title}</h3>
        <p className="mt-1 text-caption text-[color:var(--aqt-fg-muted)]">{sub}</p>
      </div>
      {aside}
    </div>
  );
}

/**
 * The top three on a podium in medal colours, the title counts on the steps, then #4–5 as rows with a bar scaled to
 * the leader. A podium player shows their main character and career when their profile was read.
 */
function Podium({
  players,
  profiles,
  format
}: Readonly<{ players: PlayerStatistics[]; profiles: (UserProfile | null)[]; format: Formatter }>) {
  const t = useTranslations("home.leaders");
  const leader = players[0].value;

  return (
    <>
      <ol className={styles.podium}>
        {players.slice(0, PODIUM).map((player, index) => {
          const profile = profiles[index] ?? null;
          const portrait = profile?.most_played_character ?? null;
          const { name, suffix } = splitHandle(player.name);
          return (
            <li key={player.id} className={cn(PLACE_CLASS[index], "min-w-0")}>
              <Link
                href={`/users/${getPlayerSlug(player.name)}`}
                prefetch={false}
                title={player.name}
                className={cn(
                  styles.place,
                  "flex flex-col items-center rounded-xl text-center focus-visible:outline-2 focus-visible:outline-offset-[6px] focus-visible:outline-[color:var(--aqt-teal)]"
                )}
              >
                <span className={cn(styles.who, "flex max-w-full flex-col items-center px-1 pb-3.5")}>
                  {index === 0 ? (
                    <Crown
                      aria-hidden
                      className={cn(styles.crown, "mb-1.5 size-[34px] fill-current text-[color:var(--aqt-medal-gold)]")}
                    />
                  ) : null}
                  <Avatar
                    name={player.name}
                    portrait={portrait}
                    title={portrait ? t("main", { name: portrait.name }) : undefined}
                    className={cn("mb-2.5", index === 0 ? "size-[72px] text-headline" : "size-[46px] text-title")}
                  />
                  <span
                    className={cn(
                      "block max-w-full truncate font-display font-bold text-[color:var(--aqt-fg)]",
                      index === 0 ? "text-title" : "text-heading"
                    )}
                  >
                    {name}
                  </span>
                  {suffix ? <span className="mt-0.5 text-label text-[color:var(--aqt-fg-faint)]">{suffix}</span> : null}
                  {profile ? (
                    <span className="mt-1.5 text-label text-[color:var(--aqt-fg-muted)]">
                      {t.rich("career", {
                        tournaments: format.number(profile.tournaments_count),
                        tournamentsCount: profile.tournaments_count,
                        maps: format.number(profile.maps_total),
                        mapsCount: profile.maps_total,
                        b: (chunks) => <b className="font-semibold text-[color:var(--aqt-fg)]">{chunks}</b>
                      })}
                    </span>
                  ) : null}
                </span>
                <span className={styles.slot}>
                  <span className={styles.block}>
                    <span className="flex items-baseline font-display text-display">
                      <b data-count={player.value} className={cn(styles.gradient, "font-extrabold tabular-nums")}>
                        {format.number(player.value)}
                      </b>
                      <span aria-hidden className={cn(styles.times, "font-extrabold")}>×</span>
                    </span>
                    <span className="mt-1.5 text-label text-[color:var(--aqt-fg-muted)]">
                      {t("titles", { count: player.value })}
                    </span>
                    <span aria-hidden className={styles.rank}>
                      {index + 1}
                    </span>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
      {players.length > PODIUM ? (
        <ol start={PODIUM + 1} className={cn(styles.rows, "mt-2.5")}>
          {players.slice(PODIUM).map((player, index) => (
            <li key={player.id} className={styles.rise} style={{ "--d": `${1250 + index * 90}ms` } as CSSProperties}>
              <Link
                href={`/users/${getPlayerSlug(player.name)}`}
                prefetch={false}
                title={player.name}
                className="grid min-h-12 grid-cols-[1.375rem_1.875rem_minmax(0,1fr)_minmax(2.5rem,7.5rem)_2.5rem] items-center gap-3 rounded-[10px] px-3 text-ui transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
              >
                <span className="text-center text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-faint)]">
                  {PODIUM + 1 + index}
                </span>
                <Avatar name={player.name} portrait={null} className="size-[30px] text-caption" />
                <HandleLabel handle={player.name} className="font-semibold text-[color:var(--aqt-fg)]" />
                <span aria-hidden className="block h-1 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
                  <span
                    className={cn(styles.bar, "block h-full rounded-full bg-[color:var(--aqt-teal)]")}
                    style={{ width: `${(player.value / leader) * 100}%` }}
                  />
                </span>
                <span className="text-right font-display text-heading font-bold tabular-nums text-[color:var(--aqt-fg)]">
                  {format.number(player.value)}×
                </span>
              </Link>
            </li>
          ))}
        </ol>
      ) : null}
    </>
  );
}

/** A player's main character, or the first letter of their name when their profile could not tell. */
function Avatar({
  name,
  portrait,
  title,
  className
}: Readonly<{ name: string; portrait: CatalogEntityRead | null; title?: string; className: string }>) {
  return (
    <span
      aria-hidden
      title={title}
      className={cn(
        styles.avatar,
        "relative grid shrink-0 place-items-center overflow-hidden rounded-full font-display font-bold",
        className
      )}
    >
      {portrait?.image_path ? (
        <Image src={portrait.image_path} alt="" fill sizes="72px" className="object-cover" />
      ) : (
        initials(name, 1)
      )}
    </span>
  );
}

/** The leader records the read carries, in their fixed order; one it has no data for is left out. */
function Records({ records, format }: Readonly<{ records: StatRecord[] | null; format: Formatter }>) {
  const t = useTranslations("statistics.records");
  if (records === null) return <OpenLoadError what={t("what")} />;
  const shown = LEADER_RECORDS.flatMap((code) => {
    const record = records.find((entry) => entry.code === code);
    return record ? [{ code, record }] : [];
  });
  if (shown.length === 0) return <OpenEmptyRow>{t("empty")}</OpenEmptyRow>;

  return (
    <ol className={RECORDS_CLASS}>
      {shown.map(({ code, record }, index) => (
        <li key={code} className={cn(styles.rise, "flex")} style={{ "--d": `${150 + index * 120}ms` } as CSSProperties}>
          <RecordCard code={code} record={record} format={format} />
        </li>
      ))}
    </ol>
  );
}

/**
 * One record on the bento's lit surface: its name, the figure counting up (as `/statistics` writes it), the holder
 * and where it happened. The win streak lights a pip per series won; a map record shows the map's still behind.
 */
function RecordCard({ code, record, format }: Readonly<{ code: LeaderRecord; record: StatRecord; format: Formatter }>) {
  const t = useTranslations("statistics.records");
  const { figure, unit } = useRecordFigure(record, format);
  const { icon: Icon, hue } = RECORD_LOOK[code];
  const still = record.map?.image_path ?? null;

  return (
    <article
      className={cn(numbers.tile, "flex min-h-[13.375rem] min-w-0 flex-1 flex-col px-5 py-[18px]")}
      style={{ "--hue": hue } as CSSProperties}
    >
      {still ? (
        <span aria-hidden className={cn(styles.still, "absolute inset-0 -z-10 overflow-hidden")}>
          <Image
            src={still}
            alt=""
            fill
            sizes="(min-width: 1024px) 22rem, (min-width: 640px) 50vw, 100vw"
            className="object-cover saturate-[0.85]"
          />
        </span>
      ) : null}
      <div className="flex items-center gap-2.5">
        <span className="grid size-[30px] shrink-0 place-items-center rounded-lg border border-[color:color-mix(in_srgb,var(--hue)_25%,transparent)] bg-[color:color-mix(in_srgb,var(--hue)_13%,transparent)] text-[color:var(--hue)]">
          <Icon aria-hidden className="size-[15px]" />
        </span>
        <Eyebrow as="h4" tone="muted">
          {t(`code.${code}`)}
        </Eyebrow>
      </div>
      <p className="mt-4 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <b
          data-count={record.value}
          data-clock={code === "longest_map" ? "" : undefined}
          className={cn(styles.gradient, "whitespace-nowrap font-display text-display font-extrabold tabular-nums")}
        >
          {figure}
        </b>
        {unit ? <span className="text-caption text-[color:var(--aqt-fg-dim)]">{unit}</span> : null}
      </p>
      {code === "win_streak" ? (
        <span aria-hidden className="mt-3.5 flex gap-1">
          {Array.from({ length: record.value }, (_, index) => (
            <span key={index} className={styles.pip} style={{ "--i": index } as CSSProperties} />
          ))}
        </span>
      ) : null}
      <div className="mt-auto min-w-0 pt-3.5">
        <RecordHolder record={record} className="truncate text-ui font-semibold text-[color:var(--aqt-fg)]" />
        <RecordContext record={record} format={format} className="mt-0.5 line-clamp-2" />
      </div>
    </article>
  );
}

export function PlatformLeadersSkeleton() {
  const t = useTranslations("home.leaders");

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("title")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={
          <MoreLink href="/statistics" className="min-h-11 whitespace-nowrap">
            {t("more")}
          </MoreLink>
        }
      />
      <div aria-hidden className={GRID_CLASS}>
        <div>
          <BoardHeadSkeleton />
          {/* #2, #1, #3: each name over its step. */}
          <div className="grid grid-cols-[1fr_1.14fr_1fr] items-end gap-x-2.5 pt-[18px]">
            {["h-72", "h-[25.5rem]", "h-64"].map((height) => (
              <Skeleton key={height} className={cn("rounded-b-none rounded-t-[var(--aqt-radius)]", height)} />
            ))}
          </div>
          {Array.from({ length: TOP - PODIUM }, (_, index) => (
            <Skeleton key={index} className="mt-2.5 h-12" />
          ))}
        </div>
        <div>
          <BoardHeadSkeleton />
          <div className={RECORDS_CLASS}>
            {LEADER_RECORDS.map((code) => (
              <Skeleton key={code} className="h-[13.375rem] rounded-[var(--aqt-radius)]" />
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}

function BoardHeadSkeleton() {
  return (
    <div className="border-b border-[color:var(--aqt-border)] pb-3.5">
      <Skeleton className="h-6 w-44" />
      <Skeleton className="mt-1 h-5 w-64 max-w-full" />
    </div>
  );
}
