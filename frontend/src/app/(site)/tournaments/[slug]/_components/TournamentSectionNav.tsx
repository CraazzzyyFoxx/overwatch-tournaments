"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Calendar,
  ClipboardList,
  LayoutDashboard,
  LayoutGrid,
  Map as MapIcon,
  Radio,
  Scale,
  Users
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";
import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

import {
  buildTournamentSectionNav,
  observeTournamentRail,
  scrollTournamentRail,
  type TournamentRailScrollState,
  type TournamentSectionId
} from "./tournament-section-nav";

const icons: Record<TournamentSectionId, React.ComponentType<{ className?: string }>> = {
  overview: LayoutDashboard,
  bracket: LayoutGrid,
  teams: Users,
  matches: Calendar,
  maps: MapIcon,
  stats: BarChart3,
  stream: Radio,
  rules: Scale,
  participants: ClipboardList
};

const initialRailState: TournamentRailScrollState = {
  hasOverflow: false,
  canScrollPrevious: false,
  canScrollNext: false
};

/**
 * One rail tab, a link or a locked button alike. On a locked `Button` these
 * win over the primitive's box through `cn`: the rail, not the button, sets
 * the tab's geometry (44px row, 2px bottom bar sitting on the rail's rule).
 */
const NAV_ITEM =
  "relative inline-flex min-h-11 flex-none items-center gap-2 rounded-none border-0 border-b-2 border-transparent bg-transparent px-3.25 py-2.5 -mb-px text-caption font-medium leading-none whitespace-nowrap no-underline cursor-pointer transition-colors duration-150 motion-reduce:transition-none max-sm:px-2.75 hover:bg-[color:var(--aqt-overlay-2)] focus-visible:bg-[color:var(--aqt-overlay-2)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-0 [&_svg]:size-3.5";

/** The rail's text fade, standing in for the clipped tabs on the side that can still scroll. */
const EDGE_FADE = "pointer-events-none absolute inset-y-0 z-2 w-6 to-transparent";

type TournamentSectionNavProps = {
  tournamentId: string;
  status: TournamentStatus;
  stages?: StageSummary[];
  hasTeams?: boolean;
  hasStreams?: boolean;
  hasRules?: boolean;
  hasMapPool?: boolean;
  /**
   * Rendered in the rail's leading slot only while the page's big title is out
   * of view, so the viewer never loses the tournament's name without the rail
   * growing a second header of its own.
   */
  collapsedTitle?: React.ReactNode;
  /** Rendered in the trailing slot under the same condition. */
  collapsedActions?: React.ReactNode;
  /** Whether the big title is currently scrolled out of view. */
  collapsed?: boolean;
  className?: string;
};

