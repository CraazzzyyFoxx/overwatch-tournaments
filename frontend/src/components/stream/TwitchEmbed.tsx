"use client";

import { useSyncExternalStore } from "react";

import { twitchTimestamp } from "@/lib/social/stream-platform";

type TwitchEmbedProps = {
  /**
   * Accessible name of the player frame. Defaults to `Twitch · {channel}` (or
   * the video id), which is brand + identifier and therefore locale-neutral.
   */
  title?: string;
  className?: string;
} & (
  | {
      /** Twitch login of the live channel to play. */
      channel: string;
      video?: never;
      start?: never;
    }
  | {
      /** Twitch video id of a past broadcast, without the "v" prefix. */
      video: string;
      /** Where to start, in seconds into the video. */
      start: number;
      channel?: never;
    }
);

/**
 * The `parent` value Twitch will accept for a document served from `hostname`.
 *
 * Exported as the test seam for the rule, which is not self-evident from the
 * expression: lowercase, trimmed, and with the port STRIPPED — Twitch rejects a
 * `parent` that carries one, so `localhost:3000` must be sent as `localhost`.
 * Empty input yields `null`, meaning "do not render the player".
 */
export function twitchParentFromHostname(hostname: string | null | undefined): string | null {
  return hostname?.trim().toLowerCase().split(":")[0] || null;
}

// The document hostname cannot change without a navigation, so the store never
// notifies. `useSyncExternalStore` (rather than state set from an effect) is what
// expresses "this value exists only on the client": the server snapshot is
// `null`, so SSR and hydration both render nothing and React swaps in the real
// hostname on the client pass — no hydration mismatch, no state write in an
// effect.
//
// These three are hoisted to module scope because `useSyncExternalStore` keys on
// callback IDENTITY: arrow literals written inline at the call site would be new
// functions on every render, so React would tear down and re-subscribe the store
// each pass. They are one-expression functions that must not be inlined.
const subscribeToHostname = () => () => {};
const clientHostname = () => window.location.hostname;
const serverHostname = () => null;

/**
 * Twitch player for a live channel (muted: browsers block unmuted autoplay
 * anyway) or for a past broadcast from a given moment. A VOD is only mounted
 * once the viewer picked that moment, so it is not muted: they asked to hear it.
 *
 * ## Why `parent` is read from `window.location.hostname`
 *
 * Twitch validates the `parent` query param against the domain that actually
 * frames the player and refuses to play on a mismatch — the failure is a blank
 * player, not an error we can catch. This platform is white-label: the apex,
 * `*.owt.craazzzyyfoxx.me` subdomains, AND arbitrary tenant custom domains all
 * serve the same page.
 *
 * So `parent` MUST come from the live document:
 *
 *  - NOT from `NEXT_PUBLIC_SITE_URL` (`@/config/site`) — it defaults to the
 *    platform apex, so on a tenant's custom domain it would not match and the
 *    player would silently refuse. Do not "simplify" this to a build-time env
 *    var, or the feature dies for every custom-domain tenant.
 *  - Normalised exactly like `resolveHost` (`@/lib/site/host`): lowercased with the
 *    port stripped, because Twitch rejects a `parent` that carries a port.
 *  - Read AFTER mount. The server has no hostname, so the player is not
 *    rendered at all during SSR/first paint — a frame emitted with a guessed
 *    `parent` would just be a dead iframe.
 */
export function TwitchEmbed({ channel, video, start, title, className }: Readonly<TwitchEmbedProps>) {
  const parent = twitchParentFromHostname(useSyncExternalStore(subscribeToHostname, clientHostname, serverHostname));
  const identifier = channel || video;

  if (!parent || !identifier) {
    return null;
  }

  // The player wants the "v" prefix on a video id; twitch.tv links do not.
  const source = channel
    ? `channel=${encodeURIComponent(channel)}`
    : `video=v${encodeURIComponent(identifier)}&time=${twitchTimestamp(start ?? 0)}`;
  const src = `https://player.twitch.tv/?${source}&parent=${encodeURIComponent(parent)}${channel ? "&muted=true" : ""}`;

  return (
    // 400x300 is Twitch's documented minimum player size; the attributes carry
    // that floor while the CSS scales the frame up to its container.
    <iframe
      src={src}
      title={title ?? `Twitch · ${identifier}`}
      width={400}
      height={300}
      allowFullScreen
      className={className ?? "aspect-video h-full w-full min-h-[300px] rounded-[10px] border-0"}
    />
  );
}
