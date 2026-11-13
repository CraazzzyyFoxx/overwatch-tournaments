"use client";

import { Fragment, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { useSegmentLabel } from "@/components/match/segment-label";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { buildEventRows, type EventParty } from "@/lib/stats/events";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import encounterService from "@/services/encounter.service";
import type { EventTypeDefinition } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";

const clock = (seconds: number) => {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

const partyLabel = (party: EventParty | null): string | null => {
  if (party === null) return null;
  if (party.member && party.team) return `${party.member} (${party.team})`;
  return party.member ?? party.team;
};

/**
 * The game-neutral native event timeline of a match: every event of every declared type in served order,
 * grouped by segment, each named through the match's participants and members. Which events matter and what
 * their `data` means is the discipline's own (its module renders that); this lists what was observed, for any
 * number of participants.
 */
export default function MatchEventsTimeline({
  match,
  eventTypes
}: Readonly<{ match: MatchWithStats; eventTypes: readonly EventTypeDefinition[] }>) {
  const t = useTranslations();
  const segmentLabel = useSegmentLabel(match.statistics.segments);
  const feed = useQuery({
    queryKey: encounterQueryKeys.matchEvents(match.id),
    queryFn: () => encounterService.getMatchKillFeed(match.id),
    staleTime: 5 * 60_000
  });
  const rows = useMemo(
    () => (feed.data ? buildEventRows(feed.data, match, eventTypes) : []),
    [feed.data, match, eventTypes]
  );

  if (feed.isPending) {
    return (
      <Skeleton
        role="status"
        aria-label={t("matches.native.timeline.loading")}
        className="h-40 w-full rounded-lg"
      />
    );
  }
  if (feed.isError) {
    return (
      <div className="flex flex-wrap items-center gap-2" role="alert">
        <p className="text-sm text-[color:var(--aqt-rose)]">{t("matches.native.timeline.error")}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={feed.isFetching}
          onClick={() => void feed.refetch()}
        >
          {t("common.retry")}
        </Button>
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-caption text-[color:var(--aqt-fg-dim)]">
        {t("matches.native.timeline.empty")}
      </p>
    );
  }

  const segments = [...new Set(rows.map((row) => row.segment))];
  return (
    <div className="rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-4">
      <Eyebrow as="h3" className="aqt-tnum mb-3">
        {t("matches.native.timeline.title")}
      </Eyebrow>
      <div className="flex max-h-[600px] flex-col gap-5 overflow-y-auto pr-1">
        {segments.map((segment) => (
          <section key={segment} aria-label={segmentLabel(segment)}>
            {segments.length > 1 ? (
              <Eyebrow as="h4" tone="muted" className="mb-2 border-b border-[color:var(--aqt-border)] pb-1.5">
                {segmentLabel(segment)}
              </Eyebrow>
            ) : null}
            <ol className="flex flex-col">
              {rows
                .filter((row) => row.segment === segment)
                .map((row) => {
                  const actor = partyLabel(row.actor);
                  const target = partyLabel(row.target);
                  return (
                    <li
                      key={row.id}
                      className="flex flex-wrap items-center gap-2 py-[5px] pl-3 text-caption"
                    >
                      <span className="aqt-tnum w-10 shrink-0 text-label text-[color:var(--aqt-fg-faint)]">
                        {clock(row.t)}
                      </span>
                      <span className="font-semibold text-[color:var(--aqt-fg)]">{row.type}</span>
                      {row.entity ? (
                        <span className="inline-flex items-center gap-1">
                          <CatalogEntityImage entity={row.entity} size="sm" />
                          {row.entity.name}
                        </span>
                      ) : null}
                      {actor ? (
                        <span className="text-[color:var(--aqt-fg-muted)]">{actor}</span>
                      ) : null}
                      {target || row.relatedEntity ? (
                        <Fragment>
                          <span aria-hidden className="text-[color:var(--aqt-fg-faint)]">
                            →
                          </span>
                          {target ? (
                            <span className="text-[color:var(--aqt-fg-dim)]">{target}</span>
                          ) : null}
                          {row.relatedEntity ? (
                            <span className="inline-flex items-center gap-1">
                              <CatalogEntityImage entity={row.relatedEntity} size="sm" />
                              {row.relatedEntity.name}
                            </span>
                          ) : null}
                        </Fragment>
                      ) : null}
                    </li>
                  );
                })}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}
