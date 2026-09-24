"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { useDraftFeasibilityQuery, useDraftJournalQuery, type DraftMutations } from "@/hooks/useDraftData";
import { notify } from "@/lib/notify";
import { captainsOnline, lastResolvedPick } from "@/lib/draft/room-model";
import type { DraftBoard } from "@/types/draft.types";

import { DraftJournal } from "./DraftJournal";

type PendingConfirm = "autopick" | "rollback" | null;

const EXTEND_STEPS = [15, 30] as const;

interface AdminStripProps {
  board: DraftBoard;
  mutations: DraftMutations;
  onlineCaptainIds: ReadonlySet<number>;
}

/**
 * The organizer's row under the clock: everything an admin does WHILE the
 * draft runs is a reaction to the clock right above it, so it lives there
 * instead of on a control page in a second tab.
 */
export function AdminStrip({ board, mutations, onlineCaptainIds }: Readonly<AdminStripProps>) {
  const t = useTranslations("draftRedesign");
  const journalId = useId();
  const [confirming, setConfirming] = useState<PendingConfirm>(null);
  const [journalOpen, setJournalOpen] = useState(false);
  const feasibility = useDraftFeasibilityQuery(board.session.id).data ?? null;
  const journal = useDraftJournalQuery(board.session.id, journalOpen);
  const session = board.session;
  const current = board.current_pick;
  const paused = session.status === "paused";
  const clockRunning = session.status === "live" || paused;
  const canExtend = current != null && clockRunning;
  const lastPick = lastResolvedPick(board);
  const captains = captainsOnline(board, onlineCaptainIds);
  const journalCount = journal.data?.entries.length;

  const runLifecycle = (action: "pause" | "resume" | "rollback") => {
    mutations.lifecycle.mutate(
      { sessionId: session.id, action },
      {
        onSuccess: () => notify.success(t(`admin.done.${action}`)),
        onError: (error) => notify.apiError(error)
      }
    );
  };
  const extend = (seconds: number) => {
    if (!current) return;
    mutations.extendClock.mutate(
      { pickId: current.id, version: current.version, seconds },
      {
        onSuccess: () => notify.success(t("admin.done.extend", { seconds })),
        onError: (error) => notify.apiError(error)
      }
    );
  };
  const autopick = () => {
    if (!current) return;
    mutations.autopick.mutate(
      { pickId: current.id, version: current.version },
      {
        onSuccess: () => notify.success(t("admin.done.autopick")),
        onError: (error) => notify.apiError(error)
      }
    );
  };

  return (
    <div className="border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]">
      <div
        role="group"
        aria-label={t("admin.dock")}
        className="mx-auto flex max-w-[1720px] flex-wrap items-center gap-2 px-4 py-1.5 sm:px-6"
      >
        <span className="mr-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-[color:var(--aqt-fg-faint)]">
          {t("shell.admin.label")}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-h-11 sm:min-h-8"
          disabled={!clockRunning || mutations.lifecycle.isPending}
          onClick={() => runLifecycle(paused ? "resume" : "pause")}
        >
          {paused ? t("admin.resume") : t("admin.pause")}
        </Button>
        {EXTEND_STEPS.map((seconds) => (
          <Button
            key={seconds}
            type="button"
            variant="outline"
            size="sm"
            className="min-h-11 tabular-nums sm:min-h-8"
            disabled={!canExtend || mutations.extendClock.isPending}
            onClick={() => extend(seconds)}
          >
            {t("admin.addSeconds", { seconds })}
          </Button>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-h-11 sm:min-h-8"
          disabled={!canExtend || mutations.autopick.isPending}
          onClick={() => setConfirming("autopick")}
        >
          {t("shell.admin.autopickNow")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-h-11 sm:min-h-8"
          disabled={lastPick == null || session.status === "cancelled" || mutations.lifecycle.isPending}
          onClick={() => setConfirming("rollback")}
        >
          {lastPick ? t("shell.admin.rollbackPick", { pick: lastPick.overall_no }) : t("admin.rollback")}
        </Button>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 sm:ml-auto">
          <span className="whitespace-nowrap text-sm tabular-nums text-[color:var(--aqt-fg-muted)]">
            {t("shell.admin.captainsOnline", { online: captains.online, total: captains.total })}
          </span>
          {/* Feasibility decides whether this draft can still finish; the fix
              lives on the setup page, so a failing chip carries the link. */}
          {feasibility != null && (
            <span
              className="inline-flex items-center gap-1 text-sm"
              style={{ color: feasibility.is_feasible ? "var(--aqt-support)" : "var(--aqt-live)" }}
            >
              {feasibility.is_feasible ? (
                <>
                  <CheckCircle2 className="h-4 w-4" aria-hidden />
                  {t("admin.feasible")}
                </>
              ) : (
                <>
                  <AlertTriangle className="h-4 w-4" aria-hidden />
                  <Link
                    href={`/admin/tournaments/${session.tournament_id}/teams/draft`}
                    className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  >
                    {t("admin.infeasible")}
                  </Link>
                </>
              )}
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="min-h-11 tabular-nums sm:min-h-8"
            aria-expanded={journalOpen}
            aria-controls={journalOpen ? journalId : undefined}
            onClick={() => setJournalOpen((open) => !open)}
          >
            {journalOpen
              ? t("shell.admin.journalHide")
              : journalCount != null
                ? t("shell.admin.journalCount", { count: journalCount })
                : t("shell.admin.journal")}
          </Button>
        </div>
      </div>

      {journalOpen && (
        <DraftJournal
          id={journalId}
          board={board}
          entries={journal.data?.entries}
          isLoading={journal.isPending}
          isError={journal.isError}
        />
      )}

      <Dialog open={confirming != null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirming === "rollback" ? t("admin.rollbackTitle") : t("admin.autopickTitle")}
            </DialogTitle>
            <DialogDescription>
              {confirming === "rollback" ? t("admin.rollbackDescription") : t("admin.autopickDescription")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(null)}>
              {t("admin.cancel")}
            </Button>
            <Button
              onClick={() => {
                if (confirming === "rollback") runLifecycle("rollback");
                else autopick();
                setConfirming(null);
              }}
            >
              {confirming === "rollback"
                ? lastPick
                  ? t("shell.admin.rollbackPick", { pick: lastPick.overall_no })
                  : t("admin.rollback")
                : t("shell.admin.autopickNow")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
