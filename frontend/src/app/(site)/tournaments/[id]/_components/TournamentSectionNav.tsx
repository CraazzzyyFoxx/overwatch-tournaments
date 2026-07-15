"use client";

import React, { useEffect, useMemo, useRef } from "react";
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
  getTournamentPhaseNoteKey,
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
  const railRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLElement>(null);
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
  const phaseNoteKey = getTournamentPhaseNoteKey(status, stages.length > 0);
  const setActiveRef = (node: HTMLElement | null) => {
    activeRef.current = node;
  };

  useEffect(() => {
    activeRef.current?.scrollIntoView({
      behavior: preferredScrollBehavior(),
      block: "nearest",
      inline: "center"
    });
  }, [pathname]);

  const scrollRail = (direction: -1 | 1) => {
    const rail = railRef.current;
    if (!rail) return;

    rail.scrollBy({
      left: direction * Math.max(180, rail.clientWidth * 0.65),
      behavior: preferredScrollBehavior()
    });
  };

  return (
    <div className={cn(styles.navRegion, className)}>
      <p id="tournament-phase-note" className={styles.phaseNote}>
        {t(phaseNoteKey)}
      </p>
      <nav
        className={styles.railFrame}
        aria-label={t("tournamentDetail.sectionsNav")}
        aria-describedby="tournament-phase-note"
      >
        <button
          type="button"
          className={styles.scrollControl}
          onClick={() => scrollRail(-1)}
          aria-label={t("tournamentDetail.nav.scrollPrevious")}
        >
          <ArrowLeft aria-hidden="true" />
        </button>

        <div className={styles.railViewport}>
          <span className={cn(styles.edgeFade, styles.edgeFadeStart)} aria-hidden="true" />
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
          <span className={cn(styles.edgeFade, styles.edgeFadeEnd)} aria-hidden="true" />
        </div>

        <button
          type="button"
          className={styles.scrollControl}
          onClick={() => scrollRail(1)}
          aria-label={t("tournamentDetail.nav.scrollNext")}
        >
          <ArrowRight aria-hidden="true" />
        </button>
      </nav>
    </div>
  );
}
