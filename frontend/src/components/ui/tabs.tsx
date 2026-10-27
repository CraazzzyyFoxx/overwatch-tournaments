"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva } from "class-variance-authority";

import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/ui/status-dot";
import { segmentedFrame, toggleVariants } from "@/components/ui/toggle";
import type { Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

type TabsVariant = "underline" | "pill" | "rail";

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
      // triggers, so the active trigger's 2px border covers it the way a tab
      // sits on its rule, without a wrapper around the scroll container.
      underline:
        "relative flex w-full items-center gap-1 overflow-x-auto whitespace-nowrap shadow-[inset_0_-1px_0_hsl(var(--border))]",
      pill: cn(segmentedFrame, "relative max-w-full overflow-x-auto"),
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
          "aria-[current=page]:border-primary aria-[current=page]:text-foreground"
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

/**
 * Keeps the active tab visible in a horizontally scrolling row. Horizontal
 * only: `scrollIntoView` would also scroll the page to a row below the fold.
 */
function revealTab(list: HTMLElement, tab: HTMLElement) {
  const start = tab.offsetLeft;
  const end = start + tab.offsetWidth;
  if (start < list.scrollLeft) list.scrollLeft = start;
  else if (end > list.scrollLeft + list.clientWidth) list.scrollLeft = end - list.clientWidth;
}

/**
 * Count after the label: a queue size, a result total. The neutral tint at
 * rest; on the active tab the same tint over the accent (`TONE_HUE.accent`).
 */
function TabBadge({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <Badge
      tone="neutral"
      shape="pill"
      size="sm"
      className="py-0.5 font-normal tabular-nums group-data-[state=active]:[--tone-hue:var(--aqt-teal)] group-aria-[current=page]:[--tone-hue:var(--aqt-teal)]"
    >
      {children}
    </Badge>
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
  ...props
}: Readonly<
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> & { variant?: TabsVariant }
>) {
  const listRef = React.useRef<HTMLDivElement>(null);

  // A deep link (or a URL-driven change) can activate a tab that is scrolled
  // out of a narrow row; follow the active trigger whenever it changes.
  React.useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const reveal = () => {
      const active = list.querySelector<HTMLElement>('[role="tab"][data-state="active"]');
      if (active) revealTab(list, active);
    };
    reveal();
    const observer = new MutationObserver(reveal);
    observer.observe(list, { subtree: true, attributeFilter: ["data-state"] });
    return () => observer.disconnect();
  }, []);

  return (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.List
        ref={listRef}
        data-ui="tabs-list"
        className={cn(tabsListVariants({ variant }), className)}
        {...props}
      />
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
  revealTab
};
