"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva } from "class-variance-authority";

import { StatusDot } from "@/components/ui/status-dot";
import { segmentedFrame, toggleVariants } from "@/components/ui/toggle";
import type { Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

type TabsVariant = "underline" | "pill";

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
 * panels; a plain view/mode switch without panels is a `ToggleGroup`.
 */
const tabsListVariants = cva("", {
  variants: {
    variant: {
      // The baseline is an inset shadow, not a border: it paints under the
      // triggers, so the active trigger's 2px border covers it the way a tab
      // sits on its rule, without a wrapper around the scroll container.
      underline:
        "relative flex w-full items-center gap-1 overflow-x-auto whitespace-nowrap shadow-[inset_0_-1px_0_hsl(var(--border))]",
      pill: cn(segmentedFrame, "relative max-w-full overflow-x-auto")
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
          "inline-flex h-9 items-center gap-1.5 border-b-2 border-transparent px-3 text-sm text-muted-foreground transition-colors hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          "data-[state=active]:border-primary data-[state=active]:font-medium data-[state=active]:text-foreground",
          "aria-[current=page]:border-primary aria-[current=page]:font-medium aria-[current=page]:text-foreground"
        ),
        pill: toggleVariants({ variant: "pill", size: "sm" })
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

/** Count after the label: a queue size, a result total. */
function TabBadge({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <span
      className={cn(
        "rounded-full bg-muted/40 px-1.5 py-0.5 text-label font-normal tabular-nums text-muted-foreground",
        "group-data-[state=active]:bg-primary/15 group-data-[state=active]:text-primary",
        "group-aria-[current=page]:bg-primary/15 group-aria-[current=page]:text-primary"
      )}
    >
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
  ...props
}: Readonly<React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> & { variant?: TabsVariant }>) {
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

const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, TabsTriggerProps>(
  ({ className, badge, dot, children, ...props }, ref) => {
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
  }
);
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
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
