"use client";

import React from "react";
import { ChevronDown, FlaskConical } from "lucide-react";

import { PerformanceV2, StandingsDistribution, TeamAnalytics } from "@/types/analytics.types";
import { Card } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import AttentionTriage from "@/app/(site)/tournaments/analytics/components/AttentionTriage";
import AnalyticsStandings from "@/app/(site)/tournaments/analytics/components/AnalyticsStandings";
import StandingsDistributionCard from "@/app/(site)/tournaments/analytics/components/StandingsDistributionCard";
import MatchQualityCard from "@/app/(site)/tournaments/analytics/components/MatchQualityCard";

interface ExpertLayerProps {
  tournamentId: number;
  teams: TeamAnalytics[];
  performanceByPlayer: Map<number, PerformanceV2>;
  distributionByTeam?: Map<number, StandingsDistribution>;
}

/**
 * The organizer/expert surface, gated to `analytics.read` viewers by the caller.
 * Collapsed by default so the community read stays clean: needs-attention
 * triage, the dense per-player standings table, the Monte-Carlo standings
 * distribution and per-match quality / anomaly review.
 */
export default function ExpertLayer({
  tournamentId,
  teams,
  performanceByPlayer,
  distributionByTeam,
}: ExpertLayerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);

  return (
    <Card className="overflow-hidden border-border/60">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-white/[0.02]">
          <FlaskConical className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <span className="font-display text-[15px] font-bold uppercase tracking-[0.04em] text-foreground">
            {t("analytics.deepDive.title")}
          </span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {t("analytics.deepDive.subtitle")}
          </span>
          <ChevronDown
            className={cn(
              "ml-auto h-4 w-4 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
            aria-hidden="true"
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-4 border-t border-border/60 p-4">
          <AttentionTriage teams={teams} />
          <AnalyticsStandings
            teams={teams}
            performanceByPlayer={performanceByPlayer}
            distributionByTeam={distributionByTeam}
          />
          <StandingsDistributionCard tournamentId={tournamentId} teams={teams} />
          <MatchQualityCard tournamentId={tournamentId} />
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
