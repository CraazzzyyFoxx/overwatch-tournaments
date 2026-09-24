"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type Tone } from "@/components/kit/tone";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";
import type { DraftSession, DraftStatus } from "@/types/draft.types";

interface DraftHistoryPanelProps {
  tournamentId: number;
  /** Notified with the erased session id so the caller can reset a stale wizard. */
  onSessionDeleted: (sessionId: number) => void;
}

const STATUS_TONE: Record<DraftStatus, Tone> = {
  setup: "neutral",
  ready: "accent",
  live: "info",
  paused: "warning",
  completed: "success",
  cancelled: "danger"
};

export function DraftHistoryPanel({ tournamentId, onSessionDeleted }: Readonly<DraftHistoryPanelProps>) {
  const t = useTranslations("draftAdmin");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const [pendingDelete, setPendingDelete] = useState<DraftSession | null>(null);

  const sessionsKey = tournamentQueryKeys.draftSessions(tournamentId);
  const sessionsQuery = useQuery({
    queryKey: sessionsKey,
    queryFn: () => draftService.listSessions(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: sessionsKey }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftBoard(tournamentId) })
    ]);
  };

  const deleteMutation = useMutation({
    mutationFn: (sessionId: number) => draftService.deleteSession(tournamentId, sessionId),
    onSuccess: async (_result, sessionId) => {
      setPendingDelete(null);
      notify.success(t("history.deleted", { id: sessionId }));
      onSessionDeleted(sessionId);
      await invalidate();
    },
    onError: (error) => notify.apiError(error, { title: t("history.deleteFailed") })
  });

  const exportMutation = useMutation({
    mutationFn: (sessionId: number) => draftService.lifecycle(tournamentId, sessionId, "export"),
    onSuccess: async () => {
      notify.success(t("lifecycleSuccess", { action: t("actions.export") }));
      await invalidate();
    },
    onError: (error) => notify.apiError(error)
  });

  // Corrective, non-destructive counterpart to Export: the exported teams (and
  // any bracket on them) stay, only the player ranks are refreshed.
  const exportRanksMutation = useMutation({
    mutationFn: (sessionId: number) => draftService.exportRanks(tournamentId, sessionId),
    onSuccess: async (result) => {
      notify.success(t("actions.exportRanksDone", { count: result.updated_players }));
      await invalidate();
    },
    onError: (error) => notify.apiError(error)
  });

  const sessions = sessionsQuery.data ?? [];
  const pending = deleteMutation.isPending || exportMutation.isPending || exportRanksMutation.isPending;

  return (
    <section className="rounded-xl border border-border/70">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" aria-hidden />
          <h3 className="text-sm font-semibold">{t("history.title")}</h3>
          {sessions.length > 0 && (
            <Badge variant="secondary" className="tabular-nums">
              {sessions.length}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{t("history.hint")}</p>
      </header>

      {sessionsQuery.isLoading ? (
        <div className="h-24 animate-pulse rounded-b-xl bg-muted/40" />
      ) : sessionsQuery.isError ? (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 text-sm text-muted-foreground">
          <span>{t("history.loadFailed")}</span>
          <Button variant="outline" size="sm" onClick={() => void sessionsQuery.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : sessions.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">{t("history.empty")}</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {sessions.map((session) => {
            // A draft on the clock must be cancelled before it can be erased.
            const inFlight = session.status === "live" || session.status === "paused";
            return (
            <li
              key={session.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-sm"
            >
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {t("sessionNumber", { id: session.id })}
              </span>
              <StatusPill tone={STATUS_TONE[session.status]} className="shrink-0">
                {t(`statuses.${session.status}`)}
              </StatusPill>
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground tabular-nums">
                {session.created_at
                  ? format.dateTime(new Date(session.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short"
                    })
                  : "—"}
                {" · "}
                {t(`formats.${session.format}.title`)}
                {" · "}
                {t("roundsShort", { rounds: session.rounds })}
              </span>
              {/* Wraps rather than staying on one line: this panel now lives in
                  the wizard's 220px rail (F5 ·4), where three buttons abreast
                  would overflow it. */}
              <div className="flex flex-wrap items-center gap-2">
                <Button asChild variant="outline" size="sm">
                  <Link href={`/draft/${tournamentId}`} target="_blank">
                    {t("openBoard")}
                  </Link>
                </Button>
                {session.status === "completed" && (
                  <>
                    <Button
                      size="sm"
                      disabled={pending}
                      onClick={() => exportMutation.mutate(session.id)}
                    >
                      {t("actions.export")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={pending}
                      title={t("actions.exportRanksHint")}
                      onClick={() => exportRanksMutation.mutate(session.id)}
                    >
                      {t("actions.exportRanks")}
                    </Button>
                  </>
                )}
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-danger hover:bg-danger/10 hover:text-danger"
                  disabled={pending || inFlight}
                  title={inFlight ? t("history.cancelFirst") : undefined}
                  aria-label={t("history.delete", { id: session.id })}
                  onClick={() => setPendingDelete(session)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            </li>
            );
          })}
        </ul>
      )}

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        intent={{
          title: t("history.confirmTitle", { id: pendingDelete?.id ?? 0 }),
          description: t("history.confirmDescription"),
          confirmLabel: t("history.deleteConfirm"),
          tone: "danger"
        }}
        pending={deleteMutation.isPending}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </section>
  );
}
