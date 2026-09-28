"use client";

import { EyeOff, Lock, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
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
 * from outside.
 *
 * A blind step is not a turn: both captains fill a private draft and lock it,
 * and only then does either see the other's. So the tray is the whole
 * affordance — it is where the chosen items live until Lock, where a removal
 * happens, and where the server's reasons for refusing the lock
 * (`draft_issues`) are shown instead of being discovered by pressing a button
 * that 400s. The opponent's column carries a COUNT and a locked mark, never an
 * item: that privacy is enforced server-side and mirrored here.
 */
export function PickBanDraftTray({
  kind,
  step,
  items,
  locked,
  issues,
  saving,
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
  /** A debounced auto-save is in flight. */
  saving: boolean;
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

  return (
    <section
      data-pick-ban-draft
      className="flex flex-col gap-2.5 rounded-xl border border-[color:var(--aqt-teal)]/40 bg-[color:var(--aqt-card-2)]/50 p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <EyeOff className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden />
        <span className="text-sm font-semibold">{t("draft.title")}</span>
        <Badge variant="outline" className="px-1.5 py-0 text-label font-normal tabular-nums">
          {t("draft.filled", { filled: items.length, count: step.count })}
        </Badge>
        {saving ? (
          <span className="text-xs text-[color:var(--aqt-fg-faint)]">{t("draft.saving")}</span>
        ) : null}
      </div>

      {items.length === 0 ? (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("draft.empty")}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {items.map((item, index) => {
            const name = itemsById[item.item_id]?.name ?? t(`${kind}.itemNumber`, { id: item.item_id });
            const forPlayer =
              item.target_player_id != null ? targetName(item.target_player_id) : null;
            return (
              <li
                key={`${item.item_id}-${index}`}
                data-draft-item={item.item_id}
                className="flex min-w-0 items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-1 pl-1 pr-1.5"
              >
                <PickBanItemThumb kind={kind} item={itemsById[item.item_id]} name={name} size={22} />
                <span className="min-w-0 truncate text-xs font-medium">{name}</span>
                {forPlayer != null ? (
                  <span className="min-w-0 truncate text-xs text-[color:var(--aqt-fg-muted)]">
                    {t("draft.forPlayer", { player: forPlayer })}
                  </span>
                ) : null}
                {!locked ? (
                  <button
                    type="button"
                    aria-label={t("draft.remove", { item: name })}
                    onClick={() => onRemove(index)}
                    className="rounded p-0.5 text-[color:var(--aqt-fg-faint)] outline-none hover:text-[color:var(--aqt-rose)] focus-visible:text-[color:var(--aqt-rose)]"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {issues.length > 0 && !locked ? (
        <ul data-draft-issues className="flex flex-col gap-0.5">
          {issues.map((issue) => (
            <li key={issue} className="text-xs text-[color:var(--aqt-amber)]">
              {isDraftIssueCode(issue) ? t(`draftIssue.${issue}`) : issue}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {locked ? (
          <span className="flex items-center gap-1.5 text-sm font-medium text-[color:var(--aqt-support)]">
            <Lock className="h-3.5 w-3.5" aria-hidden />
            {t("draft.lockedWaiting", { team: opponentName })}
          </span>
        ) : (
          <Button size="sm" disabled={!lockable || locking} onClick={onLock}>
            {locking ? <Spinner className="mr-2" /> : <Lock className="mr-2 h-4 w-4" aria-hidden />}
            {t("draft.lock")}
          </Button>
        )}
        {opponentSide != null ? (
          <span
            data-opponent-progress={opponentProgress?.filled ?? 0}
            className={cn(
              "ml-auto text-xs",
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
      </div>
    </section>
  );
}
