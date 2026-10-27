"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva } from "class-variance-authority";

import { StatusDot } from "@/components/ui/status-dot";
import { segmentedFrame, toggleVariants } from "@/components/ui/toggle";
import type { Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

type TabsVariant = "underline" | "pill" | "rail";

/**
 * A horizontal row scrolls without a scrollbar; an edge fades while there is
 * more row past it (`--fade-start`/`--fade-end`, set by `useTabRow`), which is
 * what says the row scrolls.
 */
const scrollRowClass =
  "group/tabs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden " +
  "[mask-image:linear-gradient(to_right,transparent,#000_var(--fade-start,0px),#000_calc(100%_-_var(--fade-end,0px)),transparent)]";

/**
 * The one tab look for the whole app, in two forms that share these classes:
 *
 * - `Tabs` below (Radix): state-driven tabs with panels — `role=tab/tabpanel`,
 *   roving focus, arrow keys. Sync to the URL yourself (`useQueryParams`) when
 *   the tab should survive a reload.
 * - `kit/LinkTabs`: routed tabs, one real link per tab with `aria-current`.
 *
 * Active-state selectors answer to BOTH `data-state=active` (Radix) and
 * `aria-current=page` (links), so the two cannot drift apart.
 *
 * `underline` is the default. `pill` is the site's segmented control drawing
 * (`segmentedFrame` + `toggleVariants`) for the rare mode switch that also owns
 * panels; a plain view/mode switch without panels is a `ToggleGroup`. `rail` is
 * a vertical section list beside its panels (the account settings dialog): an
 * overlay fill and a teal bar on the active row, 44px rows below `md`.
 */
const tabsListVariants = cva("", {
  variants: {
    variant: {
      // The baseline is an inset shadow, not a border: it paints under the
      // triggers, so the active underline covers it the way a tab sits on its
      // rule, without a wrapper around the scroll container.
      underline: cn(
        "relative flex w-full items-center gap-1 overflow-x-auto whitespace-nowrap shadow-[inset_0_-1px_0_hsl(var(--border))]",
        scrollRowClass
      ),
      pill: cn(segmentedFrame, "relative max-w-full overflow-x-auto", scrollRowClass),
      rail: "flex flex-col gap-0.5"
    }
  },
  defaultVariants: { variant: "underline" }
});

const tabsTriggerVariants = cva(
  "group shrink-0 cursor-pointer disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        // Inset ring: the list scrolls horizontally, which clips anything
        // drawn outside a trigger's box.
        underline: cn(
          "inline-flex h-9 items-center gap-1.5 border-b-2 border-transparent px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
          "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          "data-[state=active]:border-primary data-[state=active]:text-foreground",
          "aria-[current=page]:border-primary aria-[current=page]:text-foreground",
          // Once `useTabRow` has placed the sliding underline, the trigger's own
          // border steps aside; before that (server render) it is the underline.
          "group-data-[indicator]/tabs:data-[state=active]:border-transparent group-data-[indicator]/tabs:aria-[current=page]:border-transparent"
        ),
        pill: toggleVariants({ variant: "pill", size: "sm" }),
        rail: cn(
          "relative flex h-11 w-full items-center gap-2.5 rounded-md px-2.5 text-sm font-medium text-[color:var(--aqt-fg-muted)] transition-colors md:h-9",
          "hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-fg)]",
          "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          "before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-transparent",
          "data-[state=active]:bg-[color:var(--aqt-overlay-3)] data-[state=active]:text-[color:var(--aqt-fg)] data-[state=active]:before:bg-primary",
          "aria-[current=page]:bg-[color:var(--aqt-overlay-3)] aria-[current=page]:text-[color:var(--aqt-fg)] aria-[current=page]:before:bg-primary",
          "[&_svg]:size-4 [&_svg]:shrink-0"
        )
      }
    },
    defaultVariants: { variant: "underline" }
  }
);

const ACTIVE_TAB = '[role="tab"][data-state="active"], [aria-current="page"]';
const FADE = "24px";

/**
 * A horizontal tab row's behaviour, after Telegram's folder tabs, for both
 * `TabsList` and `kit/LinkTabs` — pass it as the list's `ref`:
 * - the active tab scrolls to the row's centre — at once on mount, so a deep
 *   link lands on it, smoothly after;
 * - the underline (`tabIndicatorClass`) slides to it through `--tab-x`/`--tab-w`;
 * - the edges fade while the row scrolls past them.
 * Horizontal only: `scrollIntoView` would also scroll the page to a row below
 * the fold. Watches the active marker and every tab's size, so a URL-driven
 * change, a badge or a late web font all keep the underline in place.
 */
