"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";

import { useHubTournamentQuery } from "../hubQueries";

import { AdminControlRoom } from "./draft/AdminControlRoom";
import { DraftHistoryPanel } from "./draft/DraftHistoryPanel";
import { DraftSetupWizard } from "./draft/DraftSetupWizard";
import { EmptyNote } from "@/components/kit/EmptyNote";

interface DraftSessionDashboardProps {
  tournamentId: number;
  canManage: boolean;
}

export function DraftSessionDashboard({
  tournamentId,
  canManage
}: Readonly<DraftSessionDashboardProps>) {
  const t = useTranslations("draftAdmin");
  const [wizardEpoch, setWizardEpoch] = useState(0);
  const boardKey = tournamentQueryKeys.draftBoard(tournamentId);
  const boardQuery = useQuery({
    queryKey: boardKey,
    queryFn: () => draftService.getTournamentBoard(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });
  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const board = boardQuery.data ?? null;
  const session = board?.session ?? null;

  // A draft cannot be configured without the tournament's roster shape: the
  // wizard reads rounds and roster size off it instead of deriving them.
  const rosterShape = tournamentQuery.data?.roster_shape ?? null;
  if (boardQuery.isLoading || tournamentQuery.isLoading) {
    return <div className="h-64 animate-pulse rounded-2xl bg-muted/50" />;
  }
  if (boardQuery.isError || tournamentQuery.isError || rosterShape == null) {
    return (
      <EmptyNote
        tone="danger"
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void boardQuery.refetch();
              void tournamentQuery.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
      >
        <span className="font-medium text-foreground">{t("loadFailed")}</span> {t("loadFailedHint")}
      </EmptyNote>
    );
  }
  if (!canManage) {
    return <EmptyNote>{t("noPermission")}</EmptyNote>;
  }

  if (board && session && (session.status === "live" || session.status === "paused")) {
    return <AdminControlRoom tournamentId={tournamentId} board={board} />;
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
      board={terminalSession ? null : board}
      rosterShape={rosterShape}
      // Past sessions sit under the step rail (F5 ·4), collapsed: they are
      // context for the session being set up, not a competing surface.
      aside={
        <Collapsible>
          <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2 text-sm">
            {t("history.title")}
            <ChevronDown aria-hidden className="size-4 text-muted-foreground" />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <DraftHistoryPanel
              tournamentId={tournamentId}
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
