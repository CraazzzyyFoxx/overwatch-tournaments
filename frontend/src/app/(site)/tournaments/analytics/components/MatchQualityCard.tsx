"use client";

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import analyticsService from "@/services/analytics.service";
import encounterService from "@/services/encounter.service";
import { AnomalyKind, AnomalyVerdict, MatchQuality } from "@/types/analytics.types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useTranslation } from "@/i18n/LanguageContext";
import { cn } from "@/lib/utils";
import { isAnomalyGlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import AnomalyLegend from "@/app/(site)/tournaments/analytics/components/AnomalyLegend";

interface MatchQualityCardProps {
  tournamentId: number;
}

function FeedbackButtons({
  current,
  pending,
  onVerdict,
  confirmLabel,
  dismissLabel,
}: {
  current?: AnomalyVerdict;
  pending: boolean;
  onVerdict: (verdict: AnomalyVerdict) => void;
  confirmLabel: string;
  dismissLabel: string;
}) {
  return (
    <span className="inline-flex items-center gap-0.5">
      <button
        type="button"
        disabled={pending}
        onClick={() => onVerdict("confirmed")}
        title={confirmLabel}
        aria-label={confirmLabel}
        className={cn(
          "rounded p-0.5 transition-colors disabled:opacity-50",
          current === "confirmed"
            ? "text-emerald-400"
            : "text-muted-foreground hover:text-emerald-300",
        )}
      >
        <Check className="h-3 w-3" aria-hidden="true" />
      </button>
      <button
        type="button"
        disabled={pending}
        onClick={() => onVerdict("dismissed")}
        title={dismissLabel}
        aria-label={dismissLabel}
        className={cn(
          "rounded p-0.5 transition-colors disabled:opacity-50",
          current === "dismissed"
            ? "text-red-400"
            : "text-muted-foreground hover:text-red-300",
        )}
      >
        <X className="h-3 w-3" aria-hidden="true" />
      </button>
    </span>
  );
}

function scoreColor(score: number): string {
  if (score >= 75) return "bg-emerald-500/20 text-emerald-200";
  if (score >= 50) return "bg-amber-400/20 text-amber-100";
  return "bg-red-500/20 text-red-100";
}

function anomalyTone(kind: AnomalyKind): string {
  switch (kind) {
    case "smurf":
      return "border-amber-400/50 text-amber-200";
    case "troll":
      return "border-red-500/50 text-red-200";
    case "throw":
      return "border-purple-500/50 text-purple-200";
    case "sandbag":
      return "border-fuchsia-500/50 text-fuchsia-200";
    default:
      return "";
  }
}

/**
 * Match Quality view (Phase 4) — one row per encounter with the four
 * sub-scores plus anomaly flags. Lives on the analytics page as a collapsible
 * section; expand to reveal flag reasons inline.
 */
export default function MatchQualityCard({ tournamentId }: MatchQualityCardProps) {
  const { hasPermission } = usePermissions();
  const { t } = useTranslation();
  const canReview = hasPermission("analytics.update");
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics-match-quality", tournamentId],
    queryFn: () => analyticsService.getMatchQuality(tournamentId),
    staleTime: 60_000,
  });

  // Reviewer verdicts (only fetched for users who can act on them).
  const { data: feedback } = useQuery({
    queryKey: ["analytics-anomaly-feedback", tournamentId],
    queryFn: () => analyticsService.getAnomalyFeedback(tournamentId),
    enabled: canReview,
    staleTime: 60_000,
  });

  const verdictByKey = React.useMemo(
    () => new Map((feedback ?? []).map((f) => [`${f.player_id}-${f.kind}`, f.verdict])),
    [feedback],
  );

  const feedbackMutation = useMutation({
    mutationFn: (input: { playerId: number; kind: string; verdict: AnomalyVerdict }) =>
      analyticsService.submitAnomalyFeedback({
        tournament_id: tournamentId,
        player_id: input.playerId,
        kind: input.kind,
        verdict: input.verdict,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["analytics-anomaly-feedback", tournamentId],
      }),
  });

  // Encounter names so each row reads "Team A vs Team B" instead of a raw id.
  const { data: encounters } = useQuery({
    queryKey: ["encounters", "by-tournament", tournamentId],
    queryFn: () => encounterService.getAll(1, "", tournamentId, -1),
    staleTime: 60_000,
  });

  const encounterLabelById = React.useMemo(() => {
    const map = new Map<number, string>();
    (encounters?.results ?? []).forEach((encounter) => {
      const teams =
        encounter.home_team?.name && encounter.away_team?.name
          ? `${encounter.home_team.name} vs ${encounter.away_team.name}`
          : null;
      const label = encounter.name?.trim() || teams;
      if (label) map.set(encounter.id, label);
    });
    return map;
  }, [encounters]);

  const rows: MatchQuality[] = React.useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => a.encounter_id - b.encounter_id);
  }, [data]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base">{t("analytics.matchQuality.title")}</CardTitle>
          <AnomalyLegend className="shrink-0" />
        </div>
        <p className="text-xs text-muted-foreground">
          {t("analytics.matchQuality.subtitle")}
        </p>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        )}
        {isError && (
          <p className="text-sm text-muted-foreground">
            {t("analytics.matchQuality.unavailable")}
          </p>
        )}
        {rows.length === 0 && !isLoading && !isError && (
          <p className="text-sm text-muted-foreground">{t("analytics.matchQuality.noData")}</p>
        )}
        {rows.length > 0 && (
          <ul className="divide-y divide-border/60">
            {rows.map((row) => (
              <li key={row.encounter_id} className="py-2 grid grid-cols-12 gap-3 items-center text-sm">
                <span
                  className="col-span-2 truncate font-medium"
                  title={encounterLabelById.get(row.encounter_id)}
                >
                  {encounterLabelById.get(row.encounter_id) ??
                    t("analytics.matchQuality.encounter", { id: row.encounter_id })}
                </span>
                <span
                  className={cn(
                    "col-span-1 text-center rounded-md px-2 py-0.5 font-semibold",
                    scoreColor(row.quality_score),
                  )}
                  title={t("analytics.glossary.match_quality.plain")}
                >
                  {row.quality_score.toFixed(0)}
                </span>
                <span className="col-span-2 text-center text-xs text-muted-foreground">
                  {t("analytics.matchQuality.comp")} <strong>{row.competitiveness.toFixed(0)}</strong>
                </span>
                <span className="col-span-2 text-center text-xs text-muted-foreground">
                  {t("analytics.matchQuality.pred")} <strong>{row.predictability.toFixed(0)}</strong>
                </span>
                <span className="col-span-2 text-center text-xs text-muted-foreground">
                  {t("analytics.matchQuality.skill")} <strong>{row.skill_balance.toFixed(0)}</strong>
                </span>
                <span className="col-span-3 flex gap-1.5 flex-wrap justify-end items-center">
                  {(row.anomaly_flags ?? []).map((flag, i) => (
                    <span
                      key={`${flag.player_id}-${flag.kind}-${i}`}
                      className="inline-flex items-center gap-1"
                    >
                      <Badge
                        variant="outline"
                        className={cn("text-[10px] uppercase", anomalyTone(flag.kind))}
                        title={[
                          isAnomalyGlossaryTerm(flag.kind)
                            ? `${t(`analytics.glossary.${flag.kind}.label`)} — ${t(`analytics.glossary.${flag.kind}.plain`)}`
                            : null,
                          ...flag.reasons,
                        ]
                          .filter(Boolean)
                          .join("\n")}
                      >
                        {flag.kind} · #{flag.player_id}
                      </Badge>
                      {canReview ? (
                        <FeedbackButtons
                          current={verdictByKey.get(`${flag.player_id}-${flag.kind}`)}
                          pending={feedbackMutation.isPending}
                          confirmLabel={t("analytics.matchQuality.confirm")}
                          dismissLabel={t("analytics.matchQuality.dismiss")}
                          onVerdict={(verdict) =>
                            feedbackMutation.mutate({
                              playerId: flag.player_id,
                              kind: flag.kind,
                              verdict,
                            })
                          }
                        />
                      ) : null}
                    </span>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
