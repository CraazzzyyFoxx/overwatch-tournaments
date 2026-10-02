"use client";

import {
  Ban,
  Check,
  CircleDashed,
  EyeOff,
  Flag,
  Info,
  Layers,
  MapPin,
  Shield,
  Shuffle,
  Users
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type {
  PickBanKind,
  PickBanResolvedStep,
  PickBanSession,
  PickBanSubmission
} from "@/types/tournament.types";

import {
  stepRoundGroups,
  stepSubmissions,
  stepSummary,
  type PickBanSide,
  type PickBanStepSummary
} from "./pick-ban-model";
import { PickBanRoundLabel, type PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";

interface PickBanStepTimelineProps {
  kind: PickBanKind;
  /** The session's resolved steps, in index order. */
  sequence: PickBanResolvedStep[];
  /** Visible submissions — what a finished step actually took. */
  submissions: PickBanSubmission[];
  currentStepIndex: number | null;
  isComplete: boolean;
  /**
   * The server's `current_round`. Null for a flat sequence, a completed one
   * and the unavailable state alike, so round mode is read off the steps'
   * own `round` instead.
   */
  currentRound: number | null;
  itemsById: Record<number, PickBanItemLike | undefined>;
  sideName: (side: PickBanSide) => string;
  /** Drives the "who goes first" line under the Steps title. */
  session: PickBanSession;
}

export function PickBanStepTimeline({
  kind,
  sequence,
  submissions,
  currentStepIndex,
  isComplete,
  currentRound,
  itemsById,
  sideName,
  session
}: Readonly<PickBanStepTimelineProps>) {
  const t = useTranslations("pickBan.room");
  // The grid groups by round whenever the pool carries rounds, and the two
  // stack in one viewport, so the timeline groups on exactly the same
  // condition — a flat timeline beside a grouped grid repeats one headline
  // two to five times with nothing to say which round each one closes.
  const stepGroups = stepRoundGroups(sequence);

  const renderStep = (resolved: PickBanResolvedStep) => {
    const summary = stepSummary(resolved);
    const current = !isComplete && currentStepIndex === resolved.index;
    const done = isComplete || (currentStepIndex != null && resolved.index < currentStepIndex);
    // A blind step says nothing until it reveals; an open one is public as it
    // goes, which is exactly what `revealed`/non-blind submissions encode.
    const taken = stepSubmissions(submissions, resolved.index)
      .filter((submission) => submission.state === "revealed" || !resolved.blind)
      .flatMap((submission) => submission.items);
    // Who acts is a different sentence per shape, not a team name slotted into
    // one: "Both teams ban" / "{team} bans" / "Random ban".
    const shape = summary.system ? "system" : summary.sides.length > 1 ? "both" : "side";
    const headlineKey = `step.${shape}.${summary.action}` as const;

    const Icon = done
      ? Check
      : summary.system
        ? Shuffle
        : current
          ? MapPin
          : CircleDashed;

    return (
      <div
        key={resolved.index}
        data-pick-ban-step={resolved.index}
        aria-current={current ? "step" : undefined}
        className={cn(
          "flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border px-3 py-2 text-sm",
          current
            ? "border-[color:var(--aqt-teal)]/45 bg-[color:var(--aqt-teal)]/10"
            : "border-[color:var(--aqt-border)]",
          done ? "opacity-70" : null
        )}
      >
        <span className="w-5 shrink-0 text-right text-xs text-[color:var(--aqt-fg-faint)]">
          {resolved.index + 1}
        </span>
        <Icon
          aria-label={done ? t("steps.done") : current ? t("steps.current") : t("steps.pending")}
          className={cn(
            "h-4 w-4 shrink-0",
            done
              ? "text-[color:var(--aqt-support)]"
              : current
                ? "text-[color:var(--aqt-teal)]"
                : "text-[color:var(--aqt-fg-faint)]"
          )}
        />
        <span
          className={cn(
            "inline-flex items-center gap-1 font-medium",
            summary.action === "ban" ? "text-[color:var(--aqt-rose)]" : null,
            summary.action === "pick" ? "text-[color:var(--aqt-support)]" : null,
            summary.action === "protect" ? "text-[color:var(--aqt-amber)]" : null
          )}
        >
          {summary.action === "ban" ? <Ban className="h-3.5 w-3.5" aria-hidden /> : null}
          {summary.action === "protect" ? <Shield className="h-3.5 w-3.5" aria-hidden /> : null}
          {t(headlineKey, {
            team: summary.sides.length === 1 ? sideName(summary.sides[0]) : ""
          })}
          {summary.action === "decider" ? (
            <TooltipProvider delayDuration={150}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex text-[color:var(--aqt-fg-faint)] outline-none hover:text-[color:var(--aqt-teal)] focus-visible:text-[color:var(--aqt-teal)]"
                    aria-label={t("steps.deciderHint")}
                  >
                    <Info className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[16rem] text-xs">
                  {t("steps.deciderHint")}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : null}
        </span>
        <StepMeta summary={summary} />
        {taken.length > 0 ? (
          <span className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">
            {taken.map((item, position) => {
              const name =
                itemsById[item.item_id]?.name ?? t(`${kind}.itemNumber`, { id: item.item_id });
              return (
                <PickBanItemThumb
                  key={`${item.item_id}-${position}`}
                  kind={kind}
                  item={itemsById[item.item_id]}
                  name={name}
                  size={22}
                  muted={summary.action === "ban"}
                />
              );
            })}
          </span>
        ) : null}
      </div>
    );
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("steps.title")}</CardTitle>
        {session.first_side ? (
          <p className="flex items-center gap-2 text-sm text-[color:var(--aqt-fg-muted)]">
            <Flag className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden />
            <span>
              {t("firstBanner", { team: sideName(session.first_side) })}{" "}
              <span className="text-[color:var(--aqt-fg-dim)]">
                ({t(`seedSource.${session.seed_source}`)})
              </span>
            </span>
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5">
        {stepGroups === null
          ? sequence.map((resolved) => renderStep(resolved))
          : stepGroups.map((group) => {
              // Below `lg` a Bo5 round-mode sequence is a long run sitting
              // above five item groups, so everything but the live round folds
              // away there. When no round is live — a completed sequence —
              // there is nothing to fold to, so the whole run stays visible.
              const folded = currentRound != null && group.round !== currentRound;
              return (
                <div
                  key={group.round}
                  data-pick-ban-step-round={group.round}
                  className={cn("flex-col gap-1.5", folded ? "hidden lg:flex" : "flex")}
                >
                  <div className="pt-1.5">
                    <PickBanRoundLabel
                      round={group.round}
                      state={
                        group.round === currentRound
                          ? "current"
                          : currentRound != null && group.round < currentRound
                            ? "resolved"
                            : "upcoming"
                      }
                    />
                  </div>
                  {group.steps.map((resolved) => renderStep(resolved))}
                </div>
              );
            })}
      </CardContent>
    </Card>
  );
}

/**
 * The parameters that make a v2 step different from a v1 token: how many items
 * each side takes, whether it is blind, whether every item names an opponent
 * player, and how long its bans hold. Each one is omitted when it says nothing
 * — a count of 1 and a one-map ban are the default shape. Plain glyph-and-text
 * pairs, not chips: they qualify the headline beside them, they do not compete
 * with it.
 */
function StepMeta({ summary }: Readonly<{ summary: PickBanStepSummary }>) {
  const t = useTranslations("pickBan.room");
  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs text-[color:var(--aqt-fg-muted)]">
      {summary.count != null ? (
        <span className="font-semibold tabular-nums text-[color:var(--aqt-fg)]">
          {t("step.count", { n: summary.count })}
        </span>
      ) : null}
      {summary.blind ? (
        <span className="inline-flex items-center gap-1">
          <EyeOff className="h-3 w-3" aria-hidden />
          {t("step.blind")}
        </span>
      ) : null}
      {summary.targeted ? (
        <span className="inline-flex items-center gap-1">
          <Users className="h-3 w-3" aria-hidden />
          {t("step.targeted")}
        </span>
      ) : null}
      {summary.lifetime != null ? (
        <span className="inline-flex items-center gap-1">
          <Layers className="h-3 w-3" aria-hidden />
          {summary.lifetime === "series"
            ? t("step.lifetimeSeries")
            : t("step.lifetime", { n: summary.lifetime })}
        </span>
      ) : null}
    </span>
  );
}
