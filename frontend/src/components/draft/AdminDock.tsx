"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Pause, Play, Plus, RotateCcw, Zap } from "lucide-react";
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
import { useDraftFeasibilityQuery, type DraftMutations } from "@/hooks/useDraftData";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { DraftBoard } from "@/types/draft.types";

type PendingConfirm = "autopick" | "rollback" | null;

const EXTEND_STEPS = [15, 30] as const;

interface AdminDockProps {
  board: DraftBoard;
  mutations: DraftMutations;
  /** Auth user ids of connected captains, for the presence counter. */
  onlineCaptainIds?: ReadonlySet<number>;
}

/**
 * The organizer's row of the command bar.
 *
 * Everything an admin does WHILE the draft runs belongs next to the clock they
 * are watching, not on a separate control page they would have to keep open in
 * a second tab: pausing, buying the captain more time, forcing the pick and
 * rolling the last one back are all reactions to what the bar above is showing.
 */
export function AdminDock({ board, mutations, onlineCaptainIds }: Readonly<AdminDockProps>) {
  const t = useTranslations("draftRedesign");
  const [confirming, setConfirming] = useState<PendingConfirm>(null);
  const feasibilityQuery = useDraftFeasibilityQuery(board.session.id);
  const feasibility = feasibilityQuery.data ?? null;
  const session = board.session;
  const current = board.current_pick;
  const clockRunning = session.status === "live" || session.status === "paused";
  const canExtend = current != null && clockRunning;
  const canAutopick = current != null && clockRunning;
  const canRollback = board.picks.some(
    (pick) => pick.status === "completed" || pick.status === "autopicked"
  );
  const captainsTotal = board.teams.filter((team) => team.captain_auth_user_id != null).length;
  const captainsOnline = board.teams.filter(
    (team) => team.captain_auth_user_id != null && (onlineCaptainIds?.has(team.captain_auth_user_id) ?? false)
  ).length;

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
    <div
      className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-[color:var(--aqt-border-2)] pt-2"
      aria-label={t("admin.dock")}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-9"
        disabled={session.status !== "live" || mutations.lifecycle.isPending}
        onClick={() => runLifecycle("pause")}
      >
        <Pause className="mr-1.5 h-4 w-4" aria-hidden />
        {t("admin.pause")}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-9"
        disabled={session.status !== "paused" || mutations.lifecycle.isPending}
        onClick={() => runLifecycle("resume")}
      >
        <Play className="mr-1.5 h-4 w-4" aria-hidden />
        {t("admin.resume")}
      </Button>
      {EXTEND_STEPS.map((seconds) => (
        <Button
          key={seconds}
          type="button"
          variant="outline"
          size="sm"
          className="min-h-9 tabular-nums"
          disabled={!canExtend || mutations.extendClock.isPending}
          onClick={() => extend(seconds)}
        >
          <Plus className="mr-1 h-4 w-4" aria-hidden />
          {t("admin.addSeconds", { seconds })}
        </Button>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-9"
        disabled={!canAutopick || mutations.autopick.isPending}
        onClick={() => setConfirming("autopick")}
      >
        <Zap className="mr-1.5 h-4 w-4" aria-hidden />
        {t("admin.autopick")}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-9"
        disabled={!canRollback || mutations.lifecycle.isPending}
        onClick={() => setConfirming("rollback")}
      >
        <RotateCcw className="mr-1.5 h-4 w-4" aria-hidden />
        {t("admin.rollback")}
      </Button>

      <span className="ml-auto flex flex-wrap items-center gap-3 text-xs text-[color:var(--aqt-fg-muted)]">
        <span className="tabular-nums">
          {t("admin.captainsOnline", { online: captainsOnline, total: captainsTotal })}
        </span>
        {/* Feasibility is the one number that decides whether this draft can
            still finish; the fix for it lives on the setup page, so a failing
            chip carries the link there instead of only a verdict. */}
        {feasibility != null && (
          <span
            className={cn(
              "inline-flex items-center gap-1",
              feasibility.is_feasible
                ? "text-[color:var(--aqt-support)]"
                : "text-[color:var(--aqt-live)]"
            )}
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
                  className="underline underline-offset-2"
                >
                  {t("admin.infeasible")}
                </Link>
              </>
            )}
          </span>
        )}
      </span>

      <Dialog open={confirming != null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirming === "rollback" ? t("admin.rollbackTitle") : t("admin.autopickTitle")}
            </DialogTitle>
            <DialogDescription>
              {confirming === "rollback"
                ? t("admin.rollbackDescription")
                : t("admin.autopickDescription")}
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
              {confirming === "rollback" ? t("admin.rollback") : t("admin.autopick")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
