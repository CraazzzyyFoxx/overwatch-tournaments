"use client";

import React from "react";

import { AlgorithmAnalytics, TournamentAnalyticsSummary } from "@/types/analytics.types";
import type { Tournament } from "@/types/tournament.types";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { buildVerdictClauses } from "@/app/(site)/tournaments/analytics/analytics.helpers";

interface AnalyticsBriefingProps {
  tournaments: Tournament[];
  algorithms: AlgorithmAnalytics[];
  tournamentId: number | null;
  algorithmId: number | null;
  activeTournament: Tournament | null;
  activeAlgorithm: AlgorithmAnalytics | null;
  summary?: TournamentAnalyticsSummary;
  predictedMoves: number;
  loadingTournaments: boolean;
  loadingAlgorithms: boolean;
  isErrorTournaments: boolean;
  isErrorAlgorithms: boolean;
  onTournamentChange: (value: string) => void;
  onAlgorithmChange: (value: string) => void;
}

/**
 * Briefing header: instead of a wall of equal KPI cards, it leads with one
 * plain-language verdict sentence built from the summary, then the
 * tournament / algorithm pickers. Admin actions live in OrganizerTools, not
 * here, so the default read view stays clean.
 */
export default function AnalyticsBriefing({
  tournaments,
  algorithms,
  tournamentId,
  algorithmId,
  activeTournament,
  activeAlgorithm,
  summary,
  predictedMoves,
  loadingTournaments,
  loadingAlgorithms,
  isErrorTournaments,
  isErrorAlgorithms,
  onTournamentChange,
  onAlgorithmChange,
}: AnalyticsBriefingProps) {
  const verdict = summary ? buildVerdictClauses(summary, predictedMoves) : null;

  return (
    <Card className="overflow-hidden border-border/60">
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.85fr)]">
        {/* Verdict — the one-glance answer */}
        <div className="min-w-0">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">
            Tournament analytics
            {activeAlgorithm ? (
              <span className="text-muted-foreground/40"> · ranked by {activeAlgorithm.name}</span>
            ) : null}
          </p>
          <h1 className="font-display text-2xl font-bold uppercase tracking-wide text-foreground md:text-3xl">
            {activeTournament?.name ?? "Tournament analytics"}
          </h1>

          {verdict ? (
            <div className="mt-3 max-w-xl">
              <p className="text-base font-semibold text-foreground">{verdict.headline}</p>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {verdict.clauses.map((clause, index) => (
                  <React.Fragment key={index}>
                    {index > 0 ? <span className="text-muted-foreground/40"> · </span> : null}
                    <span
                      className={
                        clause.includes("flag") ? "text-amber-300" : undefined
                      }
                    >
                      {clause}
                    </span>
                  </React.Fragment>
                ))}
              </p>
            </div>
          ) : (
            <p className="mt-3 max-w-xl text-sm text-muted-foreground">
              Pick a tournament and an algorithm to see the briefing.
            </p>
          )}
        </div>

        {/* Pickers */}
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/50">
              Tournament
            </div>
            <Select
              value={tournamentId == null ? "" : tournamentId.toString()}
              onValueChange={onTournamentChange}
              disabled={loadingTournaments || isErrorTournaments}
            >
              <SelectTrigger aria-label="Tournament" className="h-11">
                <SelectValue
                  placeholder={
                    loadingTournaments
                      ? "Loading tournaments..."
                      : isErrorTournaments
                        ? "Failed to load tournaments"
                        : "Select a tournament"
                  }
                />
              </SelectTrigger>
              <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
                <SelectGroup>
                  {tournaments.map((item) => (
                    <SelectItem key={item.id} value={item.id.toString()}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/50">
              Algorithm
            </div>
            <Select
              value={algorithmId == null ? "" : algorithmId.toString()}
              onValueChange={onAlgorithmChange}
              disabled={loadingAlgorithms || isErrorAlgorithms}
            >
              <SelectTrigger aria-label="Algorithm" className="h-11">
                <SelectValue
                  placeholder={
                    loadingAlgorithms
                      ? "Loading algorithms..."
                      : isErrorAlgorithms
                        ? "Failed to load algorithms"
                        : "Select an algorithm"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {algorithms.map((item) => (
                    <SelectItem key={item.id} value={item.id.toString()}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </Card>
  );
}
