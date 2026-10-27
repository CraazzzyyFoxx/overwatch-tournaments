"use client";

import { type ReactNode, useLayoutEffect, useRef } from "react";
import { Pause, Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { useAutoplay } from "@/hooks/useAutoplay";
import { useOffscreen } from "@/hooks/useOffscreen";
import { cn } from "@/lib/utils";

import styles from "./HeroFeed.module.css";

/** What a card is: a title decided (`won`), a player's feat (`carried`), a series' maps (`maps`). Its tag follows it. */
export type FeedKind = "won" | "carried" | "maps";

export interface FeedItem {
  key: string;
  kind: FeedKind;
  /** The card, drawn on the server. */
  card: ReactNode;
}

/** How long a card stays on top. */
const INTERVAL_MS = 4800;

/** Cards drawn: the window shows about four, the next fades out under its mask. */
const SHOWN = 5;

/** A step's slide. */
const STEP: KeyframeAnimationOptions = { duration: 650, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" };

const TITLE_ID = "home-feed-title";

const HEAD_CLASS = "flex min-h-8 items-center justify-between gap-3";

/** The kicker: its label after a teal dot. */
const KICKER_CLASS =
  "flex items-center gap-2 before:size-[7px] before:flex-none before:rounded-full before:bg-[color:var(--aqt-teal)] before:shadow-[0_0_0_3px_color-mix(in_srgb,var(--aqt-teal)_20%,transparent)] before:content-['']";

/** The progress track under the head; it keeps its room under reduced motion, where nothing moves. */
const TRACK_CLASS = "mb-3 mt-2.5 h-0.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]";

/**
 * A fixed window, the cards fading out at its foot. The negative margin gives a
 * card's glow room inside the clip.
 */
const WINDOW_CLASS =
  "-m-1.5 h-[360px] overflow-hidden p-1.5 [mask-image:linear-gradient(var(--aqt-bg)_72%,transparent)] sm:h-[392px]";

/**
 * The hero's results feed: finals, records and the latest series' maps as a
 * column of cards. Every `INTERVAL_MS` the next card slides in on top and
 * pushes the others down, the line under the head filling meanwhile. It waits
 * while the pointer is over the cards, focus is inside them or the feed is
 * mostly off screen; the button stops and restarts it for good. Under reduced
 * motion it is a still list.
 */
export function HeroFeedRotator({ items }: Readonly<{ items: readonly FeedItem[] }>) {
  const t = useTranslations("home.hero.feed");
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const offscreen = useOffscreen(root);
  const count = items.length;
  const { index, playing, autoplay, toggle, holdProps } = useAutoplay(count, INTERVAL_MS, offscreen);
  // The list's head fills the window at load, top down; each step then brings
  // an unseen card on top, walking `items` from its end.
  const shown = Array.from({ length: Math.min(SHOWN, count) }, (_, depth) => items[(depth - index + count) % count]);

  // Every card below the new one moves down by the same height, so one slide of
  // the list is the FLIP of all of them; the new card enters from above the
  // window's clip. `data-stepped` lets the arrival glow (the module) skip the
  // card on top at load.
  const last = useRef(index);
  useLayoutEffect(() => {
    const ol = list.current;
    if (!ol || last.current === index) return;
    last.current = index;
    ol.dataset.stepped = "";
    const top = ol.firstElementChild as HTMLElement;
    const shift = top.offsetHeight + parseFloat(getComputedStyle(ol).rowGap);
    ol.animate([{ transform: `translateY(${-shift}px)` }, { transform: "none" }], STEP);
    top.animate([{ opacity: 0, transform: "scale(0.96)" }, { opacity: 1, transform: "none" }], STEP);
  }, [index]);

  return (
    <div ref={root} role="group" aria-labelledby={TITLE_ID} className="min-w-0">
      <div className={HEAD_CLASS}>
        <Eyebrow id={TITLE_ID} className={KICKER_CLASS}>
          {t("title")}
        </Eyebrow>
        {/* Beside the cards, not among them: pointing at or focusing the
            button must not count as the wait it is there to lift. */}
        {count > 1 ? (
          <Button variant="outline" size="sm" onClick={toggle} className="motion-reduce:hidden">
            {autoplay ? <Pause aria-hidden /> : <Play aria-hidden />}
            {t(autoplay ? "pause" : "play")}
          </Button>
        ) : null}
      </div>
      <div aria-hidden className={cn(TRACK_CLASS, "motion-reduce:invisible")}>
        {/* Mounted only while the feed moves, so a resume draws it from empty with its fresh interval. */}
        {playing ? (
          <span
            key={index}
            className="block h-full origin-left bg-[color:var(--aqt-teal)]"
            style={{ animation: `aqt-grow-x ${INTERVAL_MS}ms linear both` }}
          />
        ) : null}
      </div>
      <div className={WINDOW_CLASS} {...holdProps}>
        <ol ref={list} className={cn("flex flex-col gap-2.5", styles.list)}>
          {shown.map((item) => (
            <li key={item.key}>{item.card}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}

/** The feed's shape while it reads: the head, the track and four cards in the window. */
export function HeroFeedSkeleton() {
  return (
    <div aria-hidden className="min-w-0">
      <div className={HEAD_CLASS}>
        <Skeleton className="h-4 w-44" />
        <Skeleton className="h-8 w-24" />
      </div>
      <div className={TRACK_CLASS} />
      <div className={cn(WINDOW_CLASS, "flex flex-col gap-2.5")}>
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[118px] w-full flex-none rounded-[var(--aqt-radius)]" />
        ))}
      </div>
    </div>
  );
}
