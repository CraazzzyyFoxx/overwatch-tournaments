"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import captainService from "@/services/captain.service";
import type { Encounter } from "@/types/encounter.types";
import type { EncounterResultStatus } from "@/types/tournament.types";

const RESULT_STATUS_CONFIG: Record<
  EncounterResultStatus,
  { label: string; color: string }
> = {
  none: { label: "No result", color: "bg-gray-500" },
  pending_confirmation: { label: "Pending confirmation", color: "bg-yellow-500" },
  confirmed: { label: "Confirmed", color: "bg-green-500" },
  disputed: { label: "Disputed", color: "bg-red-500" },
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
          Match Result
          <Badge className={`${statusConfig.color} text-white`}>
            {statusConfig.label}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {canSubmit && (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {encounter.home_team?.name ?? "Home"}
              </span>
              <Input
                type="number"
                min={0}
                value={homeScore}
                onChange={(e) => setHomeScore(Number(e.target.value))}
                className="w-16"
              />
            </div>
            <span className="text-muted-foreground">vs</span>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                value={awayScore}
                onChange={(e) => setAwayScore(Number(e.target.value))}
                className="w-16"
              />
              <span className="text-sm font-medium">
                {encounter.away_team?.name ?? "Away"}
              </span>
            </div>
            <Button
              disabled={submitMutation.isPending}
              onClick={() => submitMutation.mutate()}
            >
              {submitMutation.isPending ? "Submitting..." : "Submit Result"}
            </Button>
          </div>
        )}

        {encounter.result_status === "pending_confirmation" && (
          <div className="text-sm text-muted-foreground">
            Submitted score: {encounter.score?.home} - {encounter.score?.away}
          </div>
        )}

        {canConfirm && (
          <div className="flex gap-2">
            <Button
              disabled={confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              {confirmMutation.isPending ? "Confirming..." : "Confirm Result"}
            </Button>
            <Button
              variant="destructive"
              disabled={disputeMutation.isPending}
              onClick={() => disputeMutation.mutate()}
            >
              {disputeMutation.isPending ? "..." : "Dispute"}
            </Button>
          </div>
        )}

        {encounter.result_status === "disputed" && (
          <div className="text-sm text-red-500">
            Result disputed. An admin will resolve this.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
