"use client";

import { useId } from "react";
import { useFormatter, useTranslations } from "next-intl";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import { PageStateCard } from "@/components/ui/page-state-card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { MixMemberStats } from "@/services/custom-game.service";

import {
  LEADERBOARD_MIN_GAMES,
  STATS_PERIODS,
  formatStreak,
  memberLabel,
  type StatsPeriodKey
} from "./pickup-stats";

const LEADERBOARD_LIMIT = 20;

type PickupLeaderboardProps = {
  /** Already filtered and ranked by the caller — rendered in the order given. */
  members: MixMemberStats[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  period: StatsPeriodKey;
  onPeriodChange: (period: StatsPeriodKey) => void;
};

/**
 * Who is winning in this community, as a scannable table: rank, player, matches
 * played, wins, win rate. Everything a row has to say is on the row — the board
 * answers one question, and a per-player breakdown behind a disclosure made a
 * reader open twenty of them to compare two numbers.
 */
export function PickupLeaderboard({
  members,
  loading,
  error,
  onRetry,
  period,
  onPeriodChange
}: Readonly<PickupLeaderboardProps>) {
  const t = useTranslations("mixes.leaderboard");
  const common = useTranslations("common");
  const id = useId();

  return (
    <section aria-labelledby={`${id}-title`} className={cn(PANEL_CLASS, "w-full min-w-0")}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <div className="min-w-0">
          <h2
            id={`${id}-title`}
            className="font-display text-ui font-semibold text-[color:var(--aqt-fg)]"
          >
            {t("title")}
          </h2>
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t("rules", { limit: LEADERBOARD_LIMIT, minGames: LEADERBOARD_MIN_GAMES })}
          </p>
        </div>
        <Select value={period} onValueChange={(value) => onPeriodChange(value as StatsPeriodKey)}>
          <SelectTrigger
            aria-label={t("period")}
            className="h-8 w-auto shrink-0 gap-1.5 border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] text-caption text-[color:var(--aqt-fg-muted)] shadow-none"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATS_PERIODS.map(({ key }) => (
              <SelectItem key={key} value={key} className="text-caption">
                {t(`periods.${key}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <p role="status" className="sr-only">
        {loading && !error ? t("loading") : ""}
      </p>
      {error ? (
        <PageStateCard
          state="error"
          title={t("errorTitle")}
          description={t("errorDescription")}
          actionLabel={common("retry")}
          onAction={onRetry}
          className="border-0 bg-transparent px-4 py-10"
        />
      ) : loading ? (
        <div aria-hidden="true" className="divide-y divide-[color:var(--aqt-border)]">
          {[0, 1, 2, 3, 4].map((row) => (
            <div key={row} className="flex items-center gap-3 px-4 py-2.5">
              <Skeleton className="h-4 w-full motion-reduce:animate-none" />
              <Skeleton className="h-4 w-10 shrink-0 motion-reduce:animate-none" />
            </div>
          ))}
        </div>
      ) : members.length === 0 ? (
        <PageStateCard
          state={period === "all" ? "empty" : "filtered-empty"}
          title={t("emptyTitle")}
          description={t("emptyDescription", { minGames: LEADERBOARD_MIN_GAMES })}
          actionLabel={t("allTime")}
          onAction={period === "all" ? undefined : () => onPeriodChange("all")}
          className="border-0 bg-transparent px-4 py-10"
        />
      ) : (
        <table className="w-full table-fixed border-collapse">
          <caption className="sr-only">{t("ranking")}</caption>
          <thead>
            <tr className="whitespace-nowrap text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              <th scope="col" className="px-4 py-2 text-start font-medium">
                {t("player")}
              </th>
              <th scope="col" className="w-20 px-1 py-2 text-end font-medium">
                {t("wins")}
              </th>
              <th scope="col" className="w-[5.5rem] py-2 pe-4 ps-1 text-end font-medium">
                {t("winRate")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[color:var(--aqt-border)] border-t border-[color:var(--aqt-border)]">
            {members.slice(0, LEADERBOARD_LIMIT).map((member, index) => (
              <LeaderboardRow key={member.workspace_member_id} rank={index + 1} member={member} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function LeaderboardRow({ rank, member }: Readonly<{ rank: number; member: MixMemberStats }>) {
  const t = useTranslations("mixes.leaderboard");
  const list = useTranslations("mixes.list");
  const format = useFormatter();
  const name = memberLabel(member);
  const streak = formatStreak(member.streak);

  return (
    <tr className="text-body text-[color:var(--aqt-fg)]">
      <th scope="row" className="min-w-0 px-4 py-2 text-start font-normal">
        <span className="flex min-w-0 items-center gap-2">
          <span className="w-4 shrink-0 text-caption tabular-nums text-[color:var(--aqt-fg-faint)]">
            {format.number(rank)}
          </span>
          <span title={name} className="min-w-0 truncate text-ui font-medium">
            <bdi>{name}</bdi>
          </span>
          {streak ? (
            <span
              className={cn(
                "shrink-0 rounded px-1 text-label font-semibold tabular-nums",
                member.streak > 0
                  ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)] text-[color:var(--aqt-teal)]"
                  : "bg-[color:color-mix(in_srgb,var(--aqt-rose)_14%,transparent)] text-[color:var(--aqt-rose)]"
              )}
            >
              <span className="sr-only">
                {t(member.streak > 0 ? "winStreak" : "lossStreak", {
                  count: Math.abs(member.streak)
                })}
              </span>
              <span aria-hidden="true">{streak}</span>
            </span>
          ) : null}
        </span>
      </th>
      <td className="px-1 py-2 text-end tabular-nums">
        {/* `17 / 24` reads as a record at a glance; a screen reader gets the
            same two numbers named, since a slash says nothing out loud. */}
        <span aria-hidden="true">
          <span className="font-semibold">{format.number(member.wins)}</span>
          <span className="text-[color:var(--aqt-fg-faint)]">
            {" / "}
            {format.number(member.games)}
          </span>
        </span>
        <span className="sr-only">
          {format.number(member.wins)}
          {", "}
          {list("matches", { count: member.games })}
        </span>
      </td>
      <td className="pe-4 ps-1 py-2 text-end tabular-nums text-[color:var(--aqt-fg-muted)]">
        {format.number(member.win_rate, { style: "percent", maximumFractionDigits: 0 })}
      </td>
    </tr>
  );
}
