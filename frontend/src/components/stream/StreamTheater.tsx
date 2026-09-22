"use client";

import { ExternalLink, Play } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { SocialIcon } from "@/components/social/SocialIcon";
import { TwitchEmbed } from "@/components/stream/TwitchEmbed";
import { getSocialProviderConfig } from "@/lib/social/providers";
import {
  embeddableTwitchChannel,
  formatStreamUptime,
  getStreamStatus,
  STREAM_STATUS_META
} from "@/lib/social/stream-platform";
import type { StreamEntry } from "@/types/stream.types";
import { getPlayerSlug } from "@/utils/player";

type StreamTheaterProps = {
  /** The stream currently in the frame. */
  entry: StreamEntry;
  /**
   * Whether the frame is mounted. Owned by the caller, not by this component:
   * once a viewer has asked to watch, switching channels must keep playing
   * rather than send them back to a poster on every pick.
   */
  isPlaying: boolean;
  /** Called when the viewer asks for the frame. */
  onPlay: () => void;
  /** Clock for the uptime line, passed in so the caller owns the tick. */
  now: number | null;
};

/**
 * The featured stream: one player, and everything known about whoever is in it.
 *
 * ## Why exactly one frame on the page
 *
 * Every entry here is a live Twitch channel, so the grid this replaced could
 * have embedded all of them — six iframes, six players, six audio pipelines,
 * and six sockets fighting for the same bandwidth as the stream you actually
 * wanted. So the page plays ONE, and the rail beside it switches which. Every
 * other entry stays a static JPEG the poller already produced.
 *
 * ## Why the poster is a button and not an autoplaying frame
 *
 * The caller decides (see `TournamentStreamPage`): when the tournament has an
 * official broadcast, `TournamentBroadcastDock` may already be playing in the
 * corner of every tab, and mounting a second player would put two streams on
 * one screen. In that case this starts as a poster and the viewer opts in.
 * With no official broadcast there is nothing else on the page, so the frame
 * mounts straight away — a spectator who opened "Streams" came to watch.
 *
 * A non-embeddable entry (YouTube, or a channel the poller cannot confirm is
 * live) has no poster button at all: it keeps its thumbnail and its outbound
 * link, because there is no frame to offer.
 */
