"use client";

import { useState } from "react";
import { Eye, Repeat2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type {
  PickBanDisputeState,
  PickBanKind,
  PickBanResolvedStep,
  PickBanSubmission
} from "@/types/tournament.types";

import { duplicateItemIds, type PickBanSide } from "./pick-ban-model";
import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";

const SIDE_ACCENT: Record<PickBanSide, string> = {
  home: "text-[color:var(--aqt-teal)]",
  away: "text-[color:var(--aqt-rose)]"
};

/**
 * What a blind step turned out to be, once both sides locked.
 *
 * Both columns are shown side by side because a blind step is the one place in
 * the room where a captain has never seen the opponent's choice before — and
 * because duplicates MERGE: when both sides ban the same hero the board holds
 * one banned entry, so without a "matched" mark one side appears to have spent
 * a ban that never shows up anywhere.
 *
 * The dispute button rides along: reopening is only ever about a step that has
 * just been revealed, and `dispute.available` is already the server's full
 * answer on whether this viewer may (enabled, attempts left, nothing played on
 * top of it).
 */
export function PickBanRevealPanel({
  kind,
  step,
  submissions,
  itemsById,
  sideName,
  targetName,
  dispute,
  disputing,
  onDispute
}: Readonly<{
  kind: PickBanKind;
  step: PickBanResolvedStep;
  /** The step's current-attempt submissions (`stepSubmissions`). */
  submissions: PickBanSubmission[];
  itemsById: Record<number, PickBanItemLike | undefined>;
  sideName: (side: PickBanSide) => string;
  targetName: (playerId: number) => string | null;
  dispute: PickBanDisputeState;
  disputing: boolean;
  onDispute: () => void;
}>) {
  const t = useTranslations("pickBan.room");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const duplicates = duplicateItemIds(submissions);
  const sides: PickBanSide[] = step.sides.filter(
    (side): side is PickBanSide => side !== "system"
  );
  const canDispute = dispute.available && dispute.step_index === step.index;

  return (
    <section
      data-pick-ban-reveal={step.index}
      className="flex flex-col gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40 p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Eye className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden />
        <span className="text-sm font-semibold">{t("reveal.title")}</span>
        {duplicates.size > 0 ? (
          <span className="text-xs text-[color:var(--aqt-amber)]">
            {t("reveal.matchedCount", { count: duplicates.size })}
          </span>
        ) : null}
        {canDispute ? (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={disputing}
            onClick={() => setConfirmOpen(true)}
          >
            {disputing ? (
              <Spinner className="mr-1.5 size-3.5" />
            ) : (
              <Repeat2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {t("dispute.button", { used: dispute.attempts_used, max: dispute.max })}
          </Button>
        ) : null}
      </div>

      <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2 sm:gap-3">
        {sides.map((side) => {
          const items =
            submissions.find((submission) => submission.side === side)?.items ?? [];
          return (
            <div
              key={side}
              data-reveal-side={side}
              className="flex flex-col gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]/60 p-2.5"
            >
              <span className={cn("text-xs font-semibold", SIDE_ACCENT[side])}>
                {sideName(side)}
              </span>
              {items.length === 0 ? (
                <span className="text-xs text-[color:var(--aqt-fg-faint)]">
                  {t("reveal.none")}
                </span>
              ) : (
                <ul className="flex flex-col gap-1">
                  {items.map((item, index) => {
                    const name =
                      itemsById[item.item_id]?.name ?? t(`${kind}.itemNumber`, { id: item.item_id });
                    const forPlayer =
                      item.target_player_id != null ? targetName(item.target_player_id) : null;
                    const matched = duplicates.has(item.item_id);
                    return (
                      <li
                        key={`${item.item_id}-${index}`}
                        data-reveal-item={item.item_id}
                        data-matched={matched ? "true" : undefined}
                        className="flex min-w-0 items-center gap-2"
                      >
                        <PickBanItemThumb
                          kind={kind}
                          item={itemsById[item.item_id]}
                          name={name}
                          size={24}
                          muted={step.action === "ban"}
                        />
                        <span className="min-w-0 truncate text-sm font-medium">{name}</span>
                        {forPlayer != null ? (
                          <span className="min-w-0 truncate text-xs text-[color:var(--aqt-fg-muted)]">
                            {t("draft.forPlayer", { player: forPlayer })}
                          </span>
                        ) : null}
                        {matched ? (
                          <span className="ml-auto shrink-0 text-xs text-[color:var(--aqt-amber)]">
                            {t("reveal.matched")}
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        intent={{
          title: t("dispute.confirmTitle"),
          description: t("dispute.confirmHint"),
          confirmLabel: t("dispute.confirmAction"),
          tone: "danger"
        }}
        pending={disputing}
        onConfirm={() => {
          setConfirmOpen(false);
          onDispute();
        }}
      />
    </section>
  );
}
