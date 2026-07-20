"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import captainService from "@/services/captain.service";
import { CaptainReportsView } from "@/components/tournaments/CaptainReportsView";
import { MatchReportDialog } from "@/components/tournaments/MatchReportDialog";
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

export function ResultSubmission({ encounter, isCaptain }: ResultSubmissionProps) {
  const t = useTranslations();
  const [reportOpen, setReportOpen] = useState(false);

  const statusConfig = RESULT_STATUS_CONFIG[encounter.result_status];
  const canReport = isCaptain && encounter.result_status !== "confirmed";

  const reportsQuery = useQuery({
    queryKey: ["encounter", encounter.id, "reports"],
    queryFn: () => captainService.getReports(encounter.id),
  });

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
        <CaptainReportsView encounter={encounter} reports={reportsQuery.data ?? []} />

        {canReport && (
          <Button onClick={() => setReportOpen(true)}>
            {t("matchReport.reportOrEdit")}
          </Button>
        )}
      </CardContent>

      <MatchReportDialog open={reportOpen} onOpenChange={setReportOpen} encounter={encounter} />
    </Card>
  );
}