export default function TournamentSectionNav({
  tournamentId,
  status,
  stages = [],
  hasTeams,
  hasStreams,
  hasRules,
  hasMapPool,
  collapsedTitle,
  collapsedActions,
  collapsed = false,
  className
}: Readonly<TournamentSectionNavProps>) {
  const t = useTranslations();
  const pathname = usePathname();
  const frameRef = useRef<HTMLElement>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLElement>(null);
  const refreshRailRef = useRef<() => void>(() => undefined);
  const [railState, setRailState] = useState(initialRailState);
  const scrollBehavior = usePrefersReducedMotion() ? "auto" : "smooth";
  const items = useMemo(
    () =>
      buildTournamentSectionNav({
        tournamentId,
        status,
        stages,
        hasTeams,
        hasStreams,
        hasRules,
        hasMapPool,
        pathname
      }),
    [hasMapPool, hasRules, hasTeams, hasStreams, pathname, stages, status, tournamentId]
  );
  const setActiveRef = (node: HTMLElement | null) => {
    activeRef.current = node;
  };

  useEffect(() => {
    const frame = frameRef.current;
    const rail = railRef.current;
    if (!frame || !rail) return;

    const observer = observeTournamentRail(rail, setRailState, {
      measurementContainer: frame
    });
    refreshRailRef.current = observer.refresh;

    return () => {
      refreshRailRef.current = () => undefined;
      observer.cleanup();
    };
  }, []);

  useEffect(() => {
    activeRef.current?.scrollIntoView({
      behavior: scrollBehavior,
      block: "nearest",
      inline: "center"
    });
    refreshRailRef.current();
  }, [items, pathname, scrollBehavior]);

  const scrollRail = (direction: -1 | 1) => {
    const rail = railRef.current;
    if (!rail) return;

    scrollTournamentRail(rail, direction, scrollBehavior);
  };

  return (
    <div
      className={cn(
        "sticky top-14 z-40 min-w-0 max-w-full bg-[linear-gradient(180deg,var(--aqt-bg)_78%,transparent)] pt-2",
        className
      )}
      data-collapsed={collapsed || undefined}
    >
      {/* One row: an optional collapsed-title lead, the scrolling rail, an
          optional trailing action slot. The slots mount only while the page's
          big title is out of view, so the rail never doubles as a second
          header; below `md` they stay hidden. */}
      <div className="flex min-w-0 items-stretch border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]/96">
      {collapsed && collapsedTitle ? (
        // Grows into whatever the rail leaves: the rail scrolls under its own
        // arrows when it runs out of room, the title has no such escape.
        <div className="me-2 hidden min-w-0 max-w-[clamp(12rem,30vw,34rem)] flex-[0_1_max-content] items-center gap-2 truncate border-e border-[color:var(--aqt-border)] ps-1 pe-3 text-body font-semibold text-[color:var(--aqt-fg)] md:flex">
          {collapsedTitle}
        </div>
      ) : null}
      <nav
        ref={frameRef}
        // `flex-auto`, not a 100% basis: a full-width basis made the tab strip
        // claim the whole row and squeeze the title to an ellipsis. It still
        // grows into whatever the title and actions leave.
        className={cn(
          "grid min-w-0 max-w-full flex-auto items-stretch",
          railState.hasOverflow ? "grid-cols-[2rem_minmax(0,1fr)_2rem]" : "grid-cols-[0_minmax(0,1fr)_0]"
        )}
        aria-label={t("tournamentDetail.sectionsNav")}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className={cn("col-start-1 place-self-center", !railState.hasOverflow && "hidden")}
          onClick={() => scrollRail(-1)}
          aria-label={t("tournamentDetail.nav.scrollPrevious")}
          aria-hidden={!railState.hasOverflow || undefined}
          disabled={!railState.hasOverflow || !railState.canScrollPrevious}
        >
          <ArrowLeft aria-hidden="true" />
        </Button>

        <div className="relative col-start-2 min-w-0 max-w-full overflow-hidden">
          {railState.canScrollPrevious ? (
            <span
              className={cn(EDGE_FADE, "left-0 bg-linear-to-r from-[color:var(--aqt-bg)]")}
              aria-hidden="true"
            />
          ) : null}
          <TooltipProvider>
            <div
              ref={railRef}
              className="flex w-full max-w-full scroll-px-5 gap-1 overflow-x-auto overflow-y-hidden overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {items.map((item) => {
                const Icon = icons[item.id];
                const label = t(item.labelKey);
                // Collapsed (from `md`): the row also carries the title and the
                // actions, so the inactive tabs keep their icons and give up
                // their labels; the active one stays spelled out, because an
                // icon alone cannot say where you are. Driven by `collapsed`,
                // not by overflow: condensing on overflow removes the overflow,
                // which restores the labels — a measurement loop. Visually
                // hidden rather than removed, so the accessible name survives;
                // the `title` added in this state covers the sighted reader.
                const condensed = collapsed && !item.active;
                const itemClass = cn(NAV_ITEM, condensed && "md:px-2.5");
                const content = (
                  <>
                    <Icon className="shrink-0" aria-hidden="true" />
                    <span className={cn(condensed && "md:sr-only")}>{label}</span>
                    {item.id === "bracket" && (status === "live" || status === "playoffs") ? (
                      <StatusDot pulse className="text-[color:var(--aqt-status-live)]" />
                    ) : null}
                  </>
                );

                if (!item.available && item.reasonKey) {
                  const reason = t(item.reasonKey);
                  // Locked reads as unavailable at a glance, not as a shade of
                  // the grey the open tabs use; it keeps the active bar.
                  return (
                    <Tooltip key={item.id}>
                      <TooltipTrigger asChild>
                        <Button
                          ref={item.active ? setActiveRef : undefined}
                          type="button"
                          variant="ghost"
                          className={cn(
                            itemClass,
                            "cursor-not-allowed text-[color:var(--aqt-fg-faint)] opacity-50 hover:text-[color:var(--aqt-fg-muted)] focus-visible:text-[color:var(--aqt-fg-muted)]",
                            item.active && "border-b-[color:var(--aqt-teal)]"
                          )}
                          aria-current={item.active ? "page" : undefined}
                          aria-disabled={!item.available || undefined}
                          title={collapsed ? `${label} — ${reason}` : reason}
                          onClick={(event) => event.preventDefault()}
                        >
                          {content}
                          <span className="sr-only"> — {reason}</span>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="bottom">{reason}</TooltipContent>
                    </Tooltip>
                  );
                }

                return (
                  <HoverPrefetchLink
                    key={item.id}
                    ref={item.active ? setActiveRef : undefined}
                    href={item.href}
                    className={cn(
                      itemClass,
                      item.active
                        ? "border-b-[color:var(--aqt-teal)] text-[color:var(--aqt-teal)]"
                        : "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)] focus-visible:text-[color:var(--aqt-fg)]"
                    )}
                    title={collapsed && !item.active ? label : undefined}
                    aria-current={item.active ? "page" : undefined}
                  >
                    {content}
                  </HoverPrefetchLink>
                );
              })}
            </div>
          </TooltipProvider>
          {railState.canScrollNext ? (
            <span
              className={cn(EDGE_FADE, "right-0 bg-linear-to-l from-[color:var(--aqt-bg)]")}
              aria-hidden="true"
            />
          ) : null}
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className={cn("col-start-3 place-self-center", !railState.hasOverflow && "hidden")}
          onClick={() => scrollRail(1)}
          aria-label={t("tournamentDetail.nav.scrollNext")}
          aria-hidden={!railState.hasOverflow || undefined}
          disabled={!railState.hasOverflow || !railState.canScrollNext}
        >
          <ArrowRight aria-hidden="true" />
        </Button>
      </nav>
      {collapsed && collapsedActions ? (
        <div className="hidden min-w-0 flex-none items-center gap-1.5 ps-3 md:flex">
          {collapsedActions}
        </div>
      ) : null}
      </div>
    </div>
  );
}
