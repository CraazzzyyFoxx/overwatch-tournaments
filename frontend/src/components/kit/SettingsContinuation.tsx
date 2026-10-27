"use client";

import {
  createContext,
  useContext,
  useEffect,
  useEffectEvent,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp } from "lucide-react";

import { eyebrowClass } from "@/components/ui/eyebrow";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { holdScrollPosition } from "@/lib/scroll-hold";

const PreviewContext = createContext(false);
const UnsavedReportContext = createContext<((unsaved: boolean) => void) | null>(null);

/**
 * True inside the next page's preview: the page renders for show only, so
 * whatever it would do to its surroundings (list its groups in the outline,
 * put controls in the page header, poll, report unsaved edits) it must not.
 */
export function useInSettingsPreview(): boolean {
  return useContext(PreviewContext);
}

/** Tells the enclosing `SettingsContinuation` whether leaving now would lose edits. */
export function useReportUnsaved(unsaved: boolean) {
  const report = useContext(UnsavedReportContext);
  useEffect(() => {
    if (!report) return;
    report(unsaved);
    return () => report(false);
  }, [report, unsaved]);
}

export interface SettingsAdjacentPage {
  href: string;
  title: string;
}

export interface SettingsNextPage extends SettingsAdjacentPage {
  /** The next page itself, rendered inert under a fade. */
  preview: ReactNode;
}

export type Edge = "top" | "bottom";

/** Scroll intent past the end (or the top) of the page that opens its neighbour. */
const PULL_DISTANCE_PX = 360;
/** A pause this long lets an unfinished pull fall back to nothing. */
const PULL_RESET_MS = 600;
const KEY_STEP_PX = 120;
/**
 * A wheel gesture that opened a page keeps coasting into the next one; pulls
 * count again only after the wheel has been quiet this long.
 */
const WHEEL_QUIET_MS = 250;
/** Long enough for a lazy editor or a late query to land under a held page end. */
const LANDING_HOLD_MS = 3000;

/**
 * The page change itself, the one entrance animation the admin has (DESIGN
 * §10): it says which way the reader went. Going on, the old page lifts away
 * and the new one rises from below, where its ghost was; coming back, both
 * move the other way. Leaving is shorter than arriving, and leaves the old
 * page dimmed rather than gone in case the next one is slow to render.
 */
const ENTER_MS = 320;
const LEAVE_MS = 180;
const SHIFT_PX = 32;

/** `edge` is where the new page lands: "top" going on, "bottom" coming back. */
function playLeave(page: HTMLElement | null, edge: Edge) {
  if (!page) return;
  const shift = edge === "top" ? -SHIFT_PX / 2 : SHIFT_PX / 2;
  page.animate?.(
    [
      { opacity: 1, transform: "none" },
      { opacity: 0.2, transform: `translateY(${shift}px)` }
    ],
    { duration: LEAVE_MS, easing: "cubic-bezier(0.4, 0, 1, 1)", fill: "forwards" }
  );
}

/** Also the rail's page change (`SectionNav`), so the admin keeps one entrance. */
export function playEnter(page: HTMLElement | null, edge: Edge) {
  if (!page) return;
  const shift = edge === "top" ? SHIFT_PX : -SHIFT_PX;
  page.animate?.(
    [
      { opacity: 0, transform: `translateY(${shift}px)` },
      { opacity: 1, transform: "none" }
    ],
    { duration: ENTER_MS, easing: "cubic-bezier(0.2, 0, 0, 1)" }
  );
}

const atPageEnd = () =>
  window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
const atPageTop = () => window.scrollY <= 0;

/** A dialog or popover owns the wheel while it is open (Radix locks the body). */
const overlayOpen = () => document.body.hasAttribute("data-scroll-locked");

/** Which way a page-scrolling key goes: 1 down, -1 up, 0 not one of them. */
function keyDirection(event: KeyboardEvent): 1 | -1 | 0 {
  if (event.key === " ") return event.shiftKey ? -1 : 1;
  if (event.key === "PageDown" || event.key === "ArrowDown" || event.key === "End") return 1;
  if (event.key === "PageUp" || event.key === "ArrowUp" || event.key === "Home") return -1;
  return 0;
}

/**
 * The page a pull just opened, and which edge it opens at. The router's own
 * scroll would land the reader on the page body; going on lands at the new
 * page's top, coming back at the previous page's end, where the reader left
 * it. Consumed by that page's `SettingsContinuation` on mount.
 */
let continued: { href: string; edge: Edge } | null = null;

function continueTo(href: string, edge: Edge) {
  continued = { href, edge };
}

