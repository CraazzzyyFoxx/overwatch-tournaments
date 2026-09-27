"use client";

import { AlertTriangle, ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  PICK_BAN_STEP_ACTIONS,
  PICK_BAN_STEP_SIDES,
  buildStepToken,
  parseStepToken,
  roundsPlayed,
  type PickBanDraft,
  type PickBanOrderMode,
  type PickBanStepAction,
  type PickBanStepSide,
  type SeriesLength
} from "@/lib/tournament/pick-ban-config";
import type { PickBanSequenceToken } from "@/types/tournament.types";

/** Step 2: the order the picks and bans are played in. */
export function SequenceStep({
  ids,
  draft,
  isHero,
  series,
  sequence,
  canManage,
  patch
}: Readonly<{
  ids: string;
  draft: PickBanDraft;
  isHero: boolean;
  series: SeriesLength;
  sequence: PickBanSequenceToken[];
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
}>) {
  const t = useTranslations("pickBan.admin");

  return (
    <>
      <div>
        <FieldTitle className="text-sm">{t("orderSection")}</FieldTitle>
        <FieldDescription>
          {isHero ? t("orderHeroHint") : t("orderSectionHint")}
        </FieldDescription>
      </div>

      {/* Slot mode resolves each round on its own; there is no series-wide
          order to author, and the custom preset is unstorable. */}
      {draft.mode === "slots" ? (
        <FieldDescription>{t("orderSlotsMode")}</FieldDescription>
      ) : (
        <>
          {/* A hero config has no bracket-generated option: its sequence is ONE
              round's steps, replayed per map of the series, while the generator
              answers the map question and emits picks and a decider a hero
              round cannot resolve. */}
          {isHero ? null : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor={`${ids}-order`}>{t("orderLabel")}</FieldLabel>
                <Select
                  value={draft.orderMode}
                  disabled={!canManage}
                  onValueChange={(value) =>
                    patch({
                      orderMode: value as PickBanOrderMode,
                      // Authoring starts from the generated order rather than
                      // an empty list, so "custom" is an edit, not a blank page.
                      sequence:
                        value === "custom" && draft.sequence.length === 0
                          ? sequence
                          : draft.sequence
                    })
                  }
                >
                  <SelectTrigger id={`${ids}-order`} aria-describedby={`${ids}-order-hint`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bracket">{t("orderBracket")}</SelectItem>
                    <SelectItem value="custom">{t("orderCustom")}</SelectItem>
                  </SelectContent>
                </Select>
                <FieldDescription id={`${ids}-order-hint`}>
                  {draft.orderMode === "bracket" ? t("orderBracketHint") : t("orderCustomHint")}
                </FieldDescription>
              </Field>
            </div>
          )}

          {/* The generated order is a function of the pool, so it says nothing
              until there is one — "0 rounds played" would read as a setting
              rather than a missing prerequisite. */}
          {draft.itemIds.length === 0 ? (
            <FieldDescription>{t("orderNeedsPool")}</FieldDescription>
          ) : (
            <div className="flex flex-col gap-2">
              <FieldTitle className="text-sm">
                {draft.orderMode === "bracket" ? t("orderPreview") : t("orderSteps")}
                {/* "Rounds played" counts picks and deciders — the maps a map
                    sequence settles. A hero round plays no map of its own. */}
                {isHero ? null : (
                  <Badge variant="secondary">
                    {t("orderRoundsPlayed", { count: roundsPlayed(sequence) })}
                  </Badge>
                )}
              </FieldTitle>

              {draft.orderMode === "bracket" ? (
                <>
                  <FieldDescription>
                    {t(`seriesSource.${series.source}`, { bestOf: series.bestOf })}
                  </FieldDescription>
                  <SequencePreview sequence={sequence} />
                </>
              ) : (
                <>
                  {/* A custom order runs as written, so the scope's series
                      length is only worth raising when the two disagree — and
                      only where the length is exact rather than a preview. */}
                  {!isHero &&
                  series.source === "round" &&
                  roundsPlayed(sequence) !== series.bestOf ? (
                    <Alert>
                      <AlertTriangle aria-hidden className="size-4" />
                      <AlertDescription>
                        {t("orderCustomMismatch", {
                          played: roundsPlayed(sequence),
                          expected: series.bestOf
                        })}
                      </AlertDescription>
                    </Alert>
                  ) : null}
                  <StepList
                    sequence={draft.sequence}
                    allowProtect={draft.allowProtect}
                    allowDecider={!isHero}
                    disabled={!canManage}
                    onChange={(next) => patch({ sequence: next })}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}

/** Read-only step chips: the generated order, or a preview of a custom one. */
function SequencePreview({ sequence }: Readonly<{ sequence: PickBanSequenceToken[] }>) {
  const t = useTranslations("pickBan.admin");
  if (sequence.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("sequenceEmpty")}</p>;
  }
  return (
    <ol className="flex flex-wrap gap-1.5">
      {sequence.map((token, index) => {
        const step = parseStepToken(token);
        return (
          <li
            key={`${token}-${index}`}
            className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs"
          >
            <span className="text-muted-foreground tabular-nums">{index + 1}</span>
            <span className="font-medium">
              {step.side == null
                ? t("action.decider")
                : `${t(`action.${step.action}`)} · ${t(`side.${step.side}`)}`}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The hand-authored step list. Reachable in pool mode with custom order only. */
function StepList({
  sequence,
  allowProtect,
  allowDecider,
  disabled,
  onChange
}: Readonly<{
  sequence: PickBanSequenceToken[];
  /** Gates the protect action: the engine ignores it without the toggle. */
  allowProtect: boolean;
  /** False for a hero sequence, whose pool has no survivor to decide on. */
  allowDecider: boolean;
  disabled: boolean;
  onChange: (next: PickBanSequenceToken[]) => void;
}>) {
  const t = useTranslations("pickBan.admin");

  const replace = (index: number, token: PickBanSequenceToken) => {
    const next = [...sequence];
    next[index] = token;
    onChange(next);
  };

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= sequence.length) return;
    const next = [...sequence];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const actions: (PickBanStepAction | "decider")[] = [
    ...PICK_BAN_STEP_ACTIONS.filter((action) => action !== "protect" || allowProtect),
    ...(allowDecider ? (["decider"] as const) : [])
  ];

  return (
    <div className="flex flex-col gap-2">
      {sequence.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("sequenceEmpty")}</p>
      ) : null}

      <ol className="flex flex-col gap-2">
        {sequence.map((token, index) => {
          const step = parseStepToken(token);
          const position = index + 1;
          return (
            <li key={index} className="flex flex-wrap items-center gap-2">
              <span className="w-14 shrink-0 text-xs text-muted-foreground tabular-nums">
                {t("stepNumber", { n: position })}
              </span>

              <Select
                value={step.action}
                disabled={disabled}
                onValueChange={(value) =>
                  replace(
                    index,
                    buildStepToken(value as PickBanStepAction | "decider", step.side ?? "first")
                  )
                }
              >
                <SelectTrigger className="w-36" aria-label={t("stepActionLabel", { n: position })}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {actions.map((action) => (
                    <SelectItem key={action} value={action}>
                      {t(`action.${action}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {step.side == null ? (
                <span className="text-xs text-muted-foreground">{t("deciderAuto")}</span>
              ) : (
                <Select
                  value={step.side}
                  disabled={disabled}
                  onValueChange={(value) =>
                    replace(index, buildStepToken(step.action, value as PickBanStepSide))
                  }
                >
                  <SelectTrigger className="w-36" aria-label={t("stepSideLabel", { n: position })}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PICK_BAN_STEP_SIDES.map((side) => (
                      <SelectItem key={side} value={side}>
                        {t(`side.${side}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}

              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={disabled || index === 0}
                  aria-label={t("stepMoveUp", { n: position })}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp aria-hidden className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={disabled || index === sequence.length - 1}
                  aria-label={t("stepMoveDown", { n: position })}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown aria-hidden className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={disabled}
                  aria-label={t("stepRemove", { n: position })}
                  onClick={() => onChange(sequence.filter((_, at) => at !== index))}
                >
                  <X aria-hidden className="size-4" />
                </Button>
              </div>
            </li>
          );
        })}
      </ol>

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        disabled={disabled}
        onClick={() => onChange([...sequence, "ban_first"])}
      >
        <Plus aria-hidden className="me-2 size-4" />
        {t("addStep")}
      </Button>
    </div>
  );
}
