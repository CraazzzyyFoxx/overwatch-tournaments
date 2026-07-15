"use client";

import { useState } from "react";
import { Ban, Download, Pause, Play, RotateCcw, ShieldCheck, Sparkles } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { notify } from "@/lib/notify";
import type { DraftBoard, DraftPickOption, DraftPickOptionsResponse } from "@/types/draft.types";
import type { DraftLifecycleAction } from "@/app/(site)/tournaments/[id]/draft/_hooks/useDraftData";
import { useDraftMutations } from "@/app/(site)/tournaments/[id]/draft/_hooks/useDraftData";

import { buildOverrideRequest } from "./admin-control-model";

interface LifecycleControlsProps {
  tournamentId: number;
  board: DraftBoard;
  options: DraftPickOptionsResponse | null;
}

type ConfirmedAction = Extract<DraftLifecycleAction, "rollback" | "cancel" | "export"> | "autopick";

export function LifecycleControls({ tournamentId, board, options }: LifecycleControlsProps) {
  const t = useTranslations("draftAdmin.controlRoom");
  const mutations = useDraftMutations(tournamentId);
  const [confirmedAction, setConfirmedAction] = useState<ConfirmedAction | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideValue, setOverrideValue] = useState("");
  const [overrideNote, setOverrideNote] = useState("");
  const session = board.session;
  const currentPick = board.current_pick;
  const resolvedCount = board.picks.filter((pick) =>
    ["completed", "autopicked", "skipped"].includes(pick.status)
  ).length;
  const safeOptions = options?.options.filter((option) => option.is_safe) ?? [];
  const lifecycleBusy = mutations.lifecycle.isPending;

  const runDirect = (action: "pause" | "resume") => {
    mutations.lifecycle.mutate(
      { sessionId: session.id, action },
      {
        onSuccess: () => notify.success(t(`actionSuccess.${action}`)),
        onError: (error) => notify.apiError(error)
      }
    );
  };

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

  const selectedOverride = safeOptions.find(
    (option) => `${option.player_id}:${option.role}` === overrideValue
  );
  const runOverride = () => {
    if (!currentPick || !selectedOverride || !overrideNote.trim()) return;
    const request = buildOverrideRequest(selectedOverride, currentPick.version, overrideNote);
    mutations.override.mutate(
      {
        pickId: currentPick.id,
        playerId: request.player_id,
        version: request.expected_version,
        role: request.target_role,
        note: request.note
      },
      {
        onSuccess: () => {
          notify.success(t("actionSuccess.override"));
          setOverrideOpen(false);
          setOverrideValue("");
          setOverrideNote("");
        },
        onError: (error) => notify.apiError(error)
      }
    );
  };

  const optionLabel = (option: DraftPickOption) => {
    const player = board.players.find((candidate) => candidate.id === option.player_id);
    return `${player?.battle_tag ?? `#${option.player_id}`} · ${t(`roles.${option.role}`)}`;
  };

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {session.status === "live" && (
          <Button variant="outline" disabled={lifecycleBusy} onClick={() => runDirect("pause")}>
            <Pause className="mr-2 h-4 w-4" />{t("actions.pause")}
          </Button>
        )}
        {session.status === "paused" && (
          <Button disabled={lifecycleBusy} onClick={() => runDirect("resume")}>
            <Play className="mr-2 h-4 w-4" />{t("actions.resume")}
          </Button>
        )}
        {session.status === "live" && currentPick && (
          <>
            <Button variant="outline" onClick={() => setConfirmedAction("autopick")}>
              <Sparkles className="mr-2 h-4 w-4" />{t("actions.autopick")}
            </Button>
            <Button
              variant="outline"
              disabled={!session.allow_admin_override || safeOptions.length === 0}
              onClick={() => setOverrideOpen(true)}
            >
              <ShieldCheck className="mr-2 h-4 w-4" />{t("actions.override")}
            </Button>
          </>
        )}
        {resolvedCount > 0 && ["live", "paused", "completed"].includes(session.status) && (
          <Button variant="outline" onClick={() => setConfirmedAction("rollback")}>
            <RotateCcw className="mr-2 h-4 w-4" />{t("actions.rollback")}
          </Button>
        )}
        {["live", "paused", "ready"].includes(session.status) && (
          <Button variant="destructive" onClick={() => setConfirmedAction("cancel")}>
            <Ban className="mr-2 h-4 w-4" />{t("actions.cancel")}
          </Button>
        )}
        {session.status === "completed" && (
          <Button onClick={() => setConfirmedAction("export")}>
            <Download className="mr-2 h-4 w-4" />{t("actions.export")}
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
              onClick={(event) => {
                event.preventDefault();
                runConfirmed();
              }}
            >
              {t("confirmAction")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={overrideOpen} onOpenChange={setOverrideOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("overrideTitle")}</DialogTitle>
            <DialogDescription>{t("overrideDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="override-option">{t("overrideOption")}</Label>
              <Select value={overrideValue} onValueChange={setOverrideValue}>
                <SelectTrigger id="override-option"><SelectValue placeholder={t("overrideSelect")} /></SelectTrigger>
                <SelectContent>
                  {safeOptions.map((option) => (
                    <SelectItem
                      key={`${option.player_id}:${option.role}`}
                      value={`${option.player_id}:${option.role}`}
                    >
                      {optionLabel(option)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="override-note">{t("overrideReason")}</Label>
              <Textarea
                id="override-note"
                value={overrideNote}
                onChange={(event) => setOverrideNote(event.target.value)}
                placeholder={t("overrideReasonPlaceholder")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              disabled={!selectedOverride || !overrideNote.trim() || mutations.override.isPending}
              onClick={runOverride}
            >
              {t("actions.override")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

