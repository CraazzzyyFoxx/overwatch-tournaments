"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
  type ReactNode
} from "react";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { SectionHead } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { cn } from "@/lib/utils";

/**
 * The community catalogue as a carousel. Everything moves in WHOLE cards:
 * positions are card indices, a stop is index × (card + gap), the last stop is
 * cards − perView, so a card is never cut in half.
 *
 * The arrows step one card and wrap: next on the last stop returns to the
 * first, prev on the first jumps to the last. Autoplay advances one card every
 * 6 s and rewinds the same way. It waits while
 * the pointer is over the section, focus is inside it, the rail is off-screen
 * or the tab is hidden, and it is OFF by default under prefers-reduced-motion.
 * Any manual navigation (arrows, dots, drag, wheel, swipe, keys) turns it off
 * for good — the visitor has taken over; the pause/play button turns it back
 * on (WCAG 2.2.2: pause/play and navigation are available on every viewport).
 *
 * Drag is mouse-only — touch already swipes natively. Past a 6 px threshold the
 * drag owns the gesture, the click that ends it is swallowed, and the rail
 * lands on the nearest card.
 */
const AUTOPLAY_MS = 6000;
const GAP = 32;
const DRAG_THRESHOLD = 6;
const TAKEOVER_KEYS = ["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"];
const RAIL_ID = "home-directory-rail";

interface RailMetrics {
  index: number;
  /** How many whole-card stops there are — one dot each. */
  stops: number;
  perView: number;
  cards: number;
  overflow: boolean;
}

const INITIAL: RailMetrics = {
  index: 0,
  stops: 1,
  perView: 1,
  cards: 0,
  overflow: false
};

// Reduced motion decides the DEFAULT autoplay state, which the pause/play
// button renders, so it is read through `useSyncExternalStore`: the server
// snapshot (motion allowed) hydrates without a mismatch and the real value
// lands on the first client render.
const REDUCE_MOTION = "(prefers-reduced-motion: reduce)";

