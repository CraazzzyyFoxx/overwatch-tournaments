"use client";

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { ConnectionIndicator } from "@/components/realtime/ConnectionIndicator";
import { StreamRow } from "@/components/stream/StreamRow";
import { StreamTheater } from "@/components/stream/StreamTheater";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import {
  embeddableTwitchChannel,
  getStreamStatus,
  sortStreamsByAudience,
  streamEntryKey
} from "@/lib/stream-platform";
import { useRealtimeStore } from "@/stores/realtime.store";

import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentStreamSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { useTournamentStreamsQuery } from "../_hooks/useTournamentStreams";
import styles from "../TournamentDetail.module.css";
import { getPublicPageQueryPresentation } from "./publicPageQueryPresentation";

/**
 * Who is streaming this tournament right now — and a player to watch them in.
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
 * ## Freshness
 *
 * There is no realtime subscription in this view on purpose.
 * `TournamentClientLayout` — the ancestor of every tournament section — already
 * consumes the tournament's invalidation topic, and `tournament.streams` stales
 * `tournamentQueryKeys.streams(id)`, which is the very key this view reads. A
 * second subscription here would only duplicate a mechanism that already covers
 * this page. Keep the single owner.
 */
const TournamentStreamPage = ({ tournamentId }: { tournamentId: number }) => {
  const t = useTranslations();
  const connectionState = useRealtimeStore((s) => s.connectionState);
  const streamsQuery = useTournamentStreamsQuery(tournamentId);
  const official = streamsQuery.data?.official ?? [];
  const participants = streamsQuery.data?.participants ?? [];
  const hasOfficialBroadcast = official.length > 0;

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [hasStartedWatching, setHasStartedWatching] = useState(false);
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

  // The same loading / empty / updating / refresh-error vocabulary every other
  // public tournament section speaks.
  const presentation = getPublicPageQueryPresentation({
    data: streamsQuery.data,
    itemCount: sorted.length,
    isPending: streamsQuery.isPending,
    isError: streamsQuery.isError,
    isFetching: streamsQuery.isFetching
  });

  if (presentation.initialState === "error") {
    return (
      <TournamentPageState state="initial-error" onRetry={() => void streamsQuery.refetch()} />
    );
  }

  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentStreamSkeleton />;
  }

  const totalViewers = sorted.reduce((sum, entry) => sum + (entry.viewer_count ?? 0), 0);
  const liveCount = sorted.filter((entry) => getStreamStatus(entry.live) === "live").length;

  const content = (
    <section className={styles.publicDataPage} aria-label={t("common.stream")}>
      {presentation.showUpdating ? <UpdatingBadge /> : null}

      {presentation.contentState === "empty" || !featured ? (
        // "Nobody live" is a true, frequent, and temporary state, so it gets its
        // own copy rather than the generic "the organizer has not published this
        // yet" — nothing here is waiting on the organizer.
        <TournamentPageState
          state="empty"
          title={t("stream.page.emptyTitle")}
          description={t("stream.page.emptyDescription")}
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] px-5 py-3">
            <h2 className="aqt-tnum m-0 text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {t("common.stream")}
            </h2>
            <span className="flex shrink-0 items-center gap-2.5">
              {liveCount > 0 ? (
                <span className="status-pill live">
                  <span aria-hidden className="dot" />
                  {t("stream.page.liveCount", { count: liveCount })}
                </span>
              ) : null}
              {totalViewers > 0 ? (
                <span className="aqt-tnum text-label tabular-nums text-[color:var(--aqt-fg-muted)]">
                  {t("stream.card.watching", { count: totalViewers })}
                </span>
              ) : null}
              <ConnectionIndicator connectionState={connectionState} />
            </span>
          </div>

          <div className="grid xl:grid-cols-[minmax(0,1fr)_340px]">
            <StreamTheater
              entry={featured}
              isPlaying={(!hasOfficialBroadcast && !prefersReducedMotion) || hasStartedWatching}
              onPlay={() => setHasStartedWatching(true)}
              now={now}
            />

            {/* Capped rather than free-running: the rail must not grow taller
                than the player it belongs to, or the switcher scrolls the
                page away from the thing it is switching. */}
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
                      isSelected={key === streamEntryKey(featured)}
                      now={now}
                      onSelect={
                        canEmbed
                          ? () => {
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
          </div>
        </div>
      )}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void streamsQuery.refetch()}
        isUpdating={streamsQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

export default TournamentStreamPage;
