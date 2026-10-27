"use client";

import { useEffect, useId, useRef, type CSSProperties, type ReactNode } from "react";
import { Pause, Play } from "lucide-react";

import { HeroFrame } from "@/components/site/PageHero";
import { MoreLink } from "@/components/site/open-layout";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAutoplay } from "@/hooks/useAutoplay";
import { useOffscreen } from "@/hooks/useOffscreen";
import { cn } from "@/lib/utils";

import styles from "./OrganizerTabs.module.css";

/** How long each tab holds the stage. */
const INTERVAL_MS = 6000;

/** A switch tips the window further back and lets it settle: this is the deepest point, 40% in. */
const RETILT: Keyframe[] = [
  { offset: 0.4, transform: "rotateY(-24deg) rotateX(10deg) rotateZ(-2.5deg) translateZ(-40px)" }
];

/** The `rail` tab, grown into a row with a leading box, a title and the line that opens under the active one. */
export const RAIL_TAB_CLASS = cn(
  "h-auto items-start gap-3.5 rounded-l-none py-2.5 pl-4 pr-3 text-left before:hidden md:h-auto [&_svg]:size-4.5",
  "data-[state=active]:bg-transparent data-[state=active]:bg-[linear-gradient(90deg,color-mix(in_srgb,var(--aqt-teal)_9%,transparent),transparent_85%)]"
);

/** The rail itself: the tabs on one rule, which the active tab's line covers. */
export const RAIL_LIST_CLASS = "gap-0 border-l-2 border-[color:var(--aqt-border-2)]";

const ICON_CLASS = cn(
  "grid size-9.5 shrink-0 place-items-center rounded-[10px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-faint)] transition-[color,background-color,border-color,box-shadow] duration-300",
  "group-data-[state=active]:border-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)] group-data-[state=active]:bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] group-data-[state=active]:text-[color:var(--aqt-teal)] group-data-[state=active]:shadow-[0_0_22px_-6px_color-mix(in_srgb,var(--aqt-teal)_70%,transparent)]"
);

/**
 * The active rail tab's line over the list's rule: whole while the tabs stand
 * still, filling over `ms` while they turn. Its tab must be the positioning box.
 */
export function AutoplayRail({ running, ms }: Readonly<{ running: boolean; ms: number }>) {
  return (
    <span aria-hidden className={cn(styles.rail, running && styles.run)} style={{ animationDuration: `${ms}ms` }} />
  );
}

/** The pause/play button of a turning block; it sits outside the block's hold, so it can lift it. */
export function AutoplayButton({
  autoplay,
  onToggle,
  labels
}: Readonly<{ autoplay: boolean; onToggle: () => void; labels: { pause: string; play: string } }>) {
  return (
    <Button variant="outline" size="sm" onClick={onToggle} className="rounded-full [&_svg]:size-3.5">
      {autoplay ? <Pause aria-hidden /> : <Play aria-hidden />}
      {autoplay ? labels.pause : labels.play}
    </Button>
  );
}

export interface OrganizerTab {
  key: string;
  icon: ReactNode;
  title: string;
  text: string;
  /** The page the window bar names. */
  page: string;
  alt: string;
  src: string;
  width: number;
  height: number;
  /** The docs article that sets it up: a link under the tabs while this tab is open. */
  href?: string;
}

/**
 * The organizer pitch's product tour (home banner, organizer page): the copy
 * (`children`), feature tabs and the call to action, in a plain hero frame
 * beside the active tab's screenshot (under them on a phone). From 768px the
 * screenshot sits in a browser window tipped back in 3D with a teal glow.
 *
 * The tabs turn by themselves every `INTERVAL_MS`, the active one's line
 * filling meanwhile. They wait while the block is off screen and while the
 * pointer or focus is on the tabs or the screenshot; the pause/play button
 * sits outside that hold, so it can lift it, and stops them for good. A click
 * or the arrow keys pick a tab. A tab with an `href` shows `labels.link` to it
 * under the tabs while it is open.
 */
