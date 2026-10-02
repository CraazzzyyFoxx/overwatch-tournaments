"use client";

import { Lock, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type {
  PickBanKind,
  PickBanResolvedStep,
  PickBanStepProgress,
  PickBanSubmissionItem
} from "@/types/tournament.types";

import type { PickBanSide } from "./pick-ban-model";
import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";

/**
 * The stable codes the engine reports in `draft_issues`. Anything outside this
 * list is printed as it arrived — a new engine rule must never leave a captain
 * with a Lock button that refuses and says nothing.
 */
const DRAFT_ISSUE_CODES = [
  "too_many_items",
  "duplicate_item",
  "item_not_available",
  "item_not_eligible",
  "item_not_in_pool",
  "target_required",
  "target_unknown",
  "target_not_allowed",
  "one_per_target",
  "max_per_group",
  "not_enough_items",
  "min_per_group"
] as const;

function isDraftIssueCode(issue: string): issue is (typeof DRAFT_ISSUE_CODES)[number] {
  return (DRAFT_ISSUE_CODES as readonly string[]).includes(issue);
}

/**
 * The viewer's own draft on a BLIND step, and what the opponent's looks like
 * from outside — rendered INSIDE the command bar, where an open step's
 * confirmation sits, so the commit control never scrolls away from the pool.
 *
 * A blind step is not a turn: both captains fill a private draft and lock it,
 * and only then does either see the other's. So the tray is the whole
 * affordance — it is where the chosen items live until Lock, where a removal
 * happens, and where the server's reasons for refusing the lock
 * (`draft_issues`) are shown instead of being discovered by pressing a button
 * that 400s. The opponent's side carries a COUNT and a locked mark, never an
 * item: that privacy is enforced server-side and mirrored here.
 *
 * Bar-sized on purpose: items are thumbnails (the name lives in the art's
 * title and the remove button's label) and the empty slots show what is left,
 * so a five-item draft fits beside the timer instead of growing the bar.
 */
export function PickBanDraftTray({
  kind,
  step,
  items,
  locked,
  issues,
  locking,
  itemsById,
  targetName,
  opponentSide,
  opponentProgress,
  opponentName,
  onRemove,
  onLock
}: Readonly<{
  kind: PickBanKind;
  step: PickBanResolvedStep;
  /** The viewer's draft, in submission order. */
  items: PickBanSubmissionItem[];
  /** True once the viewer locked: the tray freezes and waits. */
  locked: boolean;
  /** Server-side reasons the draft cannot be locked yet; empty = lockable. */
  issues: string[];
  /** A save or the lock is in flight. */
  locking: boolean;
  itemsById: Record<number, PickBanItemLike | undefined>;
  /** Roster name behind a target id, for a per-player step. */
  targetName: (playerId: number) => string | null;
  opponentSide: PickBanSide | null;
  opponentProgress: PickBanStepProgress | undefined;
  opponentName: string;
  onRemove: (index: number) => void;
  onLock: () => void;
}>) {
  const t = useTranslations("pickBan.room");
  const lockable = !locked && issues.length === 0 && items.length >= step.min;
  const emptySlots = Math.max(0, step.count - items.length);
  // Same box the thumb draws: heroes are circles, maps 4:3 stills.
  const slotShape = kind === "hero" ? "w-[30px] rounded-full" : "w-10 rounded-md";

  return (
    <div data-pick-ban-draft className="flex min-w-0 flex-col gap-1.5 sm:items-end">
      <div className="flex min-w-0 flex-wrap items-center gap-2 sm:flex-nowrap sm:gap-3">
        {opponentSide != null ? (
          <span
            data-opponent-progress={opponentProgress?.filled ?? 0}
            className={cn(
              "whitespace-nowrap text-xs",
              opponentProgress?.locked
                ? "text-[color:var(--aqt-support)]"
                : "text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {opponentProgress?.locked
              ? t("draft.opponentLocked", { team: opponentName })
              : t("draft.opponentFilled", {
                  team: opponentName,
                  filled: opponentProgress?.filled ?? 0,
                  count: step.count
                })}
          </span>
        ) : null}

        <ul aria-label={t("draft.title")} className="flex flex-wrap items-center gap-1.5">
          {items.map((item, index) => {
            const name = itemsById[item.item_id]?.name ?? t(`${kind}.itemNumber`, { id: item.item_id });
            const forPlayer =
              item.target_player_id != null ? targetName(item.target_player_id) : null;
            const label =
              forPlayer != null ? `${name} ${t("draft.forPlayer", { player: forPlayer })}` : name;
            const thumb = (
              <PickBanItemThumb kind={kind} item={itemsById[item.item_id]} name={name} size={30} />
            );
            return (
              <li key={`${item.item_id}-${index}`} data-draft-item={item.item_id} className="flex">
                {locked ? (
                  thumb
                ) : (
                  <button
                    type="button"
                    aria-label={t("draft.remove", { item: label })}
                    onClick={() => onRemove(index)}
                    className={cn(
                      "group relative flex outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                      kind === "hero" ? "rounded-full" : "rounded-md"
                    )}
                  >
                    {thumb}
                    <span
                      aria-hidden
                      className="absolute -right-1 -top-1 grid h-4 w-4 place-items-center rounded-full bg-[color:var(--aqt-card)] text-[color:var(--aqt-fg-faint)] ring-1 ring-[color:var(--aqt-border-2)] group-hover:text-[color:var(--aqt-rose)] group-focus-visible:text-[color:var(--aqt-rose)]"
                    >
                      <X className="h-3 w-3" />
                    </span>
                  </button>
                )}
              </li>
            );
          })}
          {Array.from({ length: emptySlots }, (_, index) => (
            <li
              key={`empty-${index}`}
              aria-hidden
              className={cn(
                "h-[30px] shrink-0 border border-dashed border-[color:var(--aqt-border-2)]",
                slotShape
              )}
            />
          ))}
        </ul>

        {locked ? (
          <span className="flex items-center gap-1.5 whitespace-nowrap text-sm font-medium text-[color:var(--aqt-support)]">
            <Lock className="h-3.5 w-3.5" aria-hidden />
            {t("draft.lockedWaiting", { team: opponentName })}
          </span>
        ) : (
          <Button
            size="sm"
            className="min-h-11 flex-1 sm:flex-initial"
            disabled={!lockable || locking}
            onClick={onLock}
          >
            {locking ? <Spinner className="mr-2" /> : <Lock className="mr-2 h-4 w-4" aria-hidden />}
            {t("draft.lock")}
          </Button>
        )}
      </div>

      {issues.length > 0 && !locked ? (
        <ul data-draft-issues className="flex flex-col gap-0.5 sm:items-end">
          {issues.map((issue) => (
            <li key={issue} className="text-xs text-[color:var(--aqt-amber)]">
              {isDraftIssueCode(issue) ? t(`draftIssue.${issue}`) : issue}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
