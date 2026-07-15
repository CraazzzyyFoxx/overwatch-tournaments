"use client";

import React from "react";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import {
  BarChart3,
  Calendar,
  ClipboardList,
  LayoutGrid,
  ListOrdered,
  Trophy,
  Users,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { Stage, TournamentStatus } from "@/types/tournament.types";

import { useTranslations } from "next-intl";

const baseItems = [
  { title: "Teams", icon: Users, tab: "teams" },
  { title: "Participants", icon: ClipboardList, tab: "participants" },
  { title: "Matches", icon: Calendar, tab: "matches" },
  { title: "Heroes", icon: Trophy, tab: "heroes" },
  { title: "Standings", icon: BarChart3, tab: "standings" },
  { title: "Draft", icon: ListOrdered, tab: "draft" },
] as const;

const phaseLockedTabs = new Set<(typeof baseItems)[number]["tab"]>([
  "teams",
  "matches",
  "heroes",
  "standings",
]);
const unlockedStatuses = new Set<TournamentStatus>([
  "live",
  "playoffs",
  "completed",
]);

type TabId = (typeof baseItems)[number]["tab"] | "bracket";

function normalizeSegment(segment: string | null): TabId {
  if (segment === "bracket") return "bracket";
  if (baseItems.some((item) => item.tab === segment)) return segment as TabId;
  return "teams";
}

function resolveBracketHref(tournamentId: string, stages: Stage[]): string {
  const active = stages.find((stage) => stage.is_active);
  const elimination = stages.find(
    (stage) =>
      stage.stage_type === "single_elimination" ||
      stage.stage_type === "double_elimination"
  );
  const group = stages.find(
    (stage) => stage.stage_type === "round_robin" || stage.stage_type === "swiss"
  );
  const primary = active ?? elimination ?? group ?? stages[0];
  return primary
    ? `/tournaments/${tournamentId}/bracket?stage=${primary.id}`
    : `/tournaments/${tournamentId}/bracket`;
}

type TournamentSectionNavProps = {
  tournamentId: string;
  status: TournamentStatus;
  stages?: Stage[];
  teamFormation?: string;
  // Retained for call-site compatibility; both variants render the tab bar.
  variant?: "desktop" | "mobile";
  className?: string;
};

export default function TournamentSectionNav({
  tournamentId,
  status,
  stages = [],
  teamFormation,
  className,
}: TournamentSectionNavProps) {
  const t = useTranslations();
  const segment = useSelectedLayoutSegment();
  const activeTab = normalizeSegment(segment);
  const competitionEnabled = unlockedStatuses.has(status);
  const isLive = status === "live" || status === "playoffs";
  const bracketHref = resolveBracketHref(tournamentId, stages);

  return (
    <nav className={cn("tabs", className)} aria-label={t("tournamentDetail.sectionsNav")}>
      {!competitionEnabled ? (
        <span className="tab disabled" aria-disabled="true">
          <LayoutGrid className="h-3.5 w-3.5" />
          {t("common.bracket")}
        </span>
      ) : (
        <Link
          href={bracketHref}
          className={cn("tab", activeTab === "bracket" && "active")}
          aria-current={activeTab === "bracket" ? "page" : undefined}
        >
          <LayoutGrid className="h-3.5 w-3.5" />
          {t("common.bracket")}
          {isLive && <span className="live-tag" />}
        </Link>
      )}

      {baseItems.map((item) => {
        if (item.tab === "draft" && teamFormation !== "draft") {
          return null;
        }

        const Icon = item.icon;
        const isActive = item.tab === activeTab;
        const disabled = phaseLockedTabs.has(item.tab) && !competitionEnabled;
        const content = (
          <>
            <Icon className="h-3.5 w-3.5" />
            {t(`common.${item.tab}`)}
          </>
        );

        if (disabled) {
          return (
            <span key={item.tab} className="tab disabled" aria-disabled="true">
              {content}
            </span>
          );
        }

        return (
          <Link
            key={item.tab}
            href={item.tab === "draft" ? `/draft/${tournamentId}` : `/tournaments/${tournamentId}/${item.tab}`}
            className={cn("tab", isActive && "active")}
            aria-current={isActive ? "page" : undefined}
          >
            {content}
          </Link>
        );
      })}
    </nav>
  );
}
