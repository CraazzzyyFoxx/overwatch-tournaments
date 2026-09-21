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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

import styles from "../TournamentDetail.module.css";
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

function preferredScrollBehavior(): ScrollBehavior {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

type TournamentSectionNavProps = {
  tournamentId: string;
  status: TournamentStatus;
  stages?: StageSummary[];
  hasTeams?: boolean;
  hasStreams?: boolean;
  hasRules?: boolean;
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
  const items = useMemo(
    () =>
      buildTournamentSectionNav({
        tournamentId,
        status,
        stages,
        hasTeams,
        hasStreams,
        hasRules,
        pathname
      }),
    [hasRules, hasTeams, hasStreams, pathname, stages, status, tournamentId]
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
      behavior: preferredScrollBehavior(),
      block: "nearest",
      inline: "center"
    });
    refreshRailRef.current();
  }, [items, pathname]);

  const scrollRail = (direction: -1 | 1) => {
    const rail = railRef.current;
    if (!rail) return;

    scrollTournamentRail(rail, direction, preferredScrollBehavior());
  };

  return (
    <div className={cn(styles.navRegion, className)} data-collapsed={collapsed || undefined}>
      <div className={styles.railRow}>
      {collapsed && collapsedTitle ? (
        <div className={styles.railLead}>{collapsedTitle}</div>
      ) : null}
      <nav
        ref={frameRef}
        className={cn(styles.railFrame, railState.hasOverflow && styles.railFrameWithControls)}
        aria-label={t("tournamentDetail.sectionsNav")}
      >
        <button
          type="button"
          className={cn(
            styles.scrollControl,
            styles.scrollPrevious,
            !railState.hasOverflow && styles.scrollControlHidden
          )}
          onClick={() => scrollRail(-1)}
          aria-label={t("tournamentDetail.nav.scrollPrevious")}
          aria-hidden={!railState.hasOverflow || undefined}
          disabled={!railState.hasOverflow || !railState.canScrollPrevious}
        >
          <ArrowLeft aria-hidden="true" />
        </button>

        <div className={styles.railViewport}>
          {railState.canScrollPrevious ? (
            <span className={cn(styles.edgeFade, styles.edgeFadeStart)} aria-hidden="true" />
          ) : null}
          <TooltipProvider delayDuration={180}>
            <div ref={railRef} className={styles.rail}>
              {items.map((item) => {
                const Icon = icons[item.id];
                const label = t(item.labelKey);
                const content = (
                  <>
                    <Icon className={styles.itemIcon} aria-hidden="true" />
                    <span className={styles.itemLabel}>{label}</span>
                    {item.id === "bracket" && (status === "live" || status === "playoffs") ? (
                      <span className={styles.liveTag} aria-hidden="true" />
                    ) : null}
                  </>
                );

                if (!item.available && item.reasonKey) {
                  const reason = t(item.reasonKey);
                  return (
                    <Tooltip key={item.id}>
                      <TooltipTrigger asChild>
                        <button
                          ref={item.active ? setActiveRef : undefined}
                          type="button"
                          className={cn(
                            styles.navItem,
                            styles.locked,
                            item.active && styles.active
                          )}
                          aria-current={item.active ? "page" : undefined}
                          aria-disabled={!item.available || undefined}
                          title={collapsed ? `${label} — ${reason}` : reason}
                          onClick={(event) => event.preventDefault()}
                        >
                          {content}
                          <span className="sr-only"> — {reason}</span>
                        </button>
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
                    className={cn(styles.navItem, item.active && styles.active)}
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
            <span className={cn(styles.edgeFade, styles.edgeFadeEnd)} aria-hidden="true" />
          ) : null}
        </div>

        <button
          type="button"
          className={cn(
            styles.scrollControl,
            styles.scrollNext,
            !railState.hasOverflow && styles.scrollControlHidden
          )}
          onClick={() => scrollRail(1)}
          aria-label={t("tournamentDetail.nav.scrollNext")}
          aria-hidden={!railState.hasOverflow || undefined}
          disabled={!railState.hasOverflow || !railState.canScrollNext}
        >
          <ArrowRight aria-hidden="true" />
        </button>
      </nav>
      {collapsed && collapsedActions ? (
        <div className={styles.railTrail}>{collapsedActions}</div>
      ) : null}
      </div>
    </div>
  );
}
