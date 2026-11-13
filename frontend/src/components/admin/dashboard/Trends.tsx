"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { StatTile } from "@/components/admin/StatTile";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import adminService from "@/services/admin.service";
import { Block, BlockError } from "./Block";

/** As many tiles across as fit at 10rem: one row in the dashboard's column, two by two on a phone. */
const TILE_GRID = "grid grid-cols-[repeat(auto-fit,minmax(min(100%,10rem),1fr))] gap-3";

/**
 * A trend line drawn over the tile; the numbers beside it carry the meaning.
 * The series mixes the workspace's games, so each point's band names its
 * tournament and game on hover.
 */
function Sparkline({ values, labels }: Readonly<{ values: (number | null)[]; labels: string[] }>) {
  const known = values.flatMap((value, index) => (value == null ? [] : [{ index, value }]));
  if (known.length < 2) return null;
  const min = Math.min(...known.map((point) => point.value));
  const span = Math.max(...known.map((point) => point.value)) - min || 1;
  const lastIndex = values.length - 1;
  const step = 100 / lastIndex;
  const points = known
    .map((point) => `${point.index * step},${29 - ((point.value - min) / span) * 28}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-10 w-full text-primary" aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      {labels.map((label, index) => (
        <rect key={index} x={index * step - step / 2} y={0} width={step} height={30} fill="transparent">
          <title>{label}</title>
        </rect>
      ))}
    </svg>
  );
}

/**
 * Four tiles over the workspace's last ten finished, public, non-league
 * tournaments, open on the page: the tiles are the frames. No realtime: they
 * move when a tournament finishes.
 */
export function Trends({ workspaceId, className }: Readonly<{ workspaceId: number; className?: string }>) {
  const t = useTranslations("adminShell.dashboard");
  const format = useFormatter();
  const games = useGameDescriptors();
  const title = t("trends");
  const query = useQuery({
    queryKey: adminQueryKeys.dashboardTrends(workspaceId),
    queryFn: () => adminService.getDashboardTrends()
  });

  if (query.isError) {
    return (
      <Block title={title} framed={false} className={className}>
        <BlockError title={title} onRetry={() => void query.refetch()} />
      </Block>
    );
  }
  if (!query.data) {
    return (
      <Block title={title} framed={false} className={className}>
        <div className={TILE_GRID}>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-32 rounded-xl" />
          ))}
        </div>
      </Block>
    );
  }

  const points = query.data.points;
  if (points.length === 0) {
    return (
      <Block title={title} framed={false} className={className}>
        <p className="text-sm text-muted-foreground">{t("trendsEmpty")}</p>
      </Block>
    );
  }

  const percent = (value: number) => format.number(value, { style: "percent", maximumFractionDigits: 0 });
  const duration = (seconds: number) =>
    seconds < 3600
      ? format.number(seconds / 60, { style: "unit", unit: "minute", unitDisplay: "short", maximumFractionDigits: 0 })
      : format.number(seconds / 3600, { style: "unit", unit: "hour", unitDisplay: "short", maximumFractionDigits: 1 });
  const tiles = [
    {
      key: "participants",
      label: t("trendParticipants"),
      series: points.map((point) => point.participants),
      show: (value: number) => format.number(value)
    },
    {
      key: "newcomers",
      label: t("trendNewcomers"),
      series: points.map((point) => (point.participants > 0 ? point.newcomers / point.participants : null)),
      show: percent
    },
    {
      key: "logs",
      label: t("trendLogCoverage"),
      series: points.map((point) =>
        point.duel_encounters_total > 0 ? point.duel_encounters_with_logs / point.duel_encounters_total : null
      ),
      show: percent
    },
    {
      key: "confirm",
      label: t("trendConfirmTime"),
      series: points.map((point) => point.median_confirm_seconds),
      show: duration
    }
  ];

  return (
    <Block
      title={title}
      framed={false}
      className={className}
      description={t("trendsDescription", { count: points.length })}
    >
      <div className={TILE_GRID}>
        {tiles.map((tile) => {
          const latest = tile.series.at(-1);
          const known = tile.series.filter((value): value is number => value != null);
          const average = known.length > 0 ? known.reduce((sum, value) => sum + value, 0) / known.length : null;
          return (
            <StatTile
              key={tile.key}
              label={tile.label}
              value={latest == null ? "—" : tile.show(latest)}
              detail={
                average == null ? t("trendNoData") : t("trendAverage", { value: tile.show(average) })
              }
              action={
                <Sparkline
                  values={tile.series}
                  labels={points.map((point, index) => {
                    const value = tile.series[index];
                    return t("trendPoint", {
                      tournament: point.tournament_name,
                      game: games.get(point.discipline)?.name ?? point.discipline,
                      value: value == null ? "—" : tile.show(value)
                    });
                  })}
                />
              }
            />
          );
        })}
      </div>
    </Block>
  );
}