function tabRowRef(list: HTMLElement | null) {
  if (!list) return;
  let active: HTMLElement | null = null;
  let frame = 0;

  const fade = () => {
    const rest = list.scrollWidth - list.clientWidth - list.scrollLeft;
    list.style.setProperty("--fade-start", list.scrollLeft > 1 ? FADE : "0px");
    list.style.setProperty("--fade-end", rest > 1 ? FADE : "0px");
  };

  const sync = () => {
    const tab = list.querySelector<HTMLElement>(ACTIVE_TAB);
    if (!tab) {
      delete list.dataset.indicator;
    } else {
      list.style.setProperty("--tab-x", `${tab.offsetLeft}px`);
      list.style.setProperty("--tab-w", `${tab.offsetWidth}px`);
      // Placed without animating first, then sliding from there on.
      if (!list.dataset.indicator) {
        list.dataset.indicator = "placed";
        frame = requestAnimationFrame(() => (list.dataset.indicator = "ready"));
      }
    }
    if (tab !== active) {
      const smooth = active !== null && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      active = tab;
      if (tab) {
        list.scrollTo({
          left: tab.offsetLeft + (tab.offsetWidth - list.clientWidth) / 2,
          behavior: smooth ? "smooth" : "instant"
        });
      }
    }
    fade();
  };

  const resize = new ResizeObserver(sync);
  const observeTabs = () => {
    resize.disconnect();
    resize.observe(list);
    for (const child of list.children) resize.observe(child);
  };
  const mutation = new MutationObserver(() => {
    observeTabs();
    sync();
  });

  observeTabs();
  sync();
  mutation.observe(list, { subtree: true, childList: true, attributeFilter: ["data-state", "aria-current"] });
  list.addEventListener("scroll", fade, { passive: true });
  return () => {
    cancelAnimationFrame(frame);
    // A re-attach (StrictMode's double ref call) places the underline afresh.
    delete list.dataset.indicator;
    resize.disconnect();
    mutation.disconnect();
    list.removeEventListener("scroll", fade);
  };
}

/** The sliding underline of an `underline` row, placed by `tabRowRef`. */
const tabIndicatorClass =
  "pointer-events-none absolute bottom-0 left-0 h-0.5 w-(--tab-w) translate-x-(--tab-x) bg-primary opacity-0 " +
  "group-data-[indicator]/tabs:opacity-100 group-data-[indicator=ready]/tabs:transition-[translate,width] " +
  "duration-200 ease-out motion-reduce:transition-none";

/**
 * Count after the label: a queue size, a result total. A plain number, part of
 * the label rather than a box beside it: dimmer than the label at rest, a step
 * brighter on the active tab.
 */
function TabBadge({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <span className="font-normal tabular-nums text-[color:var(--aqt-fg-dim)] group-data-[state=active]:text-[color:var(--aqt-fg-muted)] group-aria-[current=page]:text-[color:var(--aqt-fg-muted)]">
      {children}
    </span>
  );
}

/** Health marker before the label. `label` is required: never colour-only. */
function TabDot({ tone, label }: Readonly<{ tone: Tone; label: string }>) {
  return (
    <>
      <StatusDot tone={tone} />
      <span className="sr-only">{label}</span>
    </>
  );
}

const TabsVariantContext = React.createContext<TabsVariant>("underline");

const Tabs = TabsPrimitive.Root;

function TabsList({
  className,
  variant = "underline",
  children,
  ...props
}: Readonly<
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> & { variant?: TabsVariant }
>) {
  return (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.List
        ref={tabRowRef}
        data-ui="tabs-list"
        className={cn(tabsListVariants({ variant }), className)}
        {...props}
      >
        {children}
        {variant === "underline" ? <span aria-hidden className={tabIndicatorClass} /> : null}
      </TabsPrimitive.List>
    </TabsVariantContext.Provider>
  );
}

interface TabsTriggerProps extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> {
  /** Rendered whenever it is not `null`/`undefined` — pass `undefined` to hide a zero. */
  badge?: React.ReactNode;
  dot?: { tone: Tone; label: string };
}

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  TabsTriggerProps
>(({ className, badge, dot, children, ...props }, ref) => {
  const variant = React.useContext(TabsVariantContext);
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      data-ui="tabs-trigger"
      className={cn(tabsTriggerVariants({ variant }), className)}
      {...props}
    >
      {dot ? <TabDot {...dot} /> : null}
      {children}
      {badge != null ? <TabBadge>{badge}</TabBadge> : null}
    </TabsPrimitive.Trigger>
  );
});
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      // The gap under a horizontal list; a vertical (`rail`) list sits beside its panel.
      "mt-4 data-[orientation=vertical]:mt-0 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      className
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  TabBadge,
  TabDot,
  tabsListVariants,
  tabsTriggerVariants,
  tabIndicatorClass,
  tabRowRef
};
