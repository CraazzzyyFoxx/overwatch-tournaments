"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { SocialIcon } from "@/components/social/SocialIcon";
import { formatStreamUptime, streamPlatformLabel } from "@/lib/social/stream-platform";
import { cn } from "@/lib/utils";
import type { StreamEntry } from "@/types/stream.types";

type StreamRowProps = {
  entry: StreamEntry;
  /** Whether this row is the one in the theater. Ignored for link rows. */
  isSelected: boolean;
  /**
   * Put this entry in the theater. `null` for an entry that cannot carry a
   * frame — the row then becomes an outbound link instead of a picker.
   */
  onSelect: (() => void) | null;
  /** Clock for the uptime line, passed in so the caller owns the tick. */
  now: number | null;
};

// 12 = 4 + 8: the row's radius is the thumbnail's plus the row padding, so the
// nested corners are concentric instead of pinched (`better-ui`).
const ROW_SHELL =
  "group flex w-full items-center gap-3 rounded-[12px] border p-2 text-left outline-none transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]";

/**
 * One channel in the rail beside the theater.
 *
 * ## Why a row and not a card
 *
 * This list is a SWITCHER, not the content. The previous card grid gave every
 * channel a 16:9 hero, which meant six 400px tiles, a page you had to scroll to
 * count what was live, and rows whose height was set by whichever streamer had
 * written the longest title. A row is ~80px, so the whole line-up is visible
 * next to a player that finally gets the pixels.
 *
 * ## Why the whole row is one control
 *
 * The old card put the only click target on 13.5px of title text while a
 * 442x248 thumbnail sat inert beside it. Here the entire row is the target.
 * That rules out nesting the player's profile link inside it — nested
 * interactive elements are invalid and unreachable by keyboard — so the profile
 * link lives once, in `StreamTheater`, on whoever is actually in the frame.
 *
 * ## Reading order
 *
 * Player first, stream title second. On a tournament page the question is "who
 * is streaming", and a channel's own title is written for its own audience: it
 * is flavour, clamped to one line, and never allowed to set the row height.
 */
export function StreamRow({ entry, isSelected, onSelect, now }: Readonly<StreamRowProps>) {
  const t = useTranslations();
  const name = entry.player?.name ?? entry.channel;
  const uptime = formatStreamUptime(
    entry.started_at,
    { h: t("common.duration.h"), m: t("common.duration.m") },
    now
  );

  const body = (
    <>
      {/* The inset outline is the standard hairline on an image: the palette is
          clamped dark, so it is white-alpha — a tinted neutral would pick up
          the surface underneath and read as dirt on the thumbnail edge. */}
      <span className="relative aspect-video w-[104px] shrink-0 overflow-hidden rounded-[4px] bg-[color:var(--aqt-overlay-3)] outline outline-1 -outline-offset-1 outline-[oklch(1_0_0_/_0.1)]">
        {entry.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={entry.thumbnail_url}
            alt=""
            aria-hidden
            loading="lazy"
            className="size-full object-cover"
          />
        ) : (
          <span className="flex size-full items-center justify-center opacity-50">
            <SocialIcon provider={entry.platform} size={16} />
          </span>
        )}
        {isSelected && onSelect ? (
          <span
            aria-hidden
            className="absolute inset-x-0 bottom-0 h-[3px] bg-[color:var(--aqt-teal)]"
          />
        ) : null}
      </span>

      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex min-w-0 items-baseline gap-2">
          <span
            className={cn(
              "truncate text-caption font-semibold",
              isSelected ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg)]"
            )}
          >
            {name}
          </span>
          {entry.player?.team ? (
            <span className="truncate text-label text-[color:var(--aqt-fg-muted)]">
              {entry.player.team.name}
            </span>
          ) : null}
        </span>

        <span className="flex min-w-0 items-center gap-2">
          {entry.viewer_count != null ? (
            <span className="aqt-tnum shrink-0 text-label font-semibold tabular-nums text-[color:var(--aqt-fg-dim)]">
              {t("stream.card.watching", { count: entry.viewer_count })}
            </span>
          ) : null}
          {uptime ? (
            <span className="aqt-tnum shrink-0 text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
              <span className="sr-only">{t("stream.card.onAir", { duration: uptime })}</span>
              <span aria-hidden>{uptime}</span>
            </span>
          ) : null}
          {onSelect ? null : (
            <span className="inline-flex shrink-0 items-center gap-1 text-label text-[color:var(--aqt-fg-dim)]">
              <ExternalLink className="size-3" aria-hidden />
              {streamPlatformLabel(entry)}
            </span>
          )}
        </span>

        {/* Clamped to one line on purpose. Stream titles run to 130 characters
            of emoji; letting one of them set the row height is what made the
            old grid ragged. */}
        {entry.title ? (
          <span className="truncate text-label text-[color:var(--aqt-fg-muted)]">
            {entry.title}
          </span>
        ) : null}
      </span>
    </>
  );

  if (!onSelect) {
    return (
      <a
        href={entry.url}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          ROW_SHELL,
          "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] no-underline hover:border-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-overlay-2)]"
        )}
      >
        {body}
      </a>
    );
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      // `aria-current` and not `aria-pressed`: this is "the one being shown" out
      // of a set, not an independent toggle the viewer can switch back off.
      aria-current={isSelected ? "true" : undefined}
      className={cn(
        ROW_SHELL,
        isSelected
          ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,transparent)]"
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] hover:border-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-overlay-2)]"
      )}
    >
      <span className="sr-only">{t("stream.card.select", { name })}</span>
      {body}
    </button>
  );
}

export default StreamRow;
