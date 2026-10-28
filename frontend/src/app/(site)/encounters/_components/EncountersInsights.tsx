"use client";

import { useId, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { UseQueryResult } from "@tanstack/react-query";

import { useFormatter } from "@/lib/datetime/client";
import { duelSeats } from "@/lib/encounter/seats";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import type { EncounterInsights, EncounterStageKind } from "@/types/encounter.types";

import { formatPercent, formatSeriesLength } from "./encounters.helpers";

const STAGE_KIND_LABEL = {
  groups: "encounters.insights.stages.groups",
  playoffs: "encounters.insights.stages.playoffs",
  swiss: "encounters.insights.stages.swiss",
  unassigned: "encounters.insights.stages.unassigned"
} as const satisfies Record<EncounterStageKind, string>;

/** One accent: the stage kinds are told apart by its strength, largest share strongest. */
const STAGE_SHADES = [100, 65, 40, 20];

/** A value the data cannot give, written as the table writes one. */
const NONE = "—";

function InsightCard({
  title,
  description,
  children
}: Readonly<{ title: string; description?: string; children: ReactNode }>) {
  return (
    <Card asChild>
      <section aria-label={title}>
        <CardHeader className="space-y-1 p-4 pb-3">
          <CardTitle asChild className="text-body">
            <h3>{title}</h3>
          </CardTitle>
          {description ? <CardDescription className="text-caption">{description}</CardDescription> : null}
        </CardHeader>
        <CardContent className="p-4 pt-0">{children}</CardContent>
      </section>
    </Card>
  );
}

/** A labelled share bar; the visible row is decoration for `summary`, which is what a screen reader hears. */
function ShareRow({
  label,
  value,
  share,
  summary
}: Readonly<{ label: string; value: string; share: number; summary: string }>) {
  return (
    <li className="grid grid-cols-[minmax(3rem,8rem)_minmax(0,1fr)_auto] items-center gap-3 text-caption">
      <span className="sr-only">{summary}</span>
      <span aria-hidden className="truncate text-[color:var(--aqt-fg)]">
        {label}
      </span>
      <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
        <span className="block h-full rounded-full bg-[color:var(--aqt-teal)]" style={{ width: `${share * 100}%` }} />
      </span>
      <span aria-hidden className="tabular-nums text-[color:var(--aqt-fg-muted)]">
        {value}
      </span>
    </li>
  );
}

/**
 * «Сводка»: completed encounters under the current filters, all time (the server forces the status). Read only
 * while shown. A histogram bar narrows the list to its closeness bucket and switches to it.
 */
export function EncountersInsights({
  query,
  filtered,
  onClearFilters,
  onPickCloseness
}: Readonly<{
  query: UseQueryResult<EncounterInsights>;
  /** Anything narrows the summary: an empty one then offers to clear the filters. */
  filtered: boolean;
  onClearFilters: () => void;
  onPickCloseness: (start: number, end: number) => void;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const headingId = useId();
  const data = query.data;

  const body = () => {
    if (query.isError) return <PageStateCard state="error" onAction={() => void query.refetch()} />;
    if (!data) {
      return (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-56 rounded-xl" />
          ))}
        </div>
      );
    }
    if (data.completed === 0) {
      return (
        <PageStateCard
          state={filtered ? "filtered-empty" : "empty"}
          onAction={filtered ? onClearFilters : undefined}
        />
      );
    }

    const pct = (fraction: number) => formatPercent(format, fraction);
    const maxBucket = Math.max(1, ...data.closeness_histogram.map((bucket) => bucket.count));
    const duels = data.score_lines.reduce((sum, line) => sum + line.count, 0);
    const maxLine = Math.max(1, ...data.score_lines.map((line) => line.count));
    const maxMap = Math.max(1, ...data.hot_maps.map((map) => map.count));
    const staged = data.stage_kinds.reduce((sum, kind) => sum + kind.count, 0);

    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <InsightCard
          title={t("encounters.insights.closeness.title")}
          description={
            data.avg_closeness == null
              ? t("encounters.insights.closeness.sub")
              : t("encounters.insights.closeness.avg", { avg: pct(data.avg_closeness) })
          }
        >
          {/* Every bucket keeps its place: an empty one is a baseline stub (nothing to filter to), so a sparse
              histogram still reads as ten tenths rather than a few floating bars. */}
          <div role="group" aria-label={t("encounters.insights.closeness.title")} className="flex h-36 items-end gap-1">
            {data.closeness_histogram.map((bucket) =>
              bucket.count === 0 ? (
                <span key={bucket.start} aria-hidden className="flex h-full min-w-0 flex-1 flex-col justify-end">
                  <span className="h-0.5 rounded-full bg-[color:var(--aqt-border-2)]" />
                </span>
              ) : (
                <Button
                  key={bucket.start}
                  variant="ghost"
                  size="inline"
                  aria-label={t("encounters.insights.closeness.bar", {
                    from: pct(bucket.start),
                    to: pct(bucket.end),
                    count: bucket.count
                  })}
                  className="group h-full min-w-0 flex-1 flex-col items-stretch justify-end gap-0 rounded-sm hover:bg-[color:var(--aqt-overlay-2)]"
                  onClick={() => onPickCloseness(bucket.start, bucket.end)}
                >
                  <span aria-hidden className="h-4 text-center text-label leading-4 tabular-nums text-[color:var(--aqt-fg-muted)]">
                    {format.number(bucket.count)}
                  </span>
                  {/* The count's line comes off the top, so the tallest bar still fits under its label. */}
                  <span
                    aria-hidden
                    className="block w-full rounded-t-sm bg-[color:var(--aqt-teal)] opacity-75 transition-opacity group-hover:opacity-100"
                    style={{ height: `calc((100% - 1rem) * ${bucket.count / maxBucket})`, minHeight: 2 }}
                  />
                </Button>
              )
            )}
          </div>
          <div aria-hidden className="mt-1.5 grid grid-cols-3 text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
            <span>{pct(0)}</span>
            <span className="text-center">{pct(0.5)}</span>
            <span className="text-right">{pct(1)}</span>
          </div>
        </InsightCard>

        <InsightCard title={t("encounters.insights.length.title")}>
          <dl className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1">
              <dt className="text-label text-[color:var(--aqt-fg-dim)]">{t("encounters.insights.length.avg")}</dt>
              <dd className="text-title font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                {data.avg_series_seconds ? formatSeriesLength(format, data.avg_series_seconds) : NONE}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-label text-[color:var(--aqt-fg-dim)]">{t("encounters.insights.length.sweepRate")}</dt>
              <dd className="text-title font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                {data.multi_map ? pct(data.sweeps / data.multi_map) : NONE}
              </dd>
              <dd className="text-label text-[color:var(--aqt-fg-dim)]">
                {t("encounters.insights.length.sweepsMeta", { sweeps: data.sweeps, distance: data.went_distance })}
              </dd>
            </div>
          </dl>
        </InsightCard>

        <InsightCard title={t("encounters.insights.scoreLines.title")} description={t("encounters.insights.scoreLines.sub")}>
          <ul className="space-y-2">
            {data.score_lines.map((line) => {
              const score = `${line.winner}:${line.loser}`;
              return (
                <ShareRow
                  key={score}
                  label={score}
                  value={format.number(line.count)}
                  share={line.count / maxLine}
                  summary={t("encounters.insights.scoreLines.row", {
                    score,
                    draw: line.winner === line.loser ? "yes" : "no",
                    count: line.count,
                    share: pct(line.count / duels)
                  })}
                />
              );
            })}
          </ul>
        </InsightCard>

        <InsightCard title={t("encounters.insights.stages.title")}>
          <div aria-hidden className="flex h-3 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
            {data.stage_kinds.map((kind, index) => (
              <span
                key={kind.kind}
                className="h-full"
                style={{
                  width: `${(kind.count / Math.max(1, staged)) * 100}%`,
                  background: `color-mix(in srgb, var(--aqt-teal) ${STAGE_SHADES[index] ?? 20}%, transparent)`
                }}
              />
            ))}
          </div>
          <ul className="mt-3 space-y-1.5 text-caption">
            {data.stage_kinds.map((kind, index) => (
              <li key={kind.kind} className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="size-2.5 shrink-0 rounded-sm"
                  style={{ background: `color-mix(in srgb, var(--aqt-teal) ${STAGE_SHADES[index] ?? 20}%, transparent)` }}
                />
                <span className="text-[color:var(--aqt-fg)]">{t(STAGE_KIND_LABEL[kind.kind])}</span>
                <span className="ml-auto tabular-nums text-[color:var(--aqt-fg-muted)]">
                  {format.number(kind.count)} · {pct(kind.count / Math.max(1, staged))}
                </span>
              </li>
            ))}
          </ul>
        </InsightCard>

        <InsightCard title={t("encounters.insights.maps.title")} description={t("encounters.insights.maps.sub")}>
          {data.hot_maps.length ? (
            <ul className="space-y-2">
              {data.hot_maps.map((map) => (
                <ShareRow
                  key={map.name}
                  label={map.name}
                  value={format.number(map.count)}
                  share={map.count / maxMap}
                  summary={t("encounters.insights.maps.row", { name: map.name, count: map.count })}
                />
              ))}
            </ul>
          ) : (
            <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("encounters.insights.maps.empty")}</p>
          )}
        </InsightCard>

        <InsightCard title={t("encounters.insights.closest.title")} description={t("encounters.insights.closest.sub")}>
          <ul className="divide-y divide-[color:var(--aqt-border)]">
            {data.closest.map((encounter) => {
              const [one, two] = duelSeats(encounter.teams);
              return (
                <li key={encounter.id}>
                  <HoverPrefetchLink
                    href={`/encounters/${encounter.id}`}
                    className="flex items-center gap-3 rounded-sm py-2 text-caption transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[color:var(--aqt-fg)]">
                        {one?.name} <b className="tabular-nums">{one?.score ?? 0}:{two?.score ?? 0}</b> {two?.name}
                      </span>
                      <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                        {encounter.tournament?.name}
                      </span>
                    </span>
                    {encounter.closeness == null ? null : (
                      <span className="shrink-0 tabular-nums text-[color:var(--aqt-teal)]">
                        <span className="sr-only">{t("encounters.insights.closest.closeness")} </span>
                        {pct(encounter.closeness)}
                      </span>
                    )}
                  </HoverPrefetchLink>
                </li>
              );
            })}
          </ul>
        </InsightCard>
      </div>
    );
  };

  return (
    <section aria-labelledby={headingId} aria-busy={query.isFetching} className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={headingId} className="text-heading font-semibold text-[color:var(--aqt-fg)]">
          {t("encounters.insights.title")}
        </h2>
        {data ? (
          <span className="text-label text-[color:var(--aqt-fg-dim)]">
            {t("encounters.insights.meta", { count: data.completed })}
          </span>
        ) : null}
      </div>
      {body()}
    </section>
  );
}
