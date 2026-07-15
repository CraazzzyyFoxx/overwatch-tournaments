"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";

import { AdminControlRoom } from "./draft/AdminControlRoom";
import { DraftSetupWizard } from "./draft/DraftSetupWizard";

interface DraftSessionDashboardProps {
  tournamentId: number;
  canManage: boolean;
}

export function DraftSessionDashboard({ tournamentId, canManage }: DraftSessionDashboardProps) {
  const t = useTranslations("draftAdmin");
  const queryClient = useQueryClient();
  const boardKey = tournamentQueryKeys.draftBoard(tournamentId);
  const boardQuery = useQuery({
    queryKey: boardKey,
    queryFn: () => draftService.getTournamentBoard(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });
  const board = boardQuery.data ?? null;
  const session = board?.session ?? null;

  const lifecycleMutation = useMutation({
    mutationFn: (action: "pause" | "resume" | "cancel" | "export") =>
      draftService.lifecycle(tournamentId, session!.id, action),
    onSuccess: async (_result, action) => {
      notify.success(t("lifecycleSuccess", { action: t(`actions.${action}`) }));
      await queryClient.invalidateQueries({ queryKey: boardKey });
    },
    onError: (error) => notify.apiError(error)
  });

  if (boardQuery.isLoading) {
    return <div className="h-64 animate-pulse rounded-2xl bg-muted/50" />;
  }
  if (boardQuery.isError) {
    return (
      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle>{t("loadFailed")}</CardTitle>
          <CardDescription>{t("loadFailedHint")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => boardQuery.refetch()}>
            {t("retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (!canManage) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("noPermission")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (board && session && (session.status === "live" || session.status === "paused")) {
    return <AdminControlRoom tournamentId={tournamentId} board={board} />;
  }

  const terminalSession =
    session && (session.status === "completed" || session.status === "cancelled") ? session : null;
  return (
    <div className="space-y-4">
      {terminalSession && (
        <Card className="border-border/60">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {t("previousDraft")}
                  <Badge variant="secondary">{t(`statuses.${terminalSession.status}`)}</Badge>
                </CardTitle>
                <CardDescription className="mt-2">{t("previousDraftHint")}</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button asChild variant="outline">
                  <Link href={`/tournaments/${tournamentId}/draft`} target="_blank">
                    {t("openBoard")}
                  </Link>
                </Button>
                {terminalSession.status === "completed" && (
                  <Button
                    disabled={lifecycleMutation.isPending}
                    onClick={() => lifecycleMutation.mutate("export")}
                  >
                    {t("actions.export")}
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
        </Card>
      )}
      <DraftSetupWizard
        tournamentId={tournamentId}
        board={terminalSession ? null : board}
      />
    </div>
  );
}
