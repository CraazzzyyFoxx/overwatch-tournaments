"use client";

import { useState } from "react";
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
import type { DraftPlayer, DraftRole } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";

interface PickCommandBarProps {
  player: DraftPlayer | null;
  role: DraftRole | null;
  teamName: string;
  canConfirm: boolean;
  pending: boolean;
  connectionState: RealtimeConnectionState;
  announcement: string;
  onConfirm: () => void;
}

export function PickCommandBar({ player, role, teamName, canConfirm, pending, connectionState, announcement, onConfirm }: PickCommandBarProps) {
  const t = useTranslations("draftRedesign");
  const [reviewOpen, setReviewOpen] = useState(false);
  const selection = player && role ? `${player.battle_tag ?? `#${player.id}`} · ${t(`roles.${role}`)}` : t("noSelection");
  return (
    <>
      <section className="sticky bottom-2 z-20 mt-5 rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)]/95 p-3 shadow-xl backdrop-blur supports-[padding:max(0px)]:pb-[max(0.75rem,env(safe-area-inset-bottom))]" aria-label={t("pickCommand")}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">{t("selectionFor", { team: teamName })}</p>
            <p className="mt-1 truncate text-sm font-medium">{selection}</p>
          </div>
          {connectionState !== "connected" && <span className="flex items-center gap-2 text-sm text-[color:var(--aqt-warm)]"><WifiOff className="h-4 w-4" />{t("waitingFreshData")}</span>}
          <Button className="min-h-11" disabled={!canConfirm || pending} onClick={() => setReviewOpen(true)}>
            <ShieldCheck className="mr-2 h-4 w-4" />{t("reviewPick")}
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
