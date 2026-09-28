"use client";

import { Ban, EyeOff, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { OverlayBar } from "@/components/ui/overlay-bar";
import type { PickBanAction, PickBanKind, PickBanState } from "@/types/tournament.types";
import { Spinner } from "@/components/ui/spinner";

import { stepDeadlineMs, stepSummary, type PickBanSide } from "./pick-ban-model";
import { PickBanCountdown } from "./PickBanCountdown";
import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";

interface PickBanCommandBarProps {
  state: PickBanState;
  sideName: (side: PickBanSide) => string;
  /**
   * The viewer's own pending action on an OPEN step, or null — on a blind step
   * nothing is confirmed here (the draft tray owns that), and a spectator never
   * has one.
   */
  captainAction: PickBanAction | null;
  kind: PickBanKind;
  selectedItemId: number | null;
  selectedItemName: string | null;
  /** Catalog entry behind `selectedItemId` — the confirmation shows its art, not just its name. */
  selectedItem: PickBanItemLike | undefined;
  pending: boolean;
  onConfirm: (itemId: number) => void;
  onCancel: () => void;
}

/**
 * Fixed bottom overlay for the pregame room, anchored via the shared
 * `OverlayBar` shell. Always shows the step/countdown status (every viewer),
 * and additionally the ban/pick/protect confirmation when the viewer is a
 * captain on an OPEN step.
 *
 * "Whose turn" is no longer one side: a v2 step can put BOTH captains on the
 * clock at once, and `acting_sides` is exactly the ones that have not locked —
 * so the banner shrinks from "both teams" to "waiting for X" on its own as the
 * first side finishes.
 */
export function PickBanCommandBar({
  state,
  sideName,
  captainAction,
  kind,
  selectedItemId,
  selectedItemName,
  selectedItem,
  pending,
  onConfirm,
  onCancel
}: Readonly<PickBanCommandBarProps>) {
  const t = useTranslations("pickBan.room");
  const deadline = stepDeadlineMs(state);
  const step = state.current_step;
  const summary = step != null ? stepSummary(step) : null;
  const acting = state.acting_sides;

  const turnBanner = state.is_complete
    ? t("completedBanner")
    : summary == null
      ? null
      : summary.system
        ? t("deciderResolving")
        : acting.length === 0
          ? t("turnRevealing")
          : acting.length > 1
            ? t("turnBoth", { action: t(`action.${summary.action}`) })
            : t("turn", {
                side: sideName(acting[0]),
                action: t(`action.${summary.action}`)
              });

  const confirmLabel =
    captainAction === "ban"
      ? t("captain.confirmBan", { item: selectedItemName ?? "—" })
      : captainAction === "protect"
        ? t("captain.confirmProtect", { item: selectedItemName ?? "—" })
        : t("captain.confirmPick", { item: selectedItemName ?? "—" });

  return (
    <OverlayBar tone={captainAction != null ? "active" : "neutral"} ariaLabel={t("commandBar")}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:contents">
          {deadline != null && step?.timer_seconds != null ? (
            <PickBanCountdown deadline={deadline} totalSeconds={step.timer_seconds} />
          ) : null}
          <div className="min-w-0 flex-1">
            <p className="text-label uppercase tracking-[0.15em] text-[color:var(--aqt-teal)]">
              {captainAction != null ? t("captain.yourTurn") : "\u00A0"}
            </p>
            <p className="flex min-w-0 items-center gap-1.5 truncate text-sm font-medium">
              {summary?.blind && !state.is_complete ? (
                <EyeOff className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden />
              ) : null}
              {turnBanner ?? "\u00A0"}
            </p>
          </div>
        </div>
        {captainAction != null ? (
          <div className="flex items-center gap-2 sm:ml-auto sm:shrink-0">
            {/* The art of what is about to be banned/picked, next to its name:
                the pool tile the captain clicked is often scrolled out of view
                by the time they reach this bar. */}
            <span className="flex min-w-0 items-center gap-2 text-sm text-[color:var(--aqt-fg-muted)]">
              {selectedItemName != null ? (
                <PickBanItemThumb
                  kind={kind}
                  item={selectedItem}
                  name={selectedItemName}
                  size={26}
                />
              ) : null}
              <span className="hidden min-w-0 truncate sm:inline">
                {selectedItemName ?? t("captain.selectHint")}
              </span>
            </span>
            {selectedItemId != null ? (
              <Button size="sm" variant="ghost" disabled={pending} onClick={onCancel}>
                {t("captain.cancel")}
              </Button>
            ) : null}
            <Button
              size="sm"
              className="min-h-11 flex-1 sm:flex-initial"
              variant={captainAction === "ban" ? "destructive" : "default"}
              disabled={selectedItemId == null || pending}
              onClick={() => {
                if (selectedItemId != null) onConfirm(selectedItemId);
              }}
            >
              {captainAction === "ban" ? <Ban className="mr-2 h-4 w-4" aria-hidden /> : null}
              {captainAction === "protect" ? <Shield className="mr-2 h-4 w-4" aria-hidden /> : null}
              {pending ? <Spinner className="mr-2" /> : null}
              {pending ? t("captain.sending") : confirmLabel}
            </Button>
          </div>
        ) : null}
      </div>
    </OverlayBar>
  );
}
