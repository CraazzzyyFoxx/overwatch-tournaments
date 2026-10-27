"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { type Tone } from "@/components/ui/tone";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";
import type { DraftSession, DraftStatus } from "@/types/draft.types";

interface DraftHistoryPanelProps {
  tournamentId: number;
  /** Notified with the erased session id so the caller can reset a stale wizard. */
  onSessionDeleted?: (sessionId: number) => void;
}

/**
 * A pill only for a session that still wants attention; history is mostly
 * finished sessions, and their status is a word in the meta line.
 */
const STATUS_TONE: Partial<Record<DraftStatus, Tone>> = {
  ready: "accent",
  live: "info",
  paused: "warning"
};

export function DraftHistoryPanel({ tournamentId, onSessionDeleted }: Readonly<DraftHistoryPanelProps>) {
  const t = useTranslations("draftAdmin");
  const tTable = useTranslations("kitTable.dataTableExtra");
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
      onSessionDeleted?.(sessionId);
      await invalidate();
    },
    onError: (error) => notify.apiError(error, { title: t("history.deleteFailed") })
  });

  const exportMutation = useMutation({
    mutationFn: (sessionId: number) => draftService.exportDraft(tournamentId, sessionId),
    onSuccess: async (result) => {
      const advisories = result.advisories;
      const showResult = advisories.length ? notify.warning : notify.success;
      showResult(t("lifecycleSuccess", { action: t("actions.export") }), {
        description: advisories.join("\n"),
        duration: advisories.length ? Infinity : undefined,
        classNames: { description: "whitespace-pre-line" }
      });
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

  if (sessionsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("history.loadFailed")}
        onAction={() => void sessionsQuery.refetch()}
      />
    );
  }

  return (
    <section className="rounded-xl border border-border">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" aria-hidden />
          <h3 className="text-sm font-semibold">{t("history.title")}</h3>
        </div>
        <p className="text-xs text-muted-foreground">{t("history.hint")}</p>
      </header>

      {sessionsQuery.isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : sessions.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">{t("history.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {sessions.map((session) => {
            // A draft on the clock must be cancelled before it can be erased.
            const inFlight = session.status === "live" || session.status === "paused";
            const tone = STATUS_TONE[session.status];
            const name = t("sessionNumber", { id: session.id });
            const meta = [
              tone ? null : t(`statuses.${session.status}`),
              session.created_at
                ? format.dateTime(new Date(session.created_at), { dateStyle: "medium", timeStyle: "short" })
                : null,
              t(`formats.${session.format}.title`),
              t("roundsShort", { rounds: session.rounds })
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <li key={session.id} className="flex items-start gap-2 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium tabular-nums">{name}</span>
                    {tone ? (
                      <StatusPill tone={tone} className="shrink-0">
                        {t(`statuses.${session.status}`)}
                      </StatusPill>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-caption tabular-nums text-muted-foreground">{meta}</p>
                </div>
                {/* Exporting is what a finished draft is for, so it sits on the row. */}
                {session.status === "completed" && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    disabled={pending}
                    onClick={() => exportMutation.mutate(session.id)}
                  >
                    {t("actions.export")}
                  </Button>
                )}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 shrink-0 text-muted-foreground"
                      aria-label={tTable("actionsFor", { label: name })}
                      title={tTable("actionsFor", { label: name })}
                    >
                      <MoreHorizontal className="h-4 w-4" aria-hidden />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-48">
                    <DropdownMenuItem asChild>
                      <Link href={`/draft/${tournamentId}`} target="_blank">
                        {t("openBoard")}
                      </Link>
                    </DropdownMenuItem>
                    {session.status === "completed" && (
                      <DropdownMenuItem
                        disabled={pending}
                        title={t("actions.exportRanksHint")}
                        onSelect={() => exportRanksMutation.mutate(session.id)}
                      >
                        {t("actions.exportRanks")}
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuItem
                      disabled={pending || inFlight}
                      variant="destructive"
                      onSelect={() => setPendingDelete(session)}
                    >
                      <span>
                        {t("history.delete", { id: session.id })}
                        {inFlight && (
                          <span className="block text-caption text-muted-foreground">
                            {t("history.cancelFirst")}
                          </span>
                        )}
                      </span>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
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
