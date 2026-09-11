"use client";

import { useId } from "react";
import { useFormatter, useTranslations } from "next-intl";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { MixMemberStats } from "@/services/custom-game.service";

import { LINEUP_ROLES } from "./pickup-lineup";
import {
  LEADERBOARD_MIN_GAMES,
  STATS_PERIODS,
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
      <div className="space-y-4 border-b border-[color:var(--aqt-border)] p-4">
        <div className="space-y-2">
          <h2
            id={`${id}-title`}
            className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]"
          >
            {t("title")}
          </h2>
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t("rules", { limit: LEADERBOARD_LIMIT, minGames: LEADERBOARD_MIN_GAMES })}
          </p>
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("ranking")}</p>
        </div>
        <div className="space-y-2">
          <label
            htmlFor={`${id}-period`}
            className="block text-caption font-medium text-[color:var(--aqt-fg)]"
          >
            {t("period")}
          </label>
          <select
            id={`${id}-period`}
            value={period}
            onChange={(event) => onPeriodChange(event.target.value as StatsPeriodKey)}
            className="min-h-11 w-full min-w-0 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-3 text-base text-[color:var(--aqt-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
          >
            {STATS_PERIODS.map(({ key }) => (
              <option key={key} value={key}>
                {t(`periods.${key}`)}
              </option>
            ))}
          </select>
        </div>
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
            <div key={row} className="space-y-3 p-4">
              <Skeleton className="h-5 w-3/4 motion-reduce:animate-none" />
              <Skeleton className="h-9 w-1/2 motion-reduce:animate-none" />
              <Skeleton className="h-5 w-2/3 motion-reduce:animate-none" />
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
        <ol aria-labelledby={`${id}-title`} className="divide-y divide-[color:var(--aqt-border)]">
          {members.slice(0, LEADERBOARD_LIMIT).map((member, index) => (
            <LeaderboardRow key={member.workspace_member_id} rank={index + 1} member={member} />
          ))}
        </ol>
      )}
    </section>
  );
}

function LeaderboardRow({ rank, member }: Readonly<{ rank: number; member: MixMemberStats }>) {
  const t = useTranslations("mixes.leaderboard");
  const format = useFormatter();
  const name = memberLabel(member);

  return (
    <li className="min-w-0 space-y-3 px-4 py-4 text-body text-[color:var(--aqt-fg)]">
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
          #{format.number(rank)}
        </span>
        <h3 className="min-w-0 text-ui font-semibold [overflow-wrap:anywhere]">
          <bdi>{name}</bdi>
        </h3>
      </div>
      <dl className="grid grid-cols-2 gap-3">
        <div>
          <dt className="text-caption text-[color:var(--aqt-fg-muted)]">{t("wins")}</dt>
          <dd className="text-ui font-semibold tabular-nums">{format.number(member.wins)}</dd>
        </div>
        <div>
          <dt className="text-caption text-[color:var(--aqt-fg-muted)]">{t("winRate")}</dt>
          <dd className="text-ui font-semibold tabular-nums">
            {format.number(member.win_rate, { style: "percent", maximumFractionDigits: 0 })}
          </dd>
        </div>
      </dl>
      <details>
        <summary
          aria-label={t("details", { name })}
          className="min-h-11 cursor-pointer content-center rounded-sm py-2 text-caption text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] [overflow-wrap:anywhere]"
        >
          {t("showDetails")}
        </summary>
        <div className="space-y-4 pt-3">
          <dl className="grid grid-cols-2 gap-3">
            {(["losses", "draws", "games"] as const).map((metric) => (
              <div key={metric}>
                <dt className="text-caption text-[color:var(--aqt-fg-muted)]">{t(metric)}</dt>
                <dd className="tabular-nums">{format.number(member[metric])}</dd>
              </div>
            ))}
            <div className="col-span-2">
              <dt className="text-caption text-[color:var(--aqt-fg-muted)]">{t("streak")}</dt>
              <dd className="tabular-nums">
                {member.streak === 0
                  ? t("noStreak")
                  : t(member.streak > 0 ? "winStreak" : "lossStreak", {
                      count: Math.abs(member.streak)
                    })}
              </dd>
            </div>
          </dl>
          {LINEUP_ROLES.some((role) => member.by_role[role] != null) ? (
            <div className="space-y-3">
              <h4 className="text-caption font-semibold">{t("roles")}</h4>
              {LINEUP_ROLES.map((role) => {
                const tally = member.by_role[role];
                if (tally == null) return null;
                return (
                  <section key={role} aria-label={t(role)} className="space-y-1">
                    <h5 className="text-caption font-medium">{t(role)}</h5>
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
                      {(["wins", "losses", "draws", "games"] as const).map((metric) => (
                        <div key={metric}>
                          <dt className="text-caption text-[color:var(--aqt-fg-muted)]">
                            {t(metric)}
                          </dt>
                          <dd className="text-caption tabular-nums">
                            {format.number(tally[metric])}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                );
              })}
            </div>
          ) : null}
        </div>
      </details>
    </li>
  );
}