export function StreamTheater({ entry, isPlaying, onPlay, now }: Readonly<StreamTheaterProps>) {
  const t = useTranslations();
  const channel = embeddableTwitchChannel(entry);
  const meta = STREAM_STATUS_META[getStreamStatus(entry.live)];
  const provider = getSocialProviderConfig(entry.platform);
  const name = entry.player?.name ?? entry.channel;
  const uptime = formatStreamUptime(
    entry.started_at,
    { h: t("common.duration.h"), m: t("common.duration.m") },
    now
  );

  return (
    <div className="flex min-w-0 flex-col">
      {/* Pure black, not a surface token: whatever fills this box is video, and
          letterbox bars around a 16:9 frame should read as the player's own
          chrome rather than as a card that failed to fill. */}
      <div className="relative aspect-video w-full min-h-[300px] overflow-hidden bg-black">
        {isPlaying && channel ? (
          <TwitchEmbed
            channel={channel}
            title={t("stream.broadcast.participantPlayerLabel", { channel })}
            className="absolute inset-0 size-full border-0"
          />
        ) : (
          <>
            {entry.thumbnail_url ? (
              // Plain <img>, not next/image: `next.config.mjs` sets
              // `images.unoptimized`, so the optimizer never runs and a
              // `remotePatterns` entry for static-cdn.jtvnw.net would buy
              // nothing but a config diff. Decorative — the heading below and
              // the button label are the accessible names.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={entry.thumbnail_url}
                alt=""
                aria-hidden
                className="absolute inset-0 size-full object-cover"
              />
            ) : null}
            {channel ? (
              <button
                type="button"
                onClick={onPlay}
                className="group absolute inset-0 flex items-center justify-center bg-[hsl(220_22%_4%/0.45)] outline-none transition-colors hover:bg-[hsl(220_22%_4%/0.25)] focus-visible:bg-[hsl(220_22%_4%/0.25)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
              >
                <span className="sr-only">{t("stream.page.play", { name })}</span>
                {meta.labelKey ? (
                  <span className={`${meta.pillClassName} absolute left-3 top-3`} aria-hidden>
                    {meta.hasDot ? <span className="dot" /> : null}
                    {t(meta.labelKey)}
                  </span>
                ) : null}
                <span
                  aria-hidden
                  // Hover/focus brightens the teal edge and fill instead of
                  // scaling — a size change here nudges the centred disc and
                  // reflows nothing else, so it reads as a jitter.
                  className="inline-flex size-16 items-center justify-center rounded-full border border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_18%,hsl(220_22%_6%/0.8))] text-[color:var(--aqt-teal)] shadow-[0_8px_32px_hsl(220_22%_2%/0.55)] transition-colors group-hover:border-[color:var(--aqt-teal)] group-hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_32%,hsl(220_22%_6%/0.8))] group-focus-visible:border-[color:var(--aqt-teal)] group-focus-visible:bg-[color:color-mix(in_srgb,var(--aqt-teal)_32%,hsl(220_22%_6%/0.8))]"
                >
                  <Play className="size-7 translate-x-0.5 fill-current" />
                </span>
              </button>
            ) : meta.labelKey ? (
              <span className={`${meta.pillClassName} absolute left-3 top-3`}>
                {meta.hasDot ? <span aria-hidden className="dot" /> : null}
                {t(meta.labelKey)}
              </span>
            ) : null}
          </>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-2.5 p-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {meta.labelKey && isPlaying ? (
            <span className={meta.pillClassName}>
              {meta.hasDot ? <span aria-hidden className="dot" /> : null}
              {t(meta.labelKey)}
            </span>
          ) : null}
          {entry.viewer_count != null ? (
            <span className="aqt-tnum text-caption font-semibold tabular-nums text-[color:var(--aqt-fg)]">
              {t("stream.card.watching", { count: entry.viewer_count })}
            </span>
          ) : null}
          {/* "3h 12m" read on its own, straight after a viewer count, is a
              number with no subject. The screen reader gets the sentence and
              the eye gets the glanceable form. */}
          {uptime ? (
            <span className="aqt-tnum text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
              <span className="sr-only">{t("stream.card.onAir", { duration: uptime })}</span>
              <span aria-hidden>{uptime}</span>
            </span>
          ) : null}
          {/* Shown here and nowhere in the rail: on a tournament page every row
              would read the tournament's own game, which is not news. It IS
              news when the featured channel has wandered off to something
              else, and that only fits next to the frame. */}
          {entry.game_name ? (
            <span className="text-caption text-[color:var(--aqt-fg-muted)]">{entry.game_name}</span>
          ) : null}
        </div>

        {/* The person, not the channel, is what a spectator is scanning for on
            a tournament page, so it is the heading — and it is the one profile
            link on the page, because the rail rows are buttons and cannot nest
            one. */}
        <h3 className="m-0 flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 text-base font-semibold leading-tight">
          {entry.player ? (
            <Link
              href={`/users/${getPlayerSlug(entry.player.name)}`}
              className="inline-flex min-w-0 items-center gap-2 text-inherit no-underline outline-none transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
            >
              {entry.player.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={entry.player.avatar_url}
                  alt=""
                  aria-hidden
                  width={24}
                  height={24}
                  className="size-6 rounded-full object-cover outline outline-1 -outline-offset-1 outline-[oklch(1_0_0_/_0.1)]"
                />
              ) : null}
              <span className="truncate">{entry.player.name}</span>
            </Link>
          ) : (
            <span className="truncate">{entry.channel}</span>
          )}
          {/* No team is the ordinary state before the balancer forms rosters,
              so it renders nothing at all — an empty caption or a dash would
              claim the roster exists and is blank. */}
          {entry.player?.team ? (
            <span className="truncate text-caption font-normal text-[color:var(--aqt-fg-muted)]">
              {t("stream.card.team", { team: entry.player.team.name })}
            </span>
          ) : null}
        </h3>

        {/* Capped measure and clamped to two lines: at the theater's full width
            a stream title is a 150-character line, and streamers write titles
            that run to twice that. `title` keeps the clipped remainder
            reachable, since the rail rows truncate it to one line. */}
        {entry.title ? (
          <p
            className="m-0 line-clamp-2 max-w-[70ch] text-caption leading-snug text-[color:var(--aqt-fg-muted)]"
            title={entry.title}
          >
            {entry.title}
          </p>
        ) : null}

        <a
          href={entry.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex w-fit items-center gap-2 rounded-[9px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2 text-caption font-semibold text-inherit no-underline outline-none transition-colors hover:border-[color:var(--aqt-border-3)] hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
        >
          <SocialIcon provider={entry.platform} size={14} />
          <span>{t("stream.broadcast.watchOn", { platform: provider.label })}</span>
          <ExternalLink className="size-3.5 opacity-70" aria-hidden />
        </a>
      </div>
    </div>
  );
}

export default StreamTheater;
