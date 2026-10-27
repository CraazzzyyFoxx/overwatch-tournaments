"use client";

import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";

import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import { PastBroadcasts, VodTheater, type VodPick } from "@/components/stream/PastBroadcasts";
import { StreamRow } from "@/components/stream/StreamRow";
import { StreamTheater } from "@/components/stream/StreamTheater";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { Eyebrow } from "@/components/ui/eyebrow";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import {
  embeddableTwitchChannel,
  getStreamStatus,
  sortStreamsByAudience,
  streamEntryKey
} from "@/lib/social/stream-platform";
import { areStreamsVisible, mayHavePastBroadcasts } from "@/lib/tournament/status";
import { cn } from "@/lib/utils";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { StreamChapter, StreamVod } from "@/types/stream.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentStreamSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { useTournamentStreamsQuery, useTournamentVodsQuery } from "../_hooks/useTournamentStreams";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";

/**
 * Who is streaming this tournament right now — and a player to watch them in —
 * then what participants streamed before, cut into the matches they played.
 *
 * Official broadcasts lead the list (and the theater when nothing is picked).
 * Participants follow, busiest first. The floating dock is a picture-in-picture
 * of the same official channel, collapsed until the viewer asks for it.
 *
 * ## Theater, not a grid
 *
 * This page used to be a grid of thumbnail cards that all linked out to
 * twitch.tv: a page called "Streams" on which nothing could be watched. Every
 * embeddable entry now fills a player and the rest are a rail that switches it.
 * See `StreamTheater` for why exactly one frame is mounted and `StreamRow` for
 * why the rail is rows.
 *
 * ## Which one is in the frame, and when it starts
 *
 * Selection is DERIVED (`selectedKey` is only a preference), so a refetch that
 * drops the selected channel silently falls back to the official cast, then the
 * busiest embeddable, instead of leaving a dead frame — and `sortStreamsByAudience`
 * is a total order on the participant tail, so the fallback resolves to the same
 * entry tick after tick rather than restarting the iframe.
 *
 * The frame mounts on load only when the tournament has NO official broadcast.
 * With one, the shell's dock may already be playing in the corner of every tab,
 * and a second autoplaying player would be two streams on one screen; the
 * viewer opts in with the poster button instead. Once they have, switching
 * channels keeps playing — hence `hasStartedWatching` lives here and not in the
 * theater.
 *
 * ## Past broadcasts share the frame
 *
 * A chapter of a past broadcast plays in the SAME theater (`vodPick`), still
 * one player on the page; picking a live channel from the rail hands the frame
 * back. With nothing live — a finished tournament — the theater only appears
 * once a chapter is picked, and the pick scrolls it into view.
 *
 * ## Which reads, and freshness
 *
 * Both reads follow the shell's phase gates, so this page reads exactly the
 * keys the shell seeded: the live streams only while they belong on screen
 * (`areStreamsVisible`), the past broadcasts from check-in on, including after
 * the end (`mayHavePastBroadcasts`).
 *
 * There is no realtime subscription in this view on purpose.
 * `TournamentClientLayout` — the ancestor of every tournament section — already
 * consumes the tournament's invalidation topic, and `tournament.streams` stales
 * `tournamentQueryKeys.streams(id)`, which is the very key this view reads. A
 * second subscription here would only duplicate a mechanism that already covers
 * this page. Keep the single owner. Past broadcasts have no realtime resource at
 * all; their staleTime is the freshness.
 */
