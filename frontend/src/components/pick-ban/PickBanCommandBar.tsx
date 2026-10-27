"use client";

import { type ReactNode } from "react";
import { Ban, EyeOff, PauseCircle, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { OverlayBar } from "@/components/ui/overlay-bar";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { PickBanAction, PickBanKind, PickBanState } from "@/types/tournament.types";

import { memberName, stepDeadlineMs, stepSummary } from "./pick-ban-model";
import { PickBanCountdown } from "./PickBanCountdown";
import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";

interface PickBanCommandBarProps {
  state: PickBanState;
  teamName: (teamId: number) => string;
  /**
   * The viewer's own pending action on an OPEN step, or null — on a blind step
   * nothing is confirmed here (`draft` takes this slot), and a spectator never
   * has one.
   */
  captainAction: PickBanAction | null;
  /** The viewer's blind-step draft tray, shown where the confirmation goes. */
  draft?: ReactNode;
  /** The viewer still has to fill/lock that draft — the bar reads "your turn". */
  draftOpen?: boolean;
  kind: PickBanKind;
  /** The catalog item's id — or, on a `side_pick` step, the chosen side's index (0 is a choice). */
  selectedItemId: number | null;
  /** The item's name, or the chosen side's label. */
  selectedItemName: string | null;
  /** Catalog entry behind `selectedItemId` — the confirmation shows its art, not just its name. A side has none. */
  selectedItem: PickBanItemLike | undefined;
  pending: boolean;
  /** The player a member pick is made for; null on a team step. */
  forMember?: string | null;
  /** Why the viewer has nothing to confirm yet (tap a player first; the captains pick), where the confirm goes. */
  hint?: string | null;
  onConfirm: (itemId: number) => void;
  onCancel: () => void;
}

/**
 * Fixed bottom overlay for the pregame room, anchored via the shared
 * `OverlayBar` shell. Always shows the step/countdown status (every viewer),
 * and additionally the viewer's own commit control: the ban/pick/protect
 * confirmation on an OPEN step, the draft tray and its Lock on a BLIND one.
 *
 * "Whose turn" is no longer one side: a v2 step can put BOTH captains on the
 * clock at once, and `acting_sides` is exactly the ones that have not locked —
 * so the banner shrinks from "both teams" to "waiting for X" on its own as the
 * first side finishes.
 */
export function PickBanCommandBar({
  state,
  teamName,
  captainAction,
  draft,
  draftOpen = false,
  kind,
  selectedItemId,
  selectedItemName,
  selectedItem,
  pending,
  forMember = null,
  hint = null,
  onConfirm,
  onCancel
}: Readonly<PickBanCommandBarProps>) {
  const t = useTranslations("pickBan.room");
  const deadline = stepDeadlineMs(state);
  const step = state.current_step;
  const summary = step != null ? stepSummary(step) : null;
  const acting = state.acting_team_ids;
  const paused = state.session?.paused_at != null;
  const yourTurn = !paused && (captainAction != null || draftOpen);

  // A member step is a list of players, not one team: say who still picks. A free-order pick is the team's turn, for
  // whichever of them it names.
  const pickers =
    step?.member != null && step.member !== "any"
      ? state.acting_member_ids.map((id) => memberName(state.members, id))
      : [];
  // The pause outranks whose turn it is: nobody may act until an organizer
  // lifts it, and the bar is the one surface every viewer of the room sees.
  const turnBanner = paused
    ? t("pausedBanner")
    : state.is_complete
      ? t("completedBanner")
      : summary == null
        ? null
        : summary.system
          ? t("deciderResolving")
          : pickers.length > 0
            ? t("turnMembers", { names: pickers.join(", ") })
            : acting.length === 0
              ? t("turnRevealing")
              : acting.length > 1
                ? t("turnBoth", { action: t(`action.${summary.action}`) })
                : t("turn", {
                    team: teamName(acting[0]),
                    action: t(`action.${summary.action}`)
                  });

  const confirmLabel =
    captainAction === "pick" && forMember != null
      ? t("captain.confirmPickFor", { item: selectedItemName ?? "—", member: forMember })
      : captainAction === "ban"
        ? t("captain.confirmBan", { item: selectedItemName ?? "—" })
        : captainAction === "protect"
          ? t("captain.confirmProtect", { item: selectedItemName ?? "—" })
          : captainAction === "side_pick"
            ? t("captain.confirmSide", { side: selectedItemName ?? "—" })
            : t("captain.confirmPick", { item: selectedItemName ?? "—" });
  const sidePick = captainAction === "side_pick";

  return (
    <OverlayBar tone={yourTurn ? "accent" : "neutral"} ariaLabel={t("commandBar")}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:contents">
          {deadline != null && step?.timer_seconds != null ? (
            <PickBanCountdown deadline={deadline} totalSeconds={step.timer_seconds} />
          ) : null}
          <div className="min-w-0 flex-1">
            <p className={cn(eyebrowClass(), "text-[color:var(--aqt-teal)]")}>
              {yourTurn ? t("captain.yourTurn") : "\u00A0"}
            </p>
            <p className="flex min-w-0 items-center gap-1.5 truncate text-sm font-medium">
              {paused ? (
                <PauseCircle
                  className="h-4 w-4 shrink-0 text-[color:var(--aqt-amber)]"
                  aria-hidden
                />
              ) : null}
              {summary?.blind && !state.is_complete && !paused ? (
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
              {selectedItemName != null && !sidePick ? (
                <PickBanItemThumb
                  kind={kind}
                  item={selectedItem}
                  name={selectedItemName}
                  size={26}
                />
              ) : null}
              <span className="hidden min-w-0 truncate sm:inline">
                {selectedItemName ?? t(sidePick ? "captain.chooseSideHint" : "captain.selectHint")}
              </span>
            </span>
            {selectedItemId != null ? (
              <Button size="sm" variant="ghost" disabled={pending} onClick={onCancel}>
                {t("captain.cancel")}
              </Button>
            ) : null}
            <Button
              size="sm"
              className="min-h-11 min-w-0 flex-1 sm:flex-initial"
              variant={captainAction === "ban" ? "destructive" : "default"}
              disabled={selectedItemId == null || pending}
              onClick={() => {
                if (selectedItemId != null) onConfirm(selectedItemId);
              }}
            >
              {captainAction === "ban" ? <Ban className="mr-2 h-4 w-4" aria-hidden /> : null}
              {captainAction === "protect" ? <Shield className="mr-2 h-4 w-4" aria-hidden /> : null}
              {pending ? <Spinner className="mr-2" /> : null}
              {/* Truncated, not overflowing the phone's bar: a hero and a player name can be long. */}
              <span className="min-w-0 truncate">{pending ? t("captain.sending") : confirmLabel}</span>
            </Button>
          </div>
        ) : draft != null ? (
          <div className="sm:ml-auto sm:shrink-0">{draft}</div>
        ) : hint != null ? (
          <p className="text-caption text-[color:var(--aqt-fg-muted)] sm:ml-auto sm:shrink-0">{hint}</p>
        ) : null}
      </div>
    </OverlayBar>
  );
}