function subscribeReduceMotion(onChange: () => void) {
  const query = window.matchMedia(REDUCE_MOTION);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function DirectoryRail({
  titleId,
  children
}: Readonly<{ titleId: string; children: ReactNode }>) {
  const t = useTranslations("home.directory");
  const railRef = useRef<HTMLDivElement>(null);
  const [metrics, setMetrics] = useState<RailMetrics>(INITIAL);
  const reduceMotion = useSyncExternalStore(
    subscribeReduceMotion,
    () => window.matchMedia(REDUCE_MOTION).matches,
    () => false
  );
  // `null` = still following the reduced-motion default; a boolean is the
  // visitor's own decision, and a take-over is a stop that sticks.
  const [override, setOverride] = useState<boolean | null>(null);
  const autoplay = override ?? !reduceMotion;
  const [dragging, setDragging] = useState(false);

  // Autoplay gates and drag bookkeeping: read inside listeners and the tick,
  // never rendered, so they are refs rather than state.
  const hovered = useRef(false);
  const focused = useRef(false);
  const visible = useRef(true);
  const draggingRef = useRef(false);
  const lastStep = useRef(0);

  const pointerId = useRef<number | null>(null);
  const moved = useRef(false);
  const startX = useRef(0);
  const startLeft = useRef(0);

  const geometry = useCallback(() => {
    const rail = railRef.current;
    const card = rail?.querySelector("li");
    if (!rail || !card) return null;
    const step = card.getBoundingClientRect().width + GAP;
    if (step <= 0) return null;
    const cards = rail.querySelectorAll("li").length;
    const perView = Math.max(1, Math.round((rail.clientWidth + GAP) / step));
    const lastIndex = Math.max(0, cards - perView);
    const maxLeft = rail.scrollWidth - rail.clientWidth;
    return {
      rail,
      step,
      cards,
      perView,
      lastIndex,
      maxLeft,
      index: Math.min(lastIndex, Math.round(rail.scrollLeft / step))
    };
  }, []);

  const measure = useCallback(() => {
    const geo = geometry();
    if (!geo) return;
    setMetrics({
      index: geo.index,
      stops: geo.lastIndex + 1,
      perView: geo.perView,
      cards: geo.cards,
      overflow: geo.maxLeft > 1
    });
  }, [geometry]);

  const goTo = useCallback(
    (target: number, smooth = true) => {
      const geo = geometry();
      if (!geo) return;
      geo.rail.scrollTo({
        left: Math.min(geo.maxLeft, Math.max(0, Math.min(geo.lastIndex, target)) * geo.step),
        behavior: smooth && !reduceMotion ? "smooth" : "auto"
      });
    },
    [geometry, reduceMotion]
  );

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    rail.addEventListener("scroll", measure, { passive: true });
    // Fires once on observe (the first measurement) and again on every
    // breakpoint change, which alters cards-per-view: re-seat on the same
    // card, instantly.
    const resize = new ResizeObserver(() => {
      const geo = geometry();
      if (geo) goTo(geo.index, false);
      measure();
    });
    resize.observe(rail);
    const intersection = new IntersectionObserver(
      ([entry]) => {
        visible.current = entry.isIntersecting;
      },
      { threshold: 0.5 }
    );
    intersection.observe(rail);
    return () => {
      rail.removeEventListener("scroll", measure);
      resize.disconnect();
      intersection.disconnect();
    };
  }, [geometry, goTo, measure]);

  useEffect(() => {
    if (!autoplay) return;
    lastStep.current = Date.now();
    const tick = setInterval(() => {
      const geo = geometry();
      if (
        !geo ||
        hovered.current ||
        focused.current ||
        !visible.current ||
        draggingRef.current ||
        document.hidden ||
        geo.maxLeft <= 1
      ) {
        lastStep.current = Date.now();
        return;
      }
      if (Date.now() - lastStep.current < AUTOPLAY_MS) return;
      lastStep.current = Date.now();
      goTo(geo.index >= geo.lastIndex ? 0 : geo.index + 1);
    }, 250);
    return () => clearInterval(tick);
  }, [autoplay, geometry, goTo]);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== "mouse" || event.button !== 0) return;
    pointerId.current = event.pointerId;
    startX.current = event.clientX;
    startLeft.current = event.currentTarget.scrollLeft;
    moved.current = false;
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerId !== pointerId.current) return;
    const dx = event.clientX - startX.current;
    if (!moved.current) {
      if (Math.abs(dx) < DRAG_THRESHOLD) return;
      moved.current = true;
      draggingRef.current = true;
      setDragging(true);
      setOverride(false);
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    event.currentTarget.scrollLeft = startLeft.current - dx;
  };

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerId !== pointerId.current) return;
    pointerId.current = null;
    if (!moved.current) return;
    draggingRef.current = false;
    setDragging(false);
    // Land on the nearest whole card, then hand snapping back to CSS.
    const geo = geometry();
    if (geo) goTo(Math.round(geo.rail.scrollLeft / geo.step));
  };

  const navButton = owtButton({
    variant: "ghost",
    size: "icon",
    className:
      "size-11 text-[color:var(--aqt-fg-dim)] hover:bg-transparent hover:text-[color:var(--aqt-teal)] [&_svg]:size-5"
  });

  return (
    <div
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") hovered.current = true;
      }}
      onPointerLeave={() => {
        hovered.current = false;
      }}
    >
      <SectionHead title={t("title")} titleId={titleId} sub={t("sub")} />

      {/* ≥1440px: the grid bleeds 44px + 12px gap past each side, so the rail spans the full container and the arrows sit outside it. */}
      <div className="grid grid-cols-[44px_minmax(0,1fr)_44px] items-center gap-x-2 md:gap-x-3 min-[1440px]:-mx-14">
        <button
          type="button"
          className={cn(
            navButton,
            "col-start-1 row-start-3 md:row-start-1",
            !metrics.overflow && "hidden"
          )}
          aria-controls={RAIL_ID}
          aria-label={t("prev")}
          onClick={() => {
            setOverride(false);
            goTo(metrics.index <= 0 ? metrics.stops - 1 : metrics.index - 1);
          }}
        >
          <ChevronLeft aria-hidden strokeWidth={1.5} />
        </button>
        <div
          ref={railRef}
          id={RAIL_ID}
          role="group"
          aria-label={t("railLabel")}
          tabIndex={0}
          data-dragging={dragging || undefined}
          className={cn(
            "col-span-3 row-start-1 md:col-span-1 md:col-start-2",
            "snap-x snap-mandatory overflow-x-auto overscroll-x-contain py-0.5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            "[@media(pointer:fine)]:cursor-grab",
            "data-[dragging]:cursor-grabbing data-[dragging]:snap-none data-[dragging]:select-none data-[dragging]:[&_a]:pointer-events-none"
          )}
          onFocus={() => {
            focused.current = true;
          }}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) focused.current = false;
          }}
          onWheel={(event) => {
            if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) setOverride(false);
          }}
          onTouchStart={() => setOverride(false)}
          onKeyDown={(event) => {
            if (TAKEOVER_KEYS.includes(event.key)) setOverride(false);
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onClickCapture={(event) => {
            if (!moved.current) return;
            event.preventDefault();
            event.stopPropagation();
            moved.current = false;
          }}
          onDragStart={(event) => event.preventDefault()}
        >
          <ul className="grid auto-cols-[100%] grid-flow-col gap-8 min-[640px]:auto-cols-[calc((100%-32px)/2)] min-[1100px]:auto-cols-[calc((100%-2*32px)/3)]">
            {children}
          </ul>
        </div>
        <button
          type="button"
          className={cn(
            navButton,
            "col-start-3 row-start-3 md:row-start-1",
            !metrics.overflow && "hidden"
          )}
          aria-controls={RAIL_ID}
          aria-label={t("next")}
          onClick={() => {
            setOverride(false);
            goTo(metrics.index >= metrics.stops - 1 ? 0 : metrics.index + 1);
          }}
        >
          <ChevronRight aria-hidden strokeWidth={1.5} />
        </button>

        <div
          className={cn(
            "contents md:col-span-3 md:col-start-1 md:row-start-2 md:mt-3 md:flex md:items-center md:justify-center md:gap-x-2",
            !metrics.overflow && "hidden md:hidden"
          )}
        >
          <div
            role="group"
            aria-label={t("dotsLabel")}
            className="col-span-3 row-start-2 mt-3 flex max-w-full flex-wrap justify-center gap-0.5 md:mt-0"
          >
            {Array.from({ length: metrics.stops }).map((_, stop) => (
              <button
                key={stop}
                type="button"
                className="group inline-flex size-11 items-center justify-center rounded-md sm:size-6"
                aria-current={stop === metrics.index}
                aria-label={
                  metrics.perView > 1
                    ? t("dotRange", {
                        from: stop + 1,
                        to: stop + metrics.perView,
                        total: metrics.cards
                      })
                    : t("dotOne", { index: stop + 1, total: metrics.cards })
                }
                onClick={() => {
                  setOverride(false);
                  goTo(stop);
                }}
              >
                <span className="block size-1.5 rounded-full bg-[color:var(--aqt-border-3)] transition-[width,background-color] duration-200 group-hover:bg-[color:var(--aqt-fg-faint)] group-aria-[current=true]:w-[18px] group-aria-[current=true]:bg-[color:var(--aqt-teal)]" />
              </button>
            ))}
          </div>
          <button
            type="button"
            className={cn(navButton, "col-start-2 row-start-3 justify-self-center")}
            aria-controls={RAIL_ID}
            aria-label={autoplay ? t("pause") : t("play")}
            onClick={() => {
              lastStep.current = Date.now();
              setOverride(!autoplay);
            }}
          >
            {autoplay ? (
              <Pause aria-hidden strokeWidth={1.5} />
            ) : (
              <Play aria-hidden strokeWidth={1.5} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