const TournamentStreamPage = ({ tournamentId, slug }: { tournamentId: number; slug: string }) => {
  const t = useTranslations();
  const connectionState = useRealtimeStore((s) => s.connectionState);
  // Keyed by `slug`, as the shell reads it, so this is the shell's cache entry.
  const status = useTournamentQuery(slug).data?.status;
  const showsLive = status !== undefined && areStreamsVisible(status);
  const showsPast = status !== undefined && mayHavePastBroadcasts(status);
  const streamsQuery = useTournamentStreamsQuery(showsLive ? tournamentId : undefined);
  const vodsQuery = useTournamentVodsQuery(showsPast ? tournamentId : undefined);
  const official = streamsQuery.data?.official ?? [];
  const participants = streamsQuery.data?.participants ?? [];
  const vods = vodsQuery.data?.vods ?? [];
  const hasOfficialBroadcast = official.length > 0;

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [hasStartedWatching, setHasStartedWatching] = useState(false);
  const [vodPick, setVodPick] = useState<VodPick | null>(null);
  const theaterRef = useRef<HTMLDivElement>(null);
  // One clock for the whole page, so every uptime on screen is measured from
  // the same instant, and `null` until hydration so no server-side duration is
  // baked into the HTML.
  const now = useMinuteClock();
  // A frame that starts moving on its own is exactly what this preference asks
  // us not to do, and it is a decision CSS cannot make — `globals.css` can
  // flatten a transition but not decline to mount a player. The poster and its
  // button stay, so nothing is taken away; the viewer just asks first.
  const prefersReducedMotion = usePrefersReducedMotion();

  const sorted = useMemo(() => {
    const officialKeys = new Set(official.map(streamEntryKey));
    return [
      ...official,
      ...sortStreamsByAudience(
        participants.filter((entry) => !officialKeys.has(streamEntryKey(entry)))
      )
    ];
  }, [official, participants]);
  const featured =
    sorted.find((entry) => streamEntryKey(entry) === selectedKey) ?? sorted[0] ?? null;

  // The reads this phase makes; a phase that makes none (before check-in) is
  // simply empty.
  const reads = [showsLive ? streamsQuery : null, showsPast ? vodsQuery : null].filter(
    (query) => query !== null
  );
  const refetch = () => reads.forEach((query) => void query.refetch());
  const isFetching = reads.some((query) => query.isFetching);

  // The same loading / empty / updating / refresh-error vocabulary every other
  // public tournament section speaks.
  const presentation = getPublicPageQueryPresentation({
    data: status !== undefined && reads.every((query) => query.data !== undefined) ? reads : undefined,
    itemCount: sorted.length + vods.length,
    isPending: reads.some((query) => query.isPending),
    isError: reads.some((query) => query.isError),
    isFetching
  });

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={refetch} />;
  }

  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentStreamSkeleton />;
  }

  // Committed synchronously so the theater exists to scroll to: with nothing
  // live it mounts on this very pick.
  const pickChapter = (vod: StreamVod, chapter: StreamChapter) => {
    flushSync(() => setVodPick((previous) => ({ vod, chapter, take: (previous?.take ?? 0) + 1 })));
    theaterRef.current?.scrollIntoView({
      block: "nearest",
      behavior: prefersReducedMotion ? "auto" : "smooth"
    });
  };

  const totalViewers = sorted.reduce((sum, entry) => sum + (entry.viewer_count ?? 0), 0);
  const liveCount = sorted.filter((entry) => getStreamStatus(entry.live) === "live").length;

  const content = (
    <section className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0" aria-label={t("common.stream")}>
      {presentation.showUpdating ? <UpdatingBadge /> : null}

      {presentation.contentState === "empty" ? (
        // "Nobody live" is a true, frequent, and temporary state, so it gets its
        // own copy rather than the generic "the organizer has not published this
        // yet" — nothing here is waiting on the organizer.
        <TournamentPageState
          state="empty"
          title={t("stream.page.emptyTitle")}
          description={t("stream.page.emptyDescription")}
        />
      ) : (
        <>
          {featured || vodPick ? (
            <div
              ref={theaterRef}
              className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]"
            >
              {featured ? (
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] px-5 py-3">
                  <Eyebrow as="h2" className="aqt-tnum m-0">
                    {t("common.stream")}
                  </Eyebrow>
                  <span className="flex shrink-0 items-center gap-2.5">
                    {liveCount > 0 ? (
                      <TournamentStatusPill status="live">
                        {t("stream.page.liveCount", { count: liveCount })}
                      </TournamentStatusPill>
                    ) : null}
                    {totalViewers > 0 ? (
                      <span className="aqt-tnum text-label tabular-nums text-[color:var(--aqt-fg-muted)]">
                        {t("stream.card.watching", { count: totalViewers })}
                      </span>
                    ) : null}
                    <ConnectionIndicator connectionState={connectionState} />
                  </span>
                </div>
              ) : null}

              <div className={cn("grid", featured && "xl:grid-cols-[minmax(0,1fr)_340px]")}>
                {vodPick ? (
                  <VodTheater pick={vodPick} />
                ) : featured ? (
                  <StreamTheater
                    entry={featured}
                    isPlaying={(!hasOfficialBroadcast && !prefersReducedMotion) || hasStartedWatching}
                    onPlay={() => setHasStartedWatching(true)}
                    now={now}
                  />
                ) : null}

                {/* Capped rather than free-running: the rail must not grow taller
                    than the player it belongs to, or the switcher scrolls the
                    page away from the thing it is switching. */}
                {featured ? (
                  <ul
                    aria-label={t("stream.page.channels")}
                    className="m-0 grid list-none grid-cols-1 content-start gap-2 border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-3 md:grid-cols-2 xl:max-h-[72vh] xl:grid-cols-1 xl:overflow-y-auto xl:border-t-0 xl:border-s"
                  >
                    {sorted.map((entry) => {
                      const key = streamEntryKey(entry);
                      const canEmbed = embeddableTwitchChannel(entry) !== null;
                      return (
                        <li key={key} className="min-w-0">
                          <StreamRow
                            entry={entry}
                            isSelected={!vodPick && key === streamEntryKey(featured)}
                            now={now}
                            onSelect={
                              canEmbed
                                ? () => {
                                    setVodPick(null);
                                    setSelectedKey(key);
                                    setHasStartedWatching(true);
                                  }
                                : null
                            }
                          />
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>
            </div>
          ) : null}

          {vods.length > 0 ? (
            <PastBroadcasts vods={vods} pick={vodPick} onPick={pickChapter} />
          ) : null}
        </>
      )}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState state="refresh-error" onRetry={refetch} isUpdating={isFetching}>
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

export default TournamentStreamPage;