/**
 * A settings page between its neighbours, so the reader can scroll through
 * the hub without the rail.
 *
 * Below the page sits a ghost of the next one: its own render, inert and
 * faded, cut off at a fixed height, under a link that covers it. Past the end,
 * more scrolling (wheel, a swipe, PageDown or Space with nothing focused)
 * fills a bar and opens it. Above, past the top, scrolling up (wheel, PageUp,
 * Shift+Space) fills a pill naming the previous page and opens that one at its
 * end. A downward swipe at the top is left alone: it is the browser's
 * pull-to-refresh.
 *
 * Pulling is off while the page has unsaved edits — scrolling must never be
 * the way to lose them — and under reduced motion, where the bar would be the
 * motion. The ghost's link works in both, through the usual discard prompt.
 */
export function SettingsContinuation({
  previous,
  next,
  children
}: Readonly<{
  previous: SettingsAdjacentPage | null;
  next: SettingsNextPage | null;
  children: ReactNode;
}>) {
  const t = useTranslations("kit.settings");
  const router = useRouter();
  const [unsaved, setUnsaved] = useState(false);
  const reduced = usePrefersReducedMotion();
  const pullable = !unsaved && !reduced;
  const aheadRef = useRef<HTMLElement>(null);
  const behindRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const landing = useRef<Edge | null>(null);
  const nextHref = next?.href ?? null;
  const previousHref = previous?.href ?? null;

  // An Effect Event: the mount effect below reads the current preference and stays one-shot.
  const enter = useEffectEvent((edge: Edge) => {
    if (!reduced) playEnter(pageRef.current, edge);
  });

  // Before paint, so the page never shows a frame at the old scroll offset
  // and the entrance starts from its first keyframe. The edge is kept in a
  // ref: a Strict Mode remount must land the same way.
  useLayoutEffect(() => {
    if (continued?.href === window.location.pathname) {
      landing.current = continued.edge;
      continued = null;
    }
    if (!landing.current) return;
    enter(landing.current);
    if (landing.current === "top") {
      window.scrollTo({ top: 0 });
      return;
    }
    return holdScrollPosition(
      () => window.scrollTo({ top: document.documentElement.scrollHeight }),
      LANDING_HOLD_MS
    );
  }, []);

  useEffect(() => {
    if (!pullable || (!nextHref && !previousHref)) return;
    const ahead = aheadRef.current;
    const behind = behindRef.current;
    // A pull is a promise to open these; have them ready when it completes.
    if (nextHref) router.prefetch(nextHref);
    if (previousHref) router.prefetch(previousHref);

    // Progress lives in CSS variables, not state: a wheel event per frame
    // must not re-render the ghost, which is a whole settings page.
    let forward = 0;
    let back = 0;
    let gone = false;
    let resetTimer = 0;
    let lastWheel = performance.now();
    let wheelArmed = false;
    let touchY: number | null = null;

    const paint = () => {
      ahead?.style.setProperty("--pull", String(Math.min(forward / PULL_DISTANCE_PX, 1)));
      behind?.style.setProperty("--pull", String(Math.min(back / PULL_DISTANCE_PX, 1)));
    };
    const reset = () => {
      forward = 0;
      back = 0;
      paint();
    };
    const go = (href: string, edge: Edge) => {
      gone = true;
      continueTo(href, edge);
      playLeave(pageRef.current, edge);
      router.push(href, { scroll: false });
    };
    /** `delta` > 0 pulls on past the end, < 0 back past the top. */
    const pull = (delta: number) => {
      if (gone || overlayOpen()) return;
      if (nextHref && atPageEnd() && (delta > 0 || forward > 0)) {
        forward = Math.max(0, forward + delta);
      } else if (previousHref && atPageTop() && (delta < 0 || back > 0)) {
        back = Math.max(0, back - delta);
      } else {
        return;
      }
      paint();
      window.clearTimeout(resetTimer);
      if (nextHref && forward >= PULL_DISTANCE_PX) return go(nextHref, "top");
      if (previousHref && back >= PULL_DISTANCE_PX) return go(previousHref, "bottom");
      resetTimer = window.setTimeout(reset, PULL_RESET_MS);
    };

    const onWheel = (event: WheelEvent) => {
      const now = performance.now();
      const quiet = now - lastWheel > WHEEL_QUIET_MS;
      lastWheel = now;
      if (!wheelArmed && !quiet) return;
      wheelArmed = true;
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1;
      pull(event.deltaY * unit);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      // Only page scrolling: with a field or a button focused these keys are theirs.
      if (event.target !== document.body) return;
      const direction = keyDirection(event);
      if (direction) pull(direction * KEY_STEP_PX);
    };
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? null;
    };
    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY;
      if (touchY === null || y === undefined) return;
      const delta = touchY - y;
      touchY = y;
      if (delta > 0 || forward > 0) pull(delta);
    };
    const onTouchEnd = () => {
      touchY = null;
      if (!gone) reset();
    };

    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("touchend", onTouchEnd);
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.clearTimeout(resetTimer);
      ahead?.style.setProperty("--pull", "0");
      behind?.style.setProperty("--pull", "0");
    };
  }, [pullable, nextHref, previousHref, router]);

  const hint = unsaved ? t("nextBlocked") : pullable ? t("nextHint") : t("nextHintClick");

  // One element for the page and its neighbours, so the transition moves them
  // together; it repeats the column's own `gap-4` for the children inside.
  return (
    <UnsavedReportContext.Provider value={setUnsaved}>
      <div ref={pageRef} className="flex flex-col gap-4">
        {previous && pullable ? <PreviousPagePill title={previous.title} pillRef={behindRef} /> : null}
        {children}
        {next ? (
          <NextPageGhost
            next={next}
            hint={hint}
            ghostRef={aheadRef}
            onLeave={() => {
              if (!reduced) playLeave(pageRef.current, "top");
            }}
          />
        ) : null}
      </div>
    </UnsavedReportContext.Provider>
  );
}

