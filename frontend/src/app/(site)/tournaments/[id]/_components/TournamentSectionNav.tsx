"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Calendar,
  ClipboardList,
  LayoutGrid,
  ListOrdered,
  Trophy,
  Users
} from "lucide-react";
import { useTranslations } from "next-intl";

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
  bracket: LayoutGrid,
  teams: Users,
  participants: ClipboardList,
  matches: Calendar,
  heroes: Trophy,
  standings: BarChart3,
  draft: ListOrdered
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
  teamFormation?: string;
  // Retained for call-site compatibility; both variants render the same adaptive rail.
  variant?: "desktop" | "mobile";
  className?: string;
};

export default function TournamentSectionNav({
  tournamentId,
  status,
  stages = [],
  teamFormation,
  className
}: TournamentSectionNavProps) {
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
        teamFormation,
        pathname
      }),
    [pathname, stages, status, teamFormation, tournamentId]
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
    <div className={cn(styles.navRegion, className)}>
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
                const content = (
                  <>
                    <Icon className={styles.itemIcon} aria-hidden="true" />
                    <span>{t(item.labelKey)}</span>
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
                          title={reason}
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
                  <Link
                    key={item.id}
                    ref={item.active ? setActiveRef : undefined}
                    href={item.href}
                    className={cn(styles.navItem, item.active && styles.active)}
                    aria-current={item.active ? "page" : undefined}
                  >
                    {content}
                  </Link>
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
    </div>
  );
}
