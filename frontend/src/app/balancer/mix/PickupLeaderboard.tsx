"use client";

import { useId, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { CARD_TITLE_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { HandleLabel } from "@/components/HandleLabel";
import { formatRelative } from "@/components/kit/format-time";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { FormStreak } from "@/components/profile/atoms";
import { Card } from "@/components/ui/card";
import { DataPagination } from "@/components/ui/data-pagination";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { PageStateCard } from "@/components/ui/page-state-card";
import { SearchField } from "@/components/ui/search-field";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { useFormatter } from "@/lib/datetime/client";
import type { RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { MixOutcome } from "@/services/custom-game.service";

import {
  LEADERBOARD_MIN_GAMES,
  STATS_PERIODS,
  formatStreak,
  type RatedPlayer,
  type StatsPeriodKey
} from "./pickup-stats";

const RAIL_LIMIT = 10;
const TABLE_PAGE_SIZE = 50;
const LETTER: Record<MixOutcome, "W" | "L" | "D"> = { win: "W", loss: "L", draw: "D" };

type BoardProps = {
  /** Eligible players (at least `LEADERBOARD_MIN_GAMES`), best first. */
  ranked: RatedPlayer[];
  /** The signed-in reader's own row, ranked or not; `null` when they have none. */
  viewer: RatedPlayer | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  period: StatsPeriodKey;
  onPeriodChange: (period: StatsPeriodKey) => void;
  /** The board joins several communities. */
  allCommunities: boolean;
  /** The one game's roles; `null` across games, where nobody has one main role. */
  ontology: RoleOntology | null;
};

function PeriodToggle({
  period,
  onPeriodChange,
  className
}: Readonly<{ period: StatsPeriodKey; onPeriodChange: (period: StatsPeriodKey) => void; className?: string }>) {
  const t = useTranslations("mixes.leaderboard");
  return (
    <ToggleGroup
      variant="pill"
      size="sm"
      value={period}
      onValueChange={(value) => onPeriodChange(value as StatsPeriodKey)}
      aria-label={t("period")}
      className={className}
    >
      {STATS_PERIODS.map(({ key }) => (
        <ToggleGroupItem key={key} value={key} className="flex-1 whitespace-nowrap">
          {t(`periods.${key}`)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** The role with the most games: the one icon a row has room for. */
function mainRole(player: RatedPlayer): string | null {
  let best: string | null = null;
  let games = 0;
  for (const [role, tally] of Object.entries(player.byRole ?? {})) {
    if (tally.games > games) {
      best = role;
      games = tally.games;
    }
  }
  return best;
}

function PlayerName({
  player,
  ontology,
  you
}: Readonly<{ player: RatedPlayer; ontology: RoleOntology | null; you: boolean }>) {
  const t = useTranslations("mixes.leaderboard");
  const role = ontology ? mainRole(player) : null;
  return (
    <span className="flex min-w-0 items-center gap-2">
      {role ? <PlayerRoleIcon role={role} ontology={ontology} size={16} /> : null}
      <HandleLabel handle={player.name} title={player.name} className="font-medium text-[color:var(--aqt-fg)]" />
      {you ? (
        <span className="shrink-0 text-caption font-semibold text-[color:var(--aqt-teal)]">{t("you")}</span>
      ) : null}
    </span>
  );
}

/** `12/18` reads as a record at a glance; a screen reader gets the two numbers named. */
function WinsOf({ player }: Readonly<{ player: RatedPlayer }>) {
  const t = useTranslations("mixes.leaderboard");
  const format = useFormatter();
  return (
    <>
      <span aria-hidden="true">
        <span className="font-semibold text-[color:var(--aqt-fg)]">{format.number(player.wins)}</span>
        <span className="text-[color:var(--aqt-fg-faint)]">/{format.number(player.games)}</span>
      </span>
      <span className="sr-only">{t("winsOf", { wins: player.wins, games: player.games })}</span>
    </>
  );
}

function WinRate({ player }: Readonly<{ player: RatedPlayer }>) {
  const t = useTranslations("mixes.leaderboard");
  const format = useFormatter();
  const low = player.games < LOW_SAMPLE_GAMES;
  return (
    <span
      title={low ? t("lowSample", { games: LOW_SAMPLE_GAMES }) : undefined}
      className="font-semibold tabular-nums"
      style={{ color: winrateColor(player.winRate * 100, low) }}
    >
      {format.number(player.winRate, { style: "percent", maximumFractionDigits: 0 })}
    </span>
  );
}

function Form({ player, count }: Readonly<{ player: RatedPlayer; count: number }>) {
  if (player.form.length === 0) return null;
  return <FormStreak results={player.form.slice(0, count).map((outcome) => LETTER[outcome])} />;
}

function Streak({ player }: Readonly<{ player: RatedPlayer }>) {
  const t = useTranslations("mixes.leaderboard");
  const label = formatStreak(player.streak, player.streakOpen);
  if (!label) return null;
  const count = Math.abs(player.streak);
  return (
    <IconTooltip
      label={t(player.streak > 0 ? "winStreak" : "lossStreak", { count })}
      className={cn(
        "justify-end font-semibold tabular-nums",
        player.streak > 0 ? "text-[color:var(--aqt-emerald)]" : "text-[color:var(--aqt-rose)]"
      )}
    >
      <span aria-hidden="true">{label}</span>
    </IconTooltip>
  );
}

function BoardState({
  loading,
  error,
  onRetry,
  empty,
  period,
  onPeriodChange,
  rows
}: Readonly<{
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  empty: boolean;
  period: StatsPeriodKey;
  onPeriodChange: (period: StatsPeriodKey) => void;
  rows: number;
}>) {
  const t = useTranslations("mixes.leaderboard");
  const common = useTranslations("common");
  if (error) {
    return (
      <PageStateCard
        state="error"
        title={t("errorTitle")}
        description={t("errorDescription")}
        actionLabel={common("retry")}
        onAction={onRetry}
        className="border-0 bg-transparent px-4 py-10"
      />
    );
  }
  if (loading) {
    return (
      <div aria-hidden="true" className="divide-y divide-[color:var(--aqt-border)]">
        {Array.from({ length: rows }, (_, row) => (
          <div key={row} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="h-4 w-5 shrink-0 motion-reduce:animate-none" />
            <Skeleton className="h-4 flex-1 motion-reduce:animate-none" />
            <Skeleton className="h-4 w-16 shrink-0 motion-reduce:animate-none" />
          </div>
        ))}
      </div>
    );
  }
  if (!empty) return null;
  return (
    <PageStateCard
      state={period === "all" ? "empty" : "filtered-empty"}
      title={t("emptyTitle")}
      description={t("emptyDescription", { minGames: LEADERBOARD_MIN_GAMES })}
      actionLabel={t("allTime")}
      onAction={period === "all" ? undefined : () => onPeriodChange("all")}
      className="border-0 bg-transparent px-4 py-10"
    />
  );
}

/**
 * The scoreboard beside the directory: the top ten, and -- when the reader is
 * further down or not yet ranked -- their own row pinned under them, so
 * nobody has to open the full board to find themselves.
 */
export function PickupLeaderboard({
  ranked,
  viewer,
  loading,
  error,
  onRetry,
  period,
  onPeriodChange,
  allCommunities,
  ontology,
  fullHref
}: Readonly<BoardProps & { fullHref: string }>) {
  const t = useTranslations("mixes.leaderboard");
  const id = useId();
  const top = ranked.slice(0, RAIL_LIMIT);
  const viewerRank = viewer ? ranked.findIndex((player) => player.key === viewer.key) + 1 : 0;
  const pinned = viewer && viewerRank !== 0 && viewerRank <= RAIL_LIMIT ? null : viewer;
  const ready = !loading && !error;

  return (
    <Card asChild>
      <section aria-labelledby={`${id}-title`} className="w-full min-w-0">
      <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3.5">
        <div className="min-w-0">
          <h2 id={`${id}-title`} className={CARD_TITLE_CLASS}>
            {t("title")}
          </h2>
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t(allCommunities ? "rulesAll" : "rules", { minGames: LEADERBOARD_MIN_GAMES })}
          </p>
        </div>
        <PeriodToggle period={period} onPeriodChange={onPeriodChange} className="w-full" />
      </div>

      <p role="status" className="sr-only">
        {loading && !error ? t("loading") : ""}
      </p>
      <BoardState
        loading={loading}
        error={error}
        onRetry={onRetry}
        empty={ready && top.length === 0}
        period={period}
        onPeriodChange={onPeriodChange}
        rows={5}
      />
      {ready && top.length > 0 ? (
        <>
          <Table className="table-fixed border-collapse">
            <caption className="sr-only">{t("ranking")}</caption>
            <TableHeader>
              <TableRow className="whitespace-nowrap">
                <TableHead scope="col" className="w-10 py-2 ps-4 pe-0 text-start">
                  <span className="sr-only">{t("rank")}</span>
                </TableHead>
                <TableHead scope="col" className="px-0 py-2 text-start">
                  {t("player")}
                </TableHead>
                <TableHead scope="col" className="hidden w-[6.5rem] py-2 ps-2 pe-0 text-start sm:table-cell xl:hidden 2xl:table-cell">
                  {t("form")}
                </TableHead>
                <TableHead scope="col" className="w-16 px-1 py-2 text-end">
                  {t("wins")}
                </TableHead>
                <TableHead scope="col" className="w-24 py-2 pe-4 ps-1 text-end">
                  {t("winRate")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {top.map((player, index) => (
                <RailRow
                  key={player.key}
                  rank={index + 1}
                  player={player}
                  you={player.key === viewer?.key}
                  ontology={ontology}
                />
              ))}
            </TableBody>
            {pinned ? (
              <TableBody className="border-t-2 border-[color:var(--aqt-border-2)]">
                <RailRow rank={viewerRank || null} player={pinned} you ontology={ontology} />
              </TableBody>
            ) : null}
          </Table>
          {pinned && viewerRank === 0 ? (
            <p className="px-4 pb-1 text-caption text-[color:var(--aqt-fg-dim)]">
              {t("unranked", { games: pinned.games, minGames: LEADERBOARD_MIN_GAMES })}
            </p>
          ) : null}
          <div className="border-t border-[color:var(--aqt-border)] px-4 py-3">
            <Link
              href={fullHref}
              className="inline-flex items-center gap-1.5 rounded-sm text-caption font-semibold text-[color:var(--aqt-teal)] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
            >
              {t("full")}
              <ArrowRight aria-hidden className="size-4" />
            </Link>
          </div>
        </>
      ) : null}
      </section>
    </Card>
  );
}

function RailRow({
  rank,
  player,
  you,
  ontology
}: Readonly<{ rank: number | null; player: RatedPlayer; you: boolean; ontology: RoleOntology | null }>) {
  return (
    <TableRow
      className={cn(
        "text-body",
        you && "bg-[color:color-mix(in_srgb,var(--aqt-teal)_7%,transparent)]"
      )}
    >
      <TableCell className="py-2.5 ps-4 pe-0 text-caption tabular-nums text-[color:var(--aqt-fg-faint)]">
        {rank ? String(rank).padStart(2, "0") : null}
      </TableCell>
      <TableHead scope="row" className="min-w-0 px-0 py-2.5 text-start text-body font-normal normal-case tracking-normal">
        <PlayerName player={player} ontology={ontology} you={you} />
      </TableHead>
      <TableCell className="hidden py-2.5 ps-2 pe-0 sm:table-cell xl:hidden 2xl:table-cell">
        <Form player={player} count={5} />
      </TableCell>
      <TableCell className="px-1 py-2.5 text-end tabular-nums">
        <WinsOf player={player} />
      </TableCell>
      <TableCell className="py-2.5 pe-4 ps-1 text-end">
        <WinRate player={player} />
      </TableCell>
    </TableRow>
  );
}

/**
 * The whole board, for `?view=rating`: every ranked player with their form,
 * streak and last match, searchable by name and paged -- a community with a
 * few hundred regulars does not fit a sidebar.
 */
export function PickupRatingTable({
  ranked,
  viewer,
  loading,
  error,
  onRetry,
  period,
  onPeriodChange,
  allCommunities,
  ontology
}: Readonly<BoardProps>) {
  const t = useTranslations("mixes.leaderboard");
  const format = useFormatter();
  const now = useMinuteClock();
  const id = useId();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const needle = search.trim().toLocaleLowerCase();
  const ranks = new Map(ranked.map((player, index) => [player.key, index + 1]));
  const shown = needle ? ranked.filter((player) => player.name.toLocaleLowerCase().includes(needle)) : ranked;
  const totalPages = Math.max(1, Math.ceil(shown.length / TABLE_PAGE_SIZE));
  const current = Math.min(page, totalPages);
  const rows = shown.slice((current - 1) * TABLE_PAGE_SIZE, current * TABLE_PAGE_SIZE);
  const ready = !loading && !error;

  let body: ReactNode = null;
  if (ready && ranked.length > 0 && shown.length === 0) {
    body = (
      <PageStateCard
        state="filtered-empty"
        title={t("noResultsTitle")}
        description={t("noResultsDescription", { q: search.trim() })}
        actionLabel={t("clearSearch")}
        onAction={() => setSearch("")}
        className="border-0 bg-transparent px-4 py-10"
      />
    );
  } else if (ready && rows.length > 0) {
    body = (
      <div role="region" aria-labelledby={`${id}-title`} tabIndex={0} className="overflow-x-auto focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]">
        <Table className="min-w-[34rem] border-collapse" wrapperClassName="overflow-visible">
          <caption className="sr-only">{t("ranking")}</caption>
          <TableHeader>
            <TableRow className="whitespace-nowrap">
              <TableHead scope="col" className="w-14 py-2.5 ps-4 pe-0 text-start">
                <span className="sr-only">{t("rank")}</span>
              </TableHead>
              <TableHead scope="col" className="px-0 py-2.5 text-start">
                {t("player")}
              </TableHead>
              <TableHead scope="col" className="hidden py-2.5 ps-3 pe-0 text-start lg:table-cell">
                {t("form")}
              </TableHead>
              <TableHead scope="col" className="w-20 py-2.5 text-end">
                {t("wins")}
              </TableHead>
              <TableHead scope="col" className="w-20 py-2.5 text-end">
                {t("winRate")}
              </TableHead>
              <TableHead scope="col" className="hidden w-20 py-2.5 text-end md:table-cell">
                {t("streak")}
              </TableHead>
              <TableHead scope="col" className="hidden w-32 py-2.5 pe-4 text-end md:table-cell">
                {t("lastPlayed")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((player) => {
              const you = player.key === viewer?.key;
              return (
                <TableRow
                  key={player.key}
                  className={cn(
                    "text-body",
                    you && "bg-[color:color-mix(in_srgb,var(--aqt-teal)_7%,transparent)]"
                  )}
                >
                  <TableCell className="py-3 ps-4 pe-0 text-caption tabular-nums text-[color:var(--aqt-fg-faint)]">
                    {String(ranks.get(player.key) ?? 0).padStart(2, "0")}
                  </TableCell>
                  <TableHead
                    scope="row"
                    className="min-w-0 max-w-[16rem] px-0 py-3 text-start text-body font-normal normal-case tracking-normal"
                  >
                    <PlayerName player={player} ontology={ontology} you={you} />
                  </TableHead>
                  <TableCell className="hidden py-3 ps-3 pe-0 lg:table-cell">
                    <Form player={player} count={10} />
                  </TableCell>
                  <TableCell className="py-3 text-end tabular-nums">
                    <WinsOf player={player} />
                  </TableCell>
                  <TableCell className="py-3 text-end">
                    <WinRate player={player} />
                  </TableCell>
                  <TableCell className="hidden py-3 text-end md:table-cell">
                    <Streak player={player} />
                  </TableCell>
                  <TableCell
                    title={
                      player.lastPlayedAt
                        ? format.dateTime(new Date(player.lastPlayedAt), { dateStyle: "medium", timeStyle: "short" })
                        : undefined
                    }
                    className="hidden py-3 pe-4 text-end text-caption tabular-nums text-[color:var(--aqt-fg-dim)] md:table-cell"
                  >
                    {now !== null ? formatRelative(format, player.lastPlayedAt, now) : null}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    );
  }

  return (
    <Card asChild>
      <section aria-labelledby={`${id}-title`} className="w-full min-w-0">
      <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3.5 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <h2 id={`${id}-title`} className={CARD_TITLE_CLASS}>
            {t("title")}
          </h2>
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t(allCommunities ? "rulesAll" : "rules", { minGames: LEADERBOARD_MIN_GAMES })}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {ranked.length > 0 ? (
            <SearchField
              label={t("search")}
              placeholder={t("searchPlaceholder")}
              value={search}
              onValueChange={(value) => {
                setSearch(value);
                setPage(1);
              }}
              containerClassName="w-full sm:w-56"
            />
          ) : null}
          <PeriodToggle period={period} onPeriodChange={onPeriodChange} />
        </div>
      </div>
      <p role="status" className="sr-only">
        {loading && !error ? t("loading") : ""}
      </p>
      <BoardState
        loading={loading}
        error={error}
        onRetry={onRetry}
        empty={ready && ranked.length === 0}
        period={period}
        onPeriodChange={onPeriodChange}
        rows={10}
      />
      {body}
      {ready && totalPages > 1 ? (
        <DataPagination
          page={current}
          totalPages={totalPages}
          onPageChange={setPage}
          className="border-t border-[color:var(--aqt-border)] px-4 py-3"
        />
      ) : null}
      </section>
    </Card>
  );
}
