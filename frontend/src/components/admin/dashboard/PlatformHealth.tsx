"use client";

import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useNow, useTranslations } from "next-intl";
import { CheckCircle2 } from "lucide-react";

import { openMissCountQuery } from "@/app/admin/content/miss-queue";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { collectsRanks, rankHealthDot } from "@/components/admin/collectors/rank-shared";
import { diagnoseStreamHealth } from "@/components/admin/collectors/stream-shared";
import { TONE_TEXT, type Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";
import { GameIcon } from "@/components/workspace/GameIcon";
import { useDisciplines } from "@/hooks/useDisciplineMetadata";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import analyticsService from "@/services/analytics.service";
import tournamentService from "@/services/tournament.service";
import { Block } from "./Block";

/** Health is read live: on focus and once a minute. */
const LIVE = { refetchOnWindowFocus: true, refetchInterval: 60_000 } as const;
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
/** Finished tournaments since training before the models count as stale. */
const ML_STALE_AFTER = 3;

/** How many finished tournaments came after the oldest active ML artifact's training cutoff; `null`: no active model. */
async function fetchMlTrainingLag(): Promise<number | null> {
  const artifacts = await analyticsService.listArtifacts(undefined, true);
  const cutoffs = artifacts.flatMap((artifact) => artifact.training_cutoff_tournament_id ?? []);
  if (cutoffs.length === 0) return null;
  const cutoff = Math.min(...cutoffs);
  // ponytail: a higher id stands in for "finished after", over the newest 50 completed tournaments;
  // the verdict only needs to reach ML_STALE_AFTER, so the window never hides a stale model.
  const recent = await tournamentService.listTournaments({
    workspaceId: "all",
    status: "completed",
    sort: "start_date",
    order: "desc",
    perPage: 50
  });
  return recent.results.filter((tournament) => tournament.id > cutoff).length;
}

type Verdict = { tone: Tone; text: string };

interface HealthRow {
  key: string;
  label: string;
  game?: string;
  href?: string;
  failed: boolean;
  retry: () => void;
  /** `null` while loading. */
  verdict: Verdict | null;
}

function rowState<T>(query: UseQueryResult<T>, verdict: (data: T) => Verdict) {
  return {
    failed: query.isError,
    retry: () => void query.refetch(),
    verdict: query.data === undefined ? null : verdict(query.data)
  };
}

/**
 * Superuser-only platform health: the collectors, the parser's unresolved names,
 * ML model freshness and achievement evaluation. Collapses to one line when
 * everything is green.
 */
export function PlatformHealth({ workspaceId, className }: Readonly<{ workspaceId: number | null; className?: string }>) {
  const t = useTranslations("adminShell.dashboard");
  const tCommon = useTranslations("common");
  const tHealth = useTranslations("collectors.common.health");
  const tStream = useTranslations("collectors.streams.status");
  const title = t("health");
  const now = useNow();

  const disciplines = useDisciplines("all");
  const rankGames = collectsRanks(disciplines.data ?? []);
  const streams = useQuery({
    queryKey: adminQueryKeys.streamsHealth(),
    queryFn: () => adminService.getStreamPollHealth(),
    ...LIVE
  });
  // Rank stats are per game, keyed as the collectors hub keys them.
  const ranks = useQueries({
    queries: rankGames.map((game) => ({
      queryKey: adminQueryKeys.rankStats(workspaceId, game.code),
      queryFn: () => adminService.getRankCollectionStats(game.code),
      ...LIVE
    }))
  });
  const misses = useQuery({ ...openMissCountQuery, ...LIVE });
  const ml = useQuery({ queryKey: adminQueryKeys.mlTrainingLag(), queryFn: fetchMlTrainingLag, ...LIVE });
  // Workspace-scoped: there is no platform-wide run log.
  const runs = useQuery({
    queryKey: achievementQueryKeys.evaluationRuns(workspaceId),
    queryFn: () => adminService.getEvaluationRuns(workspaceId!),
    enabled: workspaceId != null,
    ...LIVE
  });

  const rows: HealthRow[] = [
    {
      key: "streams",
      label: t("healthStreams"),
      href: "/admin/collectors/streams",
      ...rowState(streams, (data) => {
        const diagnosis = diagnoseStreamHealth(data);
        return { tone: diagnosis.tone, text: tStream(`${diagnosis.key}.label`) };
      })
    },
    ...(disciplines.data
      ? rankGames.map((game, index) => ({
          key: `ranks:${game.code}`,
          // Two games collect ranks: the icon alone left the two rows identical.
          label: rankGames.length > 1 ? t("healthRanksGame", { game: game.name }) : t("healthRanks"),
          game: game.code,
          href: `/admin/collectors/rank?discipline=${game.code}`,
          ...rowState(ranks[index], (data) => {
            const health = rankHealthDot(data);
            return { tone: health.tone, text: tHealth(health.state) };
          })
        }))
      : [
          {
            key: "ranks",
            label: t("healthRanks"),
            failed: disciplines.isError,
            retry: () => void disciplines.refetch(),
            verdict: null
          }
        ]),
    {
      key: "unresolved",
      label: t("healthUnresolved"),
      href: "/admin/content/unresolved",
      ...rowState(misses, (data) =>
        data.total > 0
          ? { tone: "info", text: t("healthUnresolvedCount", { count: data.total }) }
          : { tone: "success", text: t("healthNone") }
      )
    },
    {
      key: "ml",
      label: t("healthMl"),
      ...rowState(ml, (lag) =>
        lag == null
          ? { tone: "neutral", text: t("healthMlNone") }
          : lag >= ML_STALE_AFTER
            ? { tone: "warning", text: t("healthMlStale", { count: lag }) }
            : { tone: "success", text: t("healthMlFresh") }
      )
    },
    ...(workspaceId == null
      ? []
      : [
          {
            key: "achievements",
            label: t("healthAchievements"),
            href: "/admin/achievements",
            ...rowState(runs, (data) => {
              const since = now.getTime() - WEEK_MS;
              const failedRuns = data.filter(
                (run) => (run.status === "failed" || run.status === "partial") && Date.parse(run.started_at) >= since
              ).length;
              return failedRuns > 0
                ? { tone: "warning", text: t("healthAchievementsFailed", { count: failedRuns }) }
                : { tone: "success", text: t("healthAchievementsOk") };
            })
          }
        ])
  ];

  const allGreen = rows.every(
    (row) => !row.failed && row.verdict != null && (row.verdict.tone === "success" || row.verdict.tone === "neutral")
  );
  if (allGreen) {
    return (
      <Block
        title={title}
        framed={false}
        className={className}
        description={
          <span className={cn("inline-flex items-center gap-1.5", TONE_TEXT.success)}>
            <CheckCircle2 className="size-4 shrink-0" aria-hidden />
            {t("healthAllGood")}
          </span>
        }
      />
    );
  }

  // Tiles, not label-to-status rows: across a wide column the status sat a
  // screen away from the thing it describes. Open on the page, so the tiles
  // are the only frames, and as many across as fit.
  return (
    <Block title={title} framed={false} className={className}>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,14rem),1fr))] gap-3">
        {rows.map((row) => (
          <li
            key={row.key}
            className="flex min-w-0 flex-col gap-1 rounded-xl border border-border/60 bg-card/70 px-4 py-3"
          >
            <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
              {row.game ? <GameIcon slug={row.game} /> : null}
              {row.href ? (
                <HoverPrefetchLink
                  href={row.href}
                  title={row.label}
                  className="truncate hover:text-foreground hover:underline"
                >
                  {row.label}
                </HoverPrefetchLink>
              ) : (
                <span className="truncate" title={row.label}>
                  {row.label}
                </span>
              )}
            </span>
            {row.failed ? (
              <span className={cn("flex flex-wrap items-center gap-2 text-sm", TONE_TEXT.danger)}>
                {t("healthFailed")}
                <Button variant="outline" size="sm" onClick={row.retry}>
                  {tCommon("retry")}
                </Button>
              </span>
            ) : row.verdict ? (
              <span className={cn("flex min-w-0 items-center gap-1.5 text-sm", TONE_TEXT[row.verdict.tone])}>
                <StatusDot tone={row.verdict.tone} />
                <span className="truncate" title={row.verdict.text}>
                  {row.verdict.text}
                </span>
              </span>
            ) : (
              <Skeleton className="h-5 w-28" />
            )}
          </li>
        ))}
      </ul>
    </Block>
  );
}
