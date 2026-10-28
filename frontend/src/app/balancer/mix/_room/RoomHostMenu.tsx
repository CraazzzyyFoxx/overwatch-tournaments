"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { CHARACTER_PICK_BAN_KIND } from "@/components/pick-ban/pick-ban-model";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import type { DraftMutations } from "@/hooks/useDraftData";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { DraftBoard, DraftLifecycleAction } from "@/types/draft.types";
import type { PickBanState } from "@/types/tournament.types";

import type { RoomPhase } from "./room-model";

/** How long a host's "+30 s" extends the clock in play, a draft pick or a ban step alike. */
const EXTEND_SECONDS = 30;

/**
 * The host's ⋯ in the room's header: everything a phase allows besides its one primary action (which sits in the
 * centre). The draft: pause or resume, an autopick for an idle captain, more time, a roll back of the last pick and the
 * cancel. The bans: pause or resume, more time, the organizer controls for the rarer cases, and Cancel match, which
 * Live keeps as its only entry. Nothing for an idle or a formed lobby: their actions are all in the centre.
 */
export function RoomHostMenu({
  phase,
  board,
  draftMutations,
  heroEncounterId,
  heroState,
  heroQueryKey,
  adminOpen,
  onAdminOpenChange,
  cancellingMatch,
  onCancelMatch
}: Readonly<{
  phase: RoomPhase;
  board: DraftBoard | null;
  draftMutations: DraftMutations;
  heroEncounterId: number | null;
  heroState: PickBanState | null;
  heroQueryKey: unknown[];
  adminOpen: boolean;
  onAdminOpenChange: (open: boolean) => void;
  cancellingMatch: boolean;
  onCancelMatch: () => void;
}>) {
  const t = useTranslations("mixes.arena.host");
  const tDraft = useTranslations("mixes.draft");
  const tRoom = useTranslations("mixes.room");
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<"cancelDraft" | "cancelMatch" | null>(null);
  const refreshHeroes = () => void queryClient.invalidateQueries({ queryKey: heroQueryKey });
  const heroPause = useMutation({
    mutationFn: (paused: boolean) =>
      adminService.adminPickBanPause(heroEncounterId as number, { kind: CHARACTER_PICK_BAN_KIND, paused }),
    onError: (error) => notify.apiError(error),
    onSettled: refreshHeroes
  });
  const heroExtend = useMutation({
    mutationFn: () =>
      adminService.adminPickBanExtend(heroEncounterId as number, {
        kind: CHARACTER_PICK_BAN_KIND,
        seconds: EXTEND_SECONDS
      }),
    onError: (error) => notify.apiError(error),
    onSettled: refreshHeroes
  });

  const session = board?.session ?? null;
  const current = board?.current_pick ?? null;
  const lifecycle = (action: DraftLifecycleAction) => {
    if (session == null) return;
    draftMutations.lifecycle.mutate(
      { sessionId: session.id, action },
      {
        onSuccess: action === "cancel" ? () => notify.success(tDraft("cancelled")) : undefined,
        onError: (error) => notify.apiError(error)
      }
    );
  };
  const resolved = (board?.picks ?? []).some((pick) => pick.status === "completed" || pick.status === "autopicked");
  const draftPending = draftMutations.lifecycle.isPending;

  let items: ReactNode = null;
  if (phase === "draft" && session != null) {
    const live = session.status === "live";
    const paused = session.status === "paused";
    items = (
      <>
        {live ? (
          <DropdownMenuItem disabled={draftPending} onSelect={() => lifecycle("pause")}>
            {t("pause")}
          </DropdownMenuItem>
        ) : null}
        {paused ? (
          <DropdownMenuItem disabled={draftPending} onSelect={() => lifecycle("resume")}>
            {t("resume")}
          </DropdownMenuItem>
        ) : null}
        {live && current != null ? (
          <>
            <DropdownMenuItem
              disabled={draftMutations.autopick.isPending}
              onSelect={() =>
                draftMutations.autopick.mutate(
                  { pickId: current.id, version: current.version },
                  { onError: (error) => notify.apiError(error) }
                )
              }
            >
              {t("autopick")}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={draftMutations.extendClock.isPending}
              onSelect={() =>
                draftMutations.extendClock.mutate(
                  { pickId: current.id, version: current.version, seconds: EXTEND_SECONDS },
                  { onError: (error) => notify.apiError(error) }
                )
              }
            >
              {t("extend", { seconds: EXTEND_SECONDS })}
            </DropdownMenuItem>
          </>
        ) : null}
        {live || paused ? (
          <DropdownMenuItem disabled={draftPending || !resolved} onSelect={() => lifecycle("rollback")}>
            {t("rollback")}
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => setConfirm("cancelDraft")}>
          {tDraft("cancelDraft")}
        </DropdownMenuItem>
      </>
    );
  } else if (phase === "pregame") {
    const paused = heroState?.session?.paused_at != null;
    const open = heroState?.session?.status === "active" && heroState.is_complete !== true;
    items = (
      <>
        {open && heroEncounterId != null ? (
          <>
            <DropdownMenuItem disabled={heroPause.isPending} onSelect={() => heroPause.mutate(!paused)}>
              {paused ? t("resume") : t("pause")}
            </DropdownMenuItem>
            <DropdownMenuItem disabled={heroExtend.isPending} onSelect={() => heroExtend.mutate()}>
              {t("extend", { seconds: EXTEND_SECONDS })}
            </DropdownMenuItem>
          </>
        ) : null}
        <DropdownMenuCheckboxItem checked={adminOpen} onCheckedChange={(checked) => onAdminOpenChange(checked === true)}>
          {t("banControls")}
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => setConfirm("cancelMatch")}>
          {tRoom("cancelMatch")}
        </DropdownMenuItem>
      </>
    );
  } else if (phase === "live") {
    items = (
      <DropdownMenuItem variant="destructive" onSelect={() => setConfirm("cancelMatch")}>
        {tRoom("cancelMatch")}
      </DropdownMenuItem>
    );
  }

  if (items == null) return null;
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" size="sm" aria-label={t("menu")}>
            <MoreHorizontal aria-hidden="true" />
            {t("title")}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">{items}</DropdownMenuContent>
      </DropdownMenu>
      <ConfirmDialog
        open={confirm != null}
        onOpenChange={(open) => !open && setConfirm(null)}
        intent={
          confirm === "cancelDraft"
            ? {
                title: tDraft("cancelTitle"),
                description: tDraft("cancelDescription"),
                confirmLabel: tDraft("cancelConfirm"),
                tone: "danger"
              }
            : {
                title: tRoom("cancelTitle"),
                description: tRoom("cancelDescription"),
                confirmLabel: tRoom("cancelConfirm"),
                tone: "danger"
              }
        }
        pending={confirm === "cancelDraft" ? draftPending : cancellingMatch}
        onConfirm={() => {
          const kind = confirm;
          setConfirm(null);
          if (kind === "cancelDraft") lifecycle("cancel");
          else if (kind === "cancelMatch") onCancelMatch();
        }}
      />
    </>
  );
}
