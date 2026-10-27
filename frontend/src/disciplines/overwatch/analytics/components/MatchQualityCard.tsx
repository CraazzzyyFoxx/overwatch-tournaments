"use client";

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useFormatter } from "@/lib/datetime/client";
import analyticsService from "@/services/analytics.service";
import encounterService from "@/services/encounter.service";
import { AnomalyVerdict, MatchQuality } from "@/types/analytics.types";
import type { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";
import AnomalyFlag from "@/disciplines/overwatch/analytics/components/AnomalyFlag";
import InfoDot from "@/disciplines/overwatch/analytics/components/InfoDot";
import { analyticsQueryKeys } from "@/lib/analytics/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { duelSeats } from "@/lib/encounter/seats";
import { splitHandle } from "@/lib/player";

interface MatchQualityCardProps {
  tournamentId: number;
  /** Opens the match-quality glossary entry (the tap path for the explainer). */
  onExplain?: (term: GlossaryTerm) => void;
  /** The bracket's players by id, so a flag (and its review) says whose it is. */
  playerNames?: ReadonlyMap<number, string>;
}

/** Quality ramp of a 0–100 score: ≥75 good, ≥50 middling, below that poor. */
function qualityTone(score: number): string {
  if (score >= 75) return "var(--aqt-up)";
  if (score >= 50) return "var(--aqt-amber)";
  return "var(--aqt-rose)";
}

function FeedbackButtons({
  current,
  pending,
  onVerdict,
}: Readonly<{
  current?: AnomalyVerdict;
  pending: boolean;
  onVerdict: (verdict: AnomalyVerdict) => void;
}>) {
  const t = useTranslations();
  const confirmLabel = t("analytics.matchQuality.confirm");
  const dismissLabel = t("analytics.matchQuality.dismiss");

  return (
    <span className="inline-flex items-center">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        disabled={pending}
        aria-pressed={current === "confirmed"}
        aria-label={confirmLabel}
        title={confirmLabel}
        onClick={() => onVerdict("confirmed")}
      >
        <Check
          aria-hidden
          className={current === "confirmed" ? "text-[color:var(--aqt-up)]" : undefined}
        />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        disabled={pending}
        aria-pressed={current === "dismissed"}
        aria-label={dismissLabel}
        title={dismissLabel}
        onClick={() => onVerdict("dismissed")}
      >
        <X
          aria-hidden
          className={current === "dismissed" ? "text-[color:var(--aqt-rose)]" : undefined}
        />
      </Button>
    </span>
  );
}

/**
 * Match Quality view — one row per encounter: its quality score, the three
 * sub-scores and the anomaly flags (organizers confirm or dismiss each flag).
 */
export default function MatchQualityCard({ tournamentId, onExplain, playerNames }: Readonly<MatchQualityCardProps>) {
  const { hasPermission } = usePermissions();
  const t = useTranslations();
  const format = useFormatter();
  const canReview = hasPermission("analytics.update");
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: analyticsQueryKeys.matchQuality(tournamentId),
    queryFn: () => analyticsService.getMatchQuality(tournamentId),
    staleTime: 60_000,
  });

  // Reviewer verdicts (only fetched for users who can act on them).
  const { data: feedback } = useQuery({
    queryKey: analyticsQueryKeys.anomalyFeedback(tournamentId),
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
        queryKey: analyticsQueryKeys.anomalyFeedback(tournamentId),
      }),
  });

  // Encounters so each row names its two teams instead of a raw id.
  const { data: encounters } = useQuery({
    queryKey: encounterQueryKeys.byTournament(tournamentId),
    queryFn: () => encounterService.getAll(1, "", tournamentId, -1),
    staleTime: 60_000,
  });

  const encounterById = React.useMemo(
    () => new Map((encounters?.results ?? []).map((encounter) => [encounter.id, encounter])),
    [encounters],
  );

  const rows: MatchQuality[] = React.useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => a.encounter_id - b.encounter_id);
  }, [data]);

  const title = t("analytics.matchQuality.title");
  const whole = (value: number) => format.number(value, { maximumFractionDigits: 0 });

  if (isError) {
    return (
      <PageStateCard
        state="error"
        title={title}
        description={t("analytics.matchQuality.unavailable")}
        onAction={() => void refetch()}
      />
    );
  }

  if (!isLoading && rows.length === 0) {
    return <PageStateCard state="empty" title={title} description={t("analytics.matchQuality.noData")} />;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-1 space-y-0 pb-2">
        <CardTitle asChild>
          <h3>{title}</h3>
        </CardTitle>
        <InfoDot term="match_quality" onExplain={onExplain} />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <ul aria-hidden className="divide-y divide-[color:var(--aqt-border)]">
            {[0, 1, 2].map((row) => (
              <li key={row} className="flex flex-col gap-1.5 py-2.5">
                <span className="flex items-center gap-3">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="ml-auto h-4 w-8" />
                </span>
                <Skeleton className="h-3 w-56" />
              </li>
            ))}
          </ul>
        ) : (
          <ul className="divide-y divide-[color:var(--aqt-border)]">
            {rows.map((row) => {
              const encounter = encounterById.get(row.encounter_id);
              const [one, two] = duelSeats(encounter?.teams);
              const flags = row.anomaly_flags ?? [];
              return (
                <li key={row.encounter_id} className="flex flex-col gap-1 py-2.5">
                  <div className="flex items-center gap-3">
                    <span className="flex min-w-0 flex-1 items-center gap-1.5 text-body font-medium text-[color:var(--aqt-fg)]">
                      {one && two ? (
                        <>
                          <TeamName team={{ name: one.name, image_url: one.team?.image_url }} size="xs" />
                          <span className="shrink-0 font-normal text-[color:var(--aqt-fg-dim)]">
                            {t("analytics.matchQuality.vs")}
                          </span>
                          <TeamName team={{ name: two.name, image_url: two.team?.image_url }} size="xs" />
                        </>
                      ) : (
                        <span className="truncate">
                          {encounter?.name?.trim() ||
                            t("analytics.matchQuality.encounter", { id: row.encounter_id })}
                        </span>
                      )}
                    </span>
                    <span
                      className="aqt-tnum shrink-0 text-ui font-semibold"
                      style={{ color: qualityTone(row.quality_score) }}
                    >
                      <span className="sr-only">{t("analytics.glossary.match_quality.label")} </span>
                      {whole(row.quality_score)}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="text-caption text-[color:var(--aqt-fg-muted)]">
                      {t("analytics.matchQuality.comp")}{" "}
                      <span className="aqt-tnum text-[color:var(--aqt-fg)]">{whole(row.competitiveness)}</span>
                      <span aria-hidden className="mx-1.5 text-[color:var(--aqt-fg-dim)]">
                        ·
                      </span>
                      {t("analytics.matchQuality.pred")}{" "}
                      <span className="aqt-tnum text-[color:var(--aqt-fg)]">{whole(row.predictability)}</span>
                      <span aria-hidden className="mx-1.5 text-[color:var(--aqt-fg-dim)]">
                        ·
                      </span>
                      {t("analytics.matchQuality.skill")}{" "}
                      <span className="aqt-tnum text-[color:var(--aqt-fg)]">{whole(row.skill_balance)}</span>
                    </span>
                    {flags.length > 0 ? (
                      <span className="flex flex-wrap items-center gap-2">
                        {flags.map((flag, index) => (
                          <span
                            key={`${flag.player_id}-${flag.kind}-${index}`}
                            className="inline-flex items-center gap-1.5"
                          >
                            <AnomalyFlag kind={flag.kind} reasons={flag.reasons} label="short" />
                            {playerNames?.get(flag.player_id) ? (
                              <span className="text-caption text-[color:var(--aqt-fg-muted)]">
                                {splitHandle(playerNames.get(flag.player_id)!).name}
                              </span>
                            ) : null}
                            {canReview ? (
                              <FeedbackButtons
                                current={verdictByKey.get(`${flag.player_id}-${flag.kind}`)}
                                pending={feedbackMutation.isPending}
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
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