/**
 * Names the page a pull past the top would open, and how far along the pull
 * is. Invisible until the reader pulls, and never a target: the rail and the
 * tabs are the way back by pointer and keyboard. Zero height (`-mb-4` cancels
 * the column's gap), so it overlays the top of the page instead of moving it.
 */
function PreviousPagePill({
  title,
  pillRef
}: Readonly<{ title: string; pillRef: RefObject<HTMLDivElement | null> }>) {
  return (
    <div aria-hidden className="pointer-events-none relative z-20 -mb-4 h-0">
      <div
        ref={pillRef}
        className="absolute inset-x-0 top-0 flex justify-center transition-opacity duration-150"
        style={{ "--pull": 0, opacity: "var(--pull)" } as CSSProperties}
      >
        <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-caption text-foreground">
          <ArrowUp className="size-3.5" />
          <span className="max-w-[16rem] truncate">{title}</span>
          <span className="h-0.5 w-10 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
            <span
              className="block h-full origin-left bg-primary transition-transform duration-150"
              style={{ transform: "scaleX(var(--pull))" }}
            />
          </span>
        </div>
      </div>
    </div>
  );
}

function NextPageGhost({
  next,
  hint,
  ghostRef,
  onLeave
}: Readonly<{
  next: SettingsNextPage;
  hint: string;
  ghostRef: RefObject<HTMLElement | null>;
  onLeave: () => void;
}>) {
  const t = useTranslations("kit.settings");
  const titleId = useId();

  return (
    <section
      ref={ghostRef}
      aria-labelledby={titleId}
      className="relative mt-6 border-t border-border pt-5"
      style={{ "--pull": 0 } as CSSProperties}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <p className={eyebrowClass("muted")}>{t("next")}</p>
          {/* The link's box covers the whole ghost: one target, one link. */}
          <Link
            id={titleId}
            href={next.href}
            scroll={false}
            onClick={(event) => {
              // A new-tab click leaves this page where it is.
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                return;
              }
              continueTo(next.href, "top");
              onLeave();
            }}
            className="mt-1 inline-flex items-center gap-1.5 text-heading font-semibold text-foreground transition-colors after:absolute after:inset-0 after:content-[''] hover:text-primary focus-visible:outline-hidden focus-visible:after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
          >
            {next.title}
            <ArrowDown aria-hidden className="size-4" />
          </Link>
        </div>
        <p className="text-caption text-muted-foreground">{hint}</p>
      </div>

      <div aria-hidden className="mt-3 h-0.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
        <div
          className="h-full origin-left bg-primary transition-transform duration-150"
          style={{ transform: "scaleX(var(--pull))" }}
        />
      </div>

      <div
        inert
        aria-hidden
        className="mt-4 max-h-72 overflow-hidden transition-opacity duration-150 [mask-image:linear-gradient(to_bottom,black_25%,transparent)]"
        style={{ opacity: "calc(0.4 + var(--pull) * 0.5)" }}
      >
        <PreviewContext.Provider value>
          <UnsavedReportContext.Provider value={null}>{next.preview}</UnsavedReportContext.Provider>
        </PreviewContext.Provider>
      </div>
    </section>
  );
}
