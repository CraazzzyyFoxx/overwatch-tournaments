"use client";

import React from "react";
import { ChevronDown, FlaskConical } from "lucide-react";

import { TeamAnalytics } from "@/types/analytics.types";
import { Card } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import AnalyticsHorizon from "@/app/(site)/tournaments/analytics/components/AnalyticsHorizon";
import StandingsDistributionCard from "@/app/(site)/tournaments/analytics/components/StandingsDistributionCard";
import MatchQualityCard from "@/app/(site)/tournaments/analytics/components/MatchQualityCard";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface DeepDiveSectionProps {
  tournamentId: number;
  teams: TeamAnalytics[];
}

/**
 * The expert layer, collapsed by default: predicted-vs-actual horizon, the
 * Monte Carlo standings distribution and per-match quality / anomaly review.
 * Kept one click away so the read view stays a clean briefing.
 */
export default function DeepDiveSection({ tournamentId, teams }: DeepDiveSectionProps) {
  const [open, setOpen] = React.useState(false);

  return (
    <Card className="overflow-hidden border-border/60">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-white/[0.02]">
          <FlaskConical className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <span className="font-display text-[15px] font-bold uppercase tracking-[0.04em] text-foreground">
            Deep dive
          </span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            forecast horizon · standings odds · match quality
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
          <div className={styles.split}>
            <AnalyticsHorizon teams={teams} />
            <StandingsDistributionCard tournamentId={tournamentId} teams={teams} />
          </div>
          <MatchQualityCard tournamentId={tournamentId} />
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