export function OrganizerTabs({
  tabs,
  labels,
  textLines = 2,
  cta,
  children
}: Readonly<{
  tabs: readonly OrganizerTab[];
  labels: { inside: string; pause: string; play: string; link?: string };
  /** Lines the active tab's text keeps room for, so the frame holds its height while the tabs turn. */
  textLines?: number;
  cta?: ReactNode;
  children: ReactNode;
}>) {
  const insideId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const tiltRef = useRef<HTMLDivElement>(null);
  const { index, select, playing, autoplay, toggle, holdProps } = useAutoplay(
    tabs.length,
    INTERVAL_MS,
    useOffscreen(ref)
  );
  const shown = useRef(index);

  // Web Animations rather than a class: the same class on the next switch would
  // not replay. A phone lays the window flat; reduced motion keeps it still.
  useEffect(() => {
    if (shown.current === index) return;
    shown.current = index;
    if (!matchMedia("(min-width: 48rem) and (prefers-reduced-motion: no-preference)").matches) return;
    tiltRef.current?.animate(RETILT, { duration: 900, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" });
  }, [index]);

  const active = tabs[index];
  const textStyle: CSSProperties = { minHeight: `calc(${textLines * 1.5}em + 4px)` };

  return (
    // `clip`, not `hidden`: the screenshot bleeds past the edge, and a hidden
    // overflow is still a scroll container that focus could scroll it into.
    <HeroFrame variant="plain" className="overflow-clip">
      {/* The hero tint's bloom, at 13%: the hero's own 26% would sink the
          "What's inside" label, mid-left here, under AA. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(50%_140%_at_0%_100%,color-mix(in_srgb,var(--aqt-teal)_13%,transparent),transparent_70%)]"
      />
      <Tabs
        ref={ref}
        value={active.key}
        onValueChange={(value) => select(tabs.findIndex((tab) => tab.key === value))}
        orientation="vertical"
        className="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]"
      >
        <div className="px-[clamp(20px,4vw,56px)] pb-[clamp(28px,4vw,52px)] pt-[clamp(28px,4vw,56px)] lg:pr-0">
          {children}
          <div className="mt-7 flex items-center justify-between gap-3">
            <Eyebrow id={insideId}>{labels.inside}</Eyebrow>
            <AutoplayButton autoplay={autoplay} onToggle={toggle} labels={labels} />
          </div>
          <TabsList variant="rail" aria-labelledby={insideId} className={cn("mt-2.5", RAIL_LIST_CLASS)} {...holdProps}>
            {tabs.map((tab, position) => (
              <TabsTrigger key={tab.key} value={tab.key} className={RAIL_TAB_CLASS}>
                {position === index ? <AutoplayRail running={playing} ms={INTERVAL_MS} /> : null}
                <span className={ICON_CLASS}>{tab.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block pt-2 font-display text-ui font-semibold">{tab.title}</span>
                  {/* Only the active tab's text shows; the room it keeps holds the frame's height while the tabs turn. */}
                  <span className="grid grid-rows-[0fr] transition-[grid-template-rows] duration-[450ms] ease-[cubic-bezier(0.2,0.8,0.2,1)] group-data-[state=active]:grid-rows-[1fr] motion-reduce:transition-none">
                    <span className="overflow-hidden">
                      <span
                        className="block text-pretty pt-1 text-body font-normal text-[color:var(--aqt-fg-muted)]"
                        style={textStyle}
                      >
                        {tab.text}
                      </span>
                    </span>
                  </span>
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
          {active.href && labels.link ? (
            <MoreLink href={active.href} className="mt-4">
              {labels.link}
            </MoreLink>
          ) : null}
          {cta ? <div className="mt-6">{cta}</div> : null}
        </div>
        {/* One panel for every tab: its screenshots stay mounted, so a switch crossfades instead of loading. */}
        <TabsContent value={active.key} className={styles.stage} {...holdProps}>
          <div ref={tiltRef} className={styles.tilt}>
            <div className={styles.screen}>
              <div
                aria-hidden
                className="flex h-7.5 items-center gap-1.5 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-3"
              >
                {[0, 1, 2].map((dot) => (
                  <span key={dot} className="size-[9px] rounded-full bg-[color:var(--aqt-border-3)]" />
                ))}
                <span className="ml-2.5 truncate text-label text-[color:var(--aqt-fg-faint)]">{active.page}</span>
              </div>
              <div className="relative aspect-[1440/1000]">
                {tabs.map((tab, position) => (
                  <Image
                    key={tab.key}
                    src={tab.src}
                    width={tab.width}
                    height={tab.height}
                    sizes="(min-width: 1024px) 860px, (min-width: 768px) 104vw, 100vw"
                    alt={position === index ? tab.alt : ""}
                    className={cn(
                      "absolute inset-0 size-full object-cover object-left-top",
                      styles.shot,
                      position === index && styles.on
                    )}
                  />
                ))}
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </HeroFrame>
  );
}
