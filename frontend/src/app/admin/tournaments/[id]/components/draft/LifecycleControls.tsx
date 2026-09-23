"use client";

import { useState } from "react";
import { Ban, Download, RotateCcw, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import type { DraftBoard } from "@/types/draft.types";
import type { DraftLifecycleAction } from "@/hooks/useDraftData";
import { useDraftMutations } from "@/hooks/useDraftData";

interface LifecycleControlsProps {
  tournamentId: number;
  board: DraftBoard;
}

type ConfirmedAction = Extract<DraftLifecycleAction, "rollback" | "cancel" | "export"> | "autopick";

/**
 * The lifecycle actions that END or REWIND a session, each behind a confirm.
 *
 * Pause, resume, extra time and override are not here: they steer a pick in
 * flight and belong to the admin dock inside the draft room, where the board
 * they act on is visible.
 */
export function LifecycleControls({ tournamentId, board }: Readonly<LifecycleControlsProps>) {
  const t = useTranslations("draftAdmin.controlRoom");
  const mutations = useDraftMutations(tournamentId);
  const [confirmedAction, setConfirmedAction] = useState<ConfirmedAction | null>(null);
  const session = board.session;
  const currentPick = board.current_pick;
  const resolvedCount = board.picks.filter((pick) =>
    ["completed", "autopicked", "skipped"].includes(pick.status)
  ).length;

  const runConfirmed = () => {
    const action = confirmedAction;
    if (!action) return;
    if (action === "autopick") {
      if (!currentPick) return;
      mutations.autopick.mutate(
        { pickId: currentPick.id, version: currentPick.version },
        {
          onSuccess: () => {
            notify.success(t("actionSuccess.autopick"));
            setConfirmedAction(null);
          },
          onError: (error) => notify.apiError(error)
        }
      );
      return;
    }
    mutations.lifecycle.mutate(
      { sessionId: session.id, action },
      {
        onSuccess: () => {
          notify.success(t(`actionSuccess.${action}`));
          setConfirmedAction(null);
        },
        onError: (error) => notify.apiError(error)
      }
    );
  };

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {session.status === "live" && currentPick && (
          <Button variant="outline" onClick={() => setConfirmedAction("autopick")}>
            <Sparkles className="mr-2 h-4 w-4" aria-hidden />
            {t("actions.autopick")}
          </Button>
        )}
        {resolvedCount > 0 && ["live", "paused", "completed"].includes(session.status) && (
          <Button variant="outline" onClick={() => setConfirmedAction("rollback")}>
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden />
            {t("actions.rollback")}
          </Button>
        )}
        {["live", "paused", "ready"].includes(session.status) && (
          <Button variant="destructive" onClick={() => setConfirmedAction("cancel")}>
            <Ban className="mr-2 h-4 w-4" aria-hidden />
            {t("actions.cancel")}
          </Button>
        )}
        {session.status === "completed" && (
          <Button onClick={() => setConfirmedAction("export")}>
            <Download className="mr-2 h-4 w-4" aria-hidden />
            {t("actions.export")}
          </Button>
        )}
      </div>

      <AlertDialog
        open={confirmedAction != null}
        onOpenChange={(open) => !open && setConfirmedAction(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmedAction ? t(`confirm.${confirmedAction}.title`) : ""}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmedAction ? t(`confirm.${confirmedAction}.description`) : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("dismiss")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={mutations.lifecycle.isPending || mutations.autopick.isPending}
              className={
                confirmedAction === "cancel" ? buttonVariants({ variant: "destructive" }) : undefined
              }
              onClick={(event) => {
                event.preventDefault();
                runConfirmed();
              }}
            >
              {confirmedAction ? t(`actions.${confirmedAction}`) : ""}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
