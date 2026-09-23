"use client";

import { ExternalLink, Radio } from "lucide-react";
import { useTranslations } from "next-intl";

import { SocialIcon } from "@/components/social/SocialIcon";
import { TwitchEmbed } from "@/components/stream/TwitchEmbed";
import { Dock } from "@/components/ui/dock";
import {
  embeddableTwitchChannel,
  getStreamStatus,
  streamPlatformLabel
} from "@/lib/social/stream-platform";
import type { TournamentStreams } from "@/types/stream.types";

type TournamentBroadcastDockProps = {
  /** The tournament's streams, or `undefined` while the read is in flight. */
  streams: TournamentStreams | undefined;
  className?: string;
};

/**
 * The tournament's official broadcast, docked in the bottom-trailing corner of
 * every section of the page (see `ui/dock` for what the corner is and why).
 *
 * It is persistent by design: a spectator who came to watch should not have to
 * find a tab first, and moving between Bracket and Standings must not tear down
 * a playing frame. It starts collapsed — the dock arrives on every section of
 * the page, including the ones nobody opened to watch a stream.
 *
 * ## Why there is no live badge in the header
 *
 * There was one ("Channel is live") and it said nothing the panel did not
 * already: the frame below it is either playing the cast or replaced by a
 * "Watch on …" link, and the collapsed restore button keeps its dot. A pill
 * over a running player is a caption for something the viewer is looking at.
 *
 * Offline or unembeddable broadcasts keep their link: a YouTube or VK link has
 * no live detection at all (`live === null`), and hiding it would lose the only
 * way to reach the broadcast.
 *
 * ## Why a participant never enters the frame
 *
 * `embeddable` is true only for `live`, so between casts the dock falls back to
 * a bare "Watch on …" link and the page has nothing playing — while
 * participants may be on air the whole time. The dock used to fill the frame
 * with the busiest live participant's POV, announced as exactly that.
 *
 * That is gone: this panel is the ORGANIZER's broadcast, on every section of
 * the page, and a one-sided POV in the corner reserved for the cast reads as
 * the cast however it is captioned. Participant streams have their own section
 * (`TournamentStreamPage`), where the viewer picks the POV deliberately and the
 * page around it says whose it is.
 */
export function TournamentBroadcastDock({
  streams,
  className
}: Readonly<TournamentBroadcastDockProps>) {
  const t = useTranslations();
  const official = streams?.official ?? [];

  if (official.length === 0) {
    return null;
  }

  // One player, for the first OFFICIAL broadcast that can carry one. An
  // organizer with two simultaneously live official channels is not a case
  // worth a switcher; the rest stay reachable as links below.
  const featured = official.find((entry) => embeddableTwitchChannel(entry) !== null) ?? official[0];
  const featuredChannel = embeddableTwitchChannel(featured);
  const featuredStatus = getStreamStatus(featured.live);
  const secondary = official.filter((entry) => entry !== featured);

  return (
    <Dock
      title={t("stream.broadcast.heading")}
      icon={<Radio className="size-4" aria-hidden />}
      showLabel={t("stream.broadcast.show")}
      hideLabel={t("stream.broadcast.hide")}
      // Worth a glance without reopening the frame: the cast is on air. A plain
      // dot rather than the `.status-pill.live` markup — that rule styles a
      // pill, and stripping its box back off with `!important` would be three
      // overrides to end up here anyway. Colour is not the only cue: the label
      // beside it names the subject.
      badge={
        featuredStatus === "live" ? (
          <span aria-hidden className="size-[7px] rounded-full bg-[color:var(--aqt-rose)]" />
        ) : null
      }
      className={className}
    >
      {featuredChannel ? (
        // Flush to the panel edges: the frame is the content, and a padded
        // video inside a 380px box wastes the only dimension that matters.
        //
        // The ratio has to come from this wrapper, not from `aspect-video` on
        // the iframe: `TwitchEmbed` carries Twitch's documented 400x300 minimum
        // as HTML attributes, and a presentational `height` beats `aspect-ratio`
        // in the cascade — the frame would render 300px tall at every width and
        // eat half a phone screen. Absolute fill overrides it outright.
        <div className="relative aspect-video w-full bg-black">
          <TwitchEmbed
            channel={featuredChannel}
            title={t("stream.broadcast.playerLabel", { channel: featuredChannel })}
            className="absolute inset-0 size-full border-0"
          />
        </div>
      ) : null}

      {/* Rendered only when it has something to say. The stream's own title
          used to sit here and was dropped: the dock is a corner the viewer
          watches, not reads, and a channel's self-written blurb repeated the
          heading, the pill and the frame's own overlay for two more lines of
          panel. What survives is what the frame cannot say by itself — a way
          out to a platform we cannot embed, and the other official channels. */}
      {!featuredChannel || secondary.length > 0 ? (
        <div className="flex flex-col gap-2.5 p-3">
          {featuredChannel ? null : (
            <a
              href={featured.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex w-fit items-center gap-2 rounded-[9px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-3 py-2 text-caption font-semibold text-inherit no-underline outline-none transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
            >
              <SocialIcon provider={featured.platform} size={14} />
              <span>
                {t("stream.broadcast.watchOn", { platform: streamPlatformLabel(featured) })}
              </span>
              <ExternalLink className="size-3.5 opacity-70" aria-hidden />
            </a>
          )}
          {secondary.length > 0 ? (
            <ul
              aria-label={t("stream.broadcast.moreLinks")}
              className="m-0 flex list-none flex-wrap gap-2 p-0"
            >
              {secondary.map((entry) => (
                <li key={entry.url}>
                  <a
                    href={entry.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-[7px] border border-[color:var(--aqt-border-2)] px-2 py-1 text-caption font-medium text-inherit no-underline outline-none transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
                  >
                    <SocialIcon provider={entry.platform} size={12} />
                    <span>{entry.channel || streamPlatformLabel(entry)}</span>
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Dock>
  );
}

export default TournamentBroadcastDock;
