"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { PageStateCard } from "@/components/ui/page-state-card";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";

import { tabFallback, useHubTournamentQuery } from "../hubQueries";

import { AdminControlRoom } from "./draft/AdminControlRoom";
import { DraftHistoryPanel } from "./draft/DraftHistoryPanel";
import { DraftSetupWizard } from "./draft/DraftSetupWizard";
import { EmptyNote } from "@/components/kit/EmptyNote";

interface DraftSessionDashboardProps {
  tournamentId: number;
  formationNodeId: number;
  canManage: boolean;
}

export function DraftSessionDashboard({
  tournamentId,
  formationNodeId,
  canManage
}: Readonly<DraftSessionDashboardProps>) {
  const t = useTranslations("draftAdmin");
  const [wizardEpoch, setWizardEpoch] = useState(0);
  const boardKey = tournamentQueryKeys.draftBoard(tournamentId, formationNodeId);
  const boardQuery = useQuery({
    queryKey: boardKey,
    queryFn: () => draftService.getTournamentBoard(tournamentId, formationNodeId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });
  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const board = boardQuery.data ?? null;
  const session = board?.session ?? null;

  // A draft cannot be configured without the tournament's roster shape: the
  // wizard reads rounds and roster size off it instead of deriving them.
  const rosterShape = tournamentQuery.data?.roster_shape ?? null;
  if (boardQuery.isLoading || tournamentQuery.isLoading) {
    return tabFallback;
  }
  if (boardQuery.isError || tournamentQuery.isError || rosterShape == null) {
    return (
      <PageStateCard
        state="error"
        title={t("loadFailed")}
        description={t("loadFailedHint")}
        onAction={() => {
          void boardQuery.refetch();
          void tournamentQuery.refetch();
        }}
      />
    );
  }
  if (!canManage) {
    return <EmptyNote>{t("noPermission")}</EmptyNote>;
  }

  if (board && session && (session.status === "live" || session.status === "paused")) {
    return <AdminControlRoom tournamentId={tournamentId} formationNodeId={formationNodeId} board={board} />;
  }

  const terminalSession =
    session && (session.status === "completed" || session.status === "cancelled") ? session : null;
  return (
    <DraftSetupWizard
      // Erasing the session the wizard is editing must clear its local state:
      // the wizard prefers its own copy over the refetched board, so a stale
      // session would otherwise survive the delete.
      key={wizardEpoch}
      tournamentId={tournamentId}
      formationNodeId={formationNodeId}
      board={terminalSession ? null : board}
      rosterShape={rosterShape}
      // Past sessions sit under the step rail (F5 ·4), collapsed: they are
      // context for the session being set up, not a competing surface. Open
      // after a completed draft, whose Export to teams is the next step.
      aside={
        <Collapsible defaultOpen={session?.status === "completed"}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full justify-between">
              {t("history.title")}
              <ChevronDown aria-hidden className="size-4 text-muted-foreground" />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <DraftHistoryPanel
              tournamentId={tournamentId}
              formationNodeId={formationNodeId}
              onSessionDeleted={(sessionId) => {
                if (sessionId === session?.id) setWizardEpoch((epoch) => epoch + 1);
              }}
            />
          </CollapsibleContent>
        </Collapsible>
      }
    />
  );
}
