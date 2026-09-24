"use client";

import { Check, Undo2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import pickBanService from "@/services/pickBan.service";
import type { PickBanKind, PickBanUndo } from "@/types/tournament.types";
import { Spinner } from "@/components/ui/spinner";

import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";
import type { PickBanSide } from "./pick-ban-model";

interface PickBanUndoControlProps {
  kind: PickBanKind;
  encounterId: number;
  /** `state.undo`. Absent or with no `item_ids` renders nothing. */
  undo: PickBanUndo | undefined;
  /** Null for anyone who captains neither side — they read, they never consent. */
  viewerSide: PickBanSide | null;
  itemsById: Record<number, PickBanItemLike | undefined>;
  /** Resolves a side to its team name, for the "who asked" copy. */
  sideName: (side: PickBanSide) => string;
  /** Query keys to refetch once the consent (or the undo itself) lands. */
  invalidateKeys: unknown[][];
  className?: string;
}

/**
 * Take the last action back, by agreement.
 *
 * A misclicked ban used to cost the whole round: the only remedy was an
 * organizer resetting the session. This is the captains' own, surgical
 * alternative — and deliberately a two-sided one, because the last action is
 * information the opponent has already played around. One side asks, the other
 * agrees, the backend reverts exactly that action (and the `decider` it may have
 * triggered) and reopens the step.
 *
 * Four states, all driven by the server's `undo` block rather than local state,
 * so both captains' screens agree without either holding a pending flag:
 * nothing to undo (renders nothing), free to ask, waiting on the opponent, and
 * asked by the opponent. A spectator sees the pending line without the buttons —
 * the room is watchable, and a request being open explains why nobody is acting.
 */
export function PickBanUndoControl({
  kind,
  encounterId,
  undo,
  viewerSide,
  itemsById,
  sideName,
  invalidateKeys,
  className
}: Readonly<PickBanUndoControlProps>) {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (consent: boolean) => pickBanService.undoLastAction(kind, encounterId, consent),
    onError: (error) => notify.apiError(error, { title: t("undo.failed") }),
    onSettled: () => {
      for (const key of invalidateKeys) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    }
  });

  if (undo == null || undo.item_ids.length === 0) {
    return null;
  }

  const requestedBy = undo.requested_by;
  const mine = requestedBy != null && requestedBy === viewerSide;
  const theirs = requestedBy != null && requestedBy !== viewerSide;
  const opponent: PickBanSide = viewerSide === "away" ? "home" : "away";
  const pending = mutation.isPending;

  const line = theirs
    ? t("undo.asked", { team: sideName(requestedBy as PickBanSide) })
    : mine
      ? t("undo.waiting", { team: sideName(opponent) })
      : t("undo.label");

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center sm:gap-3",
        requestedBy != null
          ? "border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-amber)]/8"
          : "border-dashed border-[color:var(--aqt-border-2)]",
        className
      )}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <Undo2
          aria-hidden
          className={cn(
            "h-4 w-4 shrink-0",
            requestedBy != null
              ? "text-[color:var(--aqt-amber)]"
              : "text-[color:var(--aqt-fg-faint)]"
          )}
        />
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium leading-tight">{line}</span>
          {/* What exactly goes back — more than one item when a decider rode
              along, which is the case a captain would otherwise not expect. */}
          <span className="flex min-w-0 flex-wrap items-center gap-1.5">
            {undo.item_ids.map((itemId) => {
              const name = itemsById[itemId]?.name ?? t(`${kind}.itemNumber`, { id: itemId });
              return (
                <span key={itemId} className="flex min-w-0 items-center gap-1">
                  <PickBanItemThumb kind={kind} item={itemsById[itemId]} name={name} size={20} />
                  <span className="min-w-0 truncate text-xs text-[color:var(--aqt-fg-muted)]">
                    {name}
                  </span>
                </span>
              );
            })}
          </span>
        </div>
      </div>

      {viewerSide != null ? (
        <div className="flex shrink-0 items-center gap-2 sm:ml-auto">
          {theirs ? (
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={pending}
                onClick={() => mutation.mutate(false)}
              >
                <X className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                {t("undo.decline")}
              </Button>
              <Button size="sm" disabled={pending} onClick={() => mutation.mutate(true)}>
                {pending ? (
                  <Spinner className="mr-1.5 size-3.5" />
                ) : (
                  <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                )}
                {t("undo.agree")}
              </Button>
            </>
          ) : mine ? (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => mutation.mutate(false)}
            >
              {t("undo.withdraw")}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => mutation.mutate(true)}
            >
              {pending ? (
                <Spinner className="mr-1.5 size-3.5" />
              ) : (
                <Undo2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              )}
              {t("undo.ask")}
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
}
