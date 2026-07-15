"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, ShieldCheck, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { DraftClockRing } from "./DraftClockRing";
import { resolveDraftAccent } from "../_lib/draft-visual";

interface PickCommandBarProps {
  player: DraftPlayer | null;
  role: DraftRole | null;
  teamName: string;
  canConfirm: boolean;
  pending: boolean;
  connectionState: RealtimeConnectionState;
  announcement: string;
  onConfirm: () => void;
  divisionGrid: DivisionGrid;
  board: DraftBoard;
  isMyPick: boolean;
  myTeamId: number | null;
}

export function PickCommandBar({
  player,
  role,
  teamName,
  canConfirm,
  pending,
  connectionState,
  announcement,
  onConfirm,
  divisionGrid,
  board,
  isMyPick
}: PickCommandBarProps) {
  const t = useTranslations("draftRedesign");
  const [reviewOpen, setReviewOpen] = useState(false);
  const isConnected = connectionState === "connected";
  const ready = canConfirm && !pending;
  const selection = player && role ? `${player.battle_tag ?? `#${player.id}`} · ${t(`roles.${role}`)}` : t("noSelection");
  const roleRank = player && role ? player.role_ranks[role] ?? player.rank_value ?? null : null;
  const roleDivision = roleRank != null ? resolveDivisionFromRank(divisionGrid, roleRank) : null;
  const accent = resolveDraftAccent(board);
  const current = board.current_pick;
  const onClockTeamName = board.teams.find((tm) => tm.id === current?.draft_team_id)?.name ?? "—";

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const el = event.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (el?.isContentEditable) return;
      if (event.key === "Enter" && canConfirm && !pending) {
        event.preventDefault();
        setReviewOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canConfirm, pending]);

  return (
    <>
      <section
        className={cn(
          "sticky bottom-2 z-20 mt-5 rounded-xl border bg-[color:var(--aqt-card)]/95 p-3 shadow-xl backdrop-blur transition-colors supports-[padding:max(0px)]:pb-[max(0.75rem,env(safe-area-inset-bottom))]",
          !isConnected
            ? "border-[color:var(--aqt-warm)]/60"
            : ready
              ? "border-[color:var(--aqt-teal)]/60"
              : "border-[color:var(--aqt-border-2)]"
        )}
        aria-label={t("pickCommand")}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <DraftClockRing expiresAt={current?.clock_expires_at ?? null} paused={board.session.status === "paused"} totalSeconds={board.session.pick_time_seconds} accent={accent} />
          <div className="shrink-0 border-r border-[color:var(--aqt-border-2)] pr-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[color:var(--aqt-teal)]">{isMyPick ? t("yourTurn") : t("onClockLabel")}</p>
            <p className="text-sm font-semibold">{onClockTeamName} <span className="font-normal text-[color:var(--aqt-fg-muted)]">· {t("pickMeta", { pick: current?.overall_no ?? 0, total: board.picks.length })}</span></p>
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">{t("selectionFor", { team: teamName })}</p>
            <p className="mt-1 flex items-center gap-2 truncate text-sm font-medium">
              <span className="truncate">{selection}</span>
              {roleRank != null && (
                <span className="flex shrink-0 items-center gap-1 font-mono text-xs text-[color:var(--aqt-fg-muted)]">
                  {`${roleRank} SR`}
                  {roleDivision != null && (
                    <PlayerDivisionIcon division={roleDivision} tournamentGrid={divisionGrid} width={16} height={16} className="h-4 w-4 object-contain" />
                  )}
                </span>
              )}
            </p>
          </div>
          {!isConnected && <span className="flex items-center gap-2 text-sm text-[color:var(--aqt-warm)]"><WifiOff className="h-4 w-4" />{t("waitingFreshData")}</span>}
          <Button
            className={cn(
              "min-h-11",
              !isConnected && "bg-[color:var(--aqt-warm)] text-[color:var(--aqt-bg)] hover:bg-[color:var(--aqt-warm)]/90",
              ready && "ring-2 ring-[color:var(--aqt-teal)]/40 ring-offset-2 ring-offset-[color:var(--aqt-card)]"
            )}
            disabled={!canConfirm || pending}
            onClick={() => setReviewOpen(true)}
          >
            <ShieldCheck className="mr-2 h-4 w-4" />
            {t("reviewPick")}
            {ready && (
              <span className="ml-1 hidden items-center rounded border border-current/40 px-1.5 py-0.5 font-mono text-[10px] font-normal opacity-80 sm:inline-flex">
                {t("enterHint")}
              </span>
            )}
          </Button>
        </div>
        <p className="sr-only" aria-live="polite">{announcement}</p>
      </section>
      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("confirmPickTitle")}</DialogTitle>
            <DialogDescription>
              {t("confirmPickDescription", {
                player: player?.battle_tag ?? (player ? `#${player.id}` : "—"),
                team: teamName,
                role: role ? t(`roles.${role}`) : "—"
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-3 rounded-xl bg-[color:var(--aqt-card-2)] p-4">
            <Check className="h-5 w-5 text-[color:var(--aqt-support)]" />
            <span className="font-medium">{selection}</span>
          </div>
          <DialogFooter>
            <Button
              disabled={!canConfirm || pending}
              onClick={() => {
                onConfirm();
                setReviewOpen(false);
              }}
            >
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />}{t("confirmPick")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
