"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import captainService from "@/services/captain.service";
import type { Encounter } from "@/types/encounter.types";
import type { EncounterResultStatus } from "@/types/tournament.types";

type ResultStatusLabelKey =
  | "encounters.result.none"
  | "encounters.result.pendingConfirmation"
  | "encounters.result.confirmed"
  | "encounters.result.disputed";

const RESULT_STATUS_CONFIG: Record<
  EncounterResultStatus,
  { labelKey: ResultStatusLabelKey; color: string }
> = {
  none: { labelKey: "encounters.result.none", color: "bg-gray-500" },
  pending_confirmation: {
    labelKey: "encounters.result.pendingConfirmation",
    color: "bg-yellow-500",
  },
  confirmed: { labelKey: "encounters.result.confirmed", color: "bg-green-500" },
  disputed: { labelKey: "encounters.result.disputed", color: "bg-red-500" },
};

interface ResultSubmissionProps {
  encounter: Encounter;
  isCaptain: boolean;
  captainSide: "home" | "away" | null;
}

export function ResultSubmission({
  encounter,
  isCaptain,
  captainSide,
}: ResultSubmissionProps) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [homeScore, setHomeScore] = useState(encounter.score?.home ?? 0);
  const [awayScore, setAwayScore] = useState(encounter.score?.away ?? 0);

  const statusConfig = RESULT_STATUS_CONFIG[encounter.result_status];
  const isSubmitter = encounter.submitted_by_id !== null;
  const canSubmit =
    isCaptain &&
    (encounter.result_status === "none" || encounter.result_status === "disputed");
  const canConfirm =
    isCaptain && encounter.result_status === "pending_confirmation";
  const canDispute =
    isCaptain && encounter.result_status === "pending_confirmation";

  const submitMutation = useMutation({
    mutationFn: () =>
      captainService.submitResult(encounter.id, {
        home_score: homeScore,
        away_score: awayScore,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounter", encounter.id],
      });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () => captainService.confirmResult(encounter.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounter", encounter.id],
      });
    },
  });

  const disputeMutation = useMutation({
    mutationFn: () => captainService.disputeResult(encounter.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["encounter", encounter.id],
      });
    },
  });

  if (!isCaptain) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          {t("encounters.result.title")}
          <Badge className={`${statusConfig.color} text-white`}>
            {t(statusConfig.labelKey)}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {canSubmit && (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {encounter.home_team?.name ?? t("encounters.result.home")}
              </span>
              <Input
                type="number"
                min={0}
                value={homeScore}
                onChange={(e) => setHomeScore(Number(e.target.value))}
                className="w-16"
              />
            </div>
            <span className="text-muted-foreground">{t("common.vs")}</span>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                value={awayScore}
                onChange={(e) => setAwayScore(Number(e.target.value))}
                className="w-16"
              />
              <span className="text-sm font-medium">
                {encounter.away_team?.name ?? t("encounters.result.away")}
              </span>
            </div>
            <Button
              disabled={submitMutation.isPending}
              onClick={() => submitMutation.mutate()}
            >
              {submitMutation.isPending
                ? t("encounters.result.submitting")
                : t("encounters.result.submit")}
            </Button>
          </div>
        )}

        {encounter.result_status === "pending_confirmation" && (
          <div className="text-sm text-muted-foreground">
            {t("encounters.result.submittedScore", {
              home: String(encounter.score?.home ?? 0),
              away: String(encounter.score?.away ?? 0),
            })}
          </div>
        )}

        {canConfirm && (
          <div className="flex gap-2">
            <Button
              disabled={confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              {confirmMutation.isPending
                ? t("encounters.result.confirming")
                : t("encounters.result.confirm")}
            </Button>
            <Button
              variant="destructive"
              disabled={disputeMutation.isPending}
              onClick={() => disputeMutation.mutate()}
            >
              {disputeMutation.isPending ? "..." : t("encounters.result.dispute")}
            </Button>
          </div>
        )}

        {encounter.result_status === "disputed" && (
          <div className="text-sm text-red-500">
            {t("encounters.result.disputedNotice")}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
