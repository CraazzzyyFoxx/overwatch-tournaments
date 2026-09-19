"use client";

import Link from "next/link";
import { useId } from "react";
import { ArrowUpRight, ChevronDown, Clock3 } from "lucide-react";
import { useTranslations } from "next-intl";

import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import FlexIcon from "@/components/icons/FlexIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TONE_CLASS } from "@/components/kit/tone";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftAutopickStrategy, DraftFormat } from "@/types/draft.types";
import { isRoleSlotCode, orderSlotCodes, type RosterShape } from "@/lib/roster-shape";

import { DRAFT_ROUND_RULES, MAX_DRAFT_TEAM_COUNT, MIN_DRAFT_TEAM_COUNT } from "./setup-model";
import type { DraftSetupConfig } from "./setup-types";

interface DraftConfigStepProps {
  value: DraftSetupConfig;
  onChange: (next: DraftSetupConfig) => void;
  /** Resolved on the server from the tournament; never editable here (T14 owns it). */
  rosterShape: RosterShape;
  tournamentId: number;
  locked?: boolean;
}

const PICK_TIME_PRESETS = [30, 45, 60, 90];
const FORMATS: DraftFormat[] = ["snake", "linear", "custom"];

export function DraftConfigStep({
  value,
  onChange,
  rosterShape,
  tournamentId,
  locked = false
}: Readonly<DraftConfigStepProps>) {
  const t = useTranslations("draftAdmin");
  // Straight off the server shape: deriving rounds from a size here is exactly
  // the mirror this feature removes.
  const rounds = rosterShape.draft_rounds;
  const pickTimeLabelId = useId();
  const formatLabelId = useId();
  const roundRulesLabelId = useId();

  const patch = (next: Partial<DraftSetupConfig>) => onChange({ ...value, ...next });

  return (
    <div className="space-y-6">
      {locked && (
        <div className={cn("rounded-xl border px-4 py-3 text-sm", TONE_CLASS.warning)}>
          {t("configLocked")}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label>{t("teamSize")}</Label>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm tabular-nums">
            <span className="font-semibold">{rosterShape.team_size}</span>
            {orderSlotCodes(rosterShape.slots).map((code) => {
              const label = isRoleSlotCode(code) ? t(`roles.${code}`) : t("roles.flex");
              return (
                <span
                  key={code}
                  className="inline-flex items-center gap-1 text-muted-foreground"
                  title={label}
                >
                  {isRoleSlotCode(code) ? (
                    <PlayerRoleIcon
                      role={getRoleIconName(code)}
                      size={16}
                      color={ROLE_ACCENT[code]}
                      decorative
                    />
                  ) : (
                    <FlexIcon width={16} height={16} />
                  )}
                  <span className="sr-only">{label}</span>×{rosterShape.slots[code]}
                </span>
              );
            })}
          </p>
          <p className="text-xs tabular-nums text-muted-foreground">
            {t("roundsDerived", { rounds })}
          </p>
          <p className="text-xs text-muted-foreground">{t("rosterShapeHint")}</p>
          <Link
            href={`/admin/tournaments/${tournamentId}/settings/general`}
            className="inline-flex items-center text-xs font-medium text-primary hover:underline"
          >
            {t("openTournamentSettings")}
            <ArrowUpRight className="ml-1 h-3.5 w-3.5" aria-hidden />
          </Link>
        </div>
        <div className="space-y-2">
          <Label htmlFor="draft-team-count">{t("teamCount")}</Label>
          <NumberInput
            id="draft-team-count"
            integer
            min={MIN_DRAFT_TEAM_COUNT}
            max={MAX_DRAFT_TEAM_COUNT}
            disabled={locked}
            value={value.teamCount}
            onValueChange={(next) => patch({ teamCount: next ?? MIN_DRAFT_TEAM_COUNT })}
          />
          <p className="text-xs text-muted-foreground">{t("teamCountHint")}</p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Clock3 className="h-4 w-4 text-muted-foreground" aria-hidden />
          <span id={pickTimeLabelId} className="text-sm font-medium leading-none">
            {t("pickTime")}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3" role="group" aria-labelledby={pickTimeLabelId}>
          {/* One segmented control instead of four standalone buttons: the presets
              are a single choice, so they must not read as four separate widgets
              next to the custom field. */}
          <div className="inline-flex h-9 items-center gap-0.5 rounded-md border border-border/70 bg-card p-0.5">
            {PICK_TIME_PRESETS.map((seconds) => (
              <button
                key={seconds}
                type="button"
                disabled={locked}
                aria-pressed={value.pickTimeSeconds === seconds}
                onClick={() => patch({ pickTimeSeconds: seconds })}
                className={cn(
                  "inline-flex h-8 min-w-13 items-center justify-center rounded-[5px] px-3 text-sm font-medium tabular-nums transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                  value.pickTimeSeconds === seconds
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {seconds}s
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="draft-pick-time" className="text-xs font-normal text-muted-foreground">
              {t("customPickTime")}
            </Label>
            <NumberInput
              id="draft-pick-time"
              integer
              min={10}
              max={600}
              disabled={locked}
              value={value.pickTimeSeconds}
              onValueChange={(next) => patch({ pickTimeSeconds: next ?? 45 })}
              className="h-9 w-20 tabular-nums"
            />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <span id={formatLabelId} className="text-sm font-medium leading-none">
          {t("format")}
        </span>
        {/* radiogroup promises arrow-key traversal and a single tab stop, so the
            group owns the arrows and only the checked option stays tabbable. */}
        <div
          className="grid gap-3 md:grid-cols-3"
          role="radiogroup"
          aria-labelledby={formatLabelId}
          onKeyDown={(event) => {
            if (locked) return;
            const delta =
              event.key === "ArrowRight" || event.key === "ArrowDown"
                ? 1
                : event.key === "ArrowLeft" || event.key === "ArrowUp"
                  ? -1
                  : 0;
            if (delta === 0) return;
            event.preventDefault();
            const index = Math.max(0, FORMATS.indexOf(value.format));
            const next = FORMATS[(index + delta + FORMATS.length) % FORMATS.length];
            patch({ format: next });
            event.currentTarget
              .querySelector<HTMLButtonElement>(`[data-format="${next}"]`)
              ?.focus();
          }}
        >
          {FORMATS.map((format) => (
            <button
              key={format}
              type="button"
              role="radio"
              data-format={format}
              tabIndex={value.format === format ? 0 : -1}
              aria-checked={value.format === format}
              disabled={locked}
              onClick={() => patch({ format })}
              className={cn(
                "rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                value.format === format
                  ? "border-primary bg-primary/8 ring-1 ring-primary/30"
                  : "border-border/70 bg-card hover:border-primary/40"
              )}
            >
              <span className="font-medium">{t(`formats.${format}.title`)}</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {t(`formats.${format}.description`)}
              </span>
              <span className="mt-3 flex gap-1" aria-hidden>
                {[1, 2, 3, 4].map((seat, index) => (
                  <span
                    key={seat}
                    className={cn(
                      "grid h-6 w-6 place-items-center rounded-md bg-muted text-xs font-semibold tabular-nums",
                      format === "snake" && index > 1 && "bg-primary/15 text-primary"
                    )}
                  >
                    {format === "snake" && index > 1 ? 5 - seat : seat}
                  </span>
                ))}
              </span>
            </button>
          ))}
        </div>
        {value.format === "custom" && (
          <div className="space-y-3 rounded-xl border border-border/70 bg-muted/20 p-4">
            <div className="space-y-1">
              <span id={roundRulesLabelId} className="text-sm font-medium leading-none">
                {t("roundRules")}
              </span>
              <p className="text-xs text-muted-foreground">{t("roundRulesHint", { rounds })}</p>
            </div>
            {/* One labelled row per round, read top to bottom: a bare two-column
                grid of selects never said which round each rule belonged to, nor
                whether the flow was row- or column-major. */}
            <div className="space-y-2" role="group" aria-labelledby={roundRulesLabelId}>
              {Array.from({ length: rounds }, (_, index) => {
                const round = index + 1;
                const selectId = `draft-round-rule-${round}`;
                return (
                  <div key={round} className="flex items-center gap-3">
                    <Label
                      htmlFor={selectId}
                      className="min-w-16 shrink-0 text-xs font-medium tabular-nums text-muted-foreground"
                    >
                      {t("roundNumber", { round })}
                    </Label>
                    <Select
                      disabled={locked}
                      value={value.roundRules[index] ?? "linear"}
                      onValueChange={(rule) => {
                        // Rebuild at the current round count so a shape change can
                        // never leave a hole (serialized as null) in the payload.
                        const roundRules = Array.from(
                          { length: rounds },
                          (_, i) => value.roundRules[i] ?? "linear"
                        );
                        roundRules[index] = rule;
                        patch({ roundRules });
                      }}
                    >
                      <SelectTrigger id={selectId} className="flex-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {DRAFT_ROUND_RULES.map((rule) => (
                          <SelectItem key={rule} value={rule}>
                            {t(`rules.${rule}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="draft-autopick">{t("autopick")}</Label>
        <Select
          disabled={locked}
          value={value.autopickStrategy}
          onValueChange={(next) => patch({ autopickStrategy: next as DraftAutopickStrategy })}
        >
          <SelectTrigger id="draft-autopick" aria-label={t("autopick")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="best_fit">{t("autopicks.best_fit.title")}</SelectItem>
            <SelectItem value="role_need">{t("autopicks.role_need.title")}</SelectItem>
            <SelectItem value="best_available">{t("autopicks.best_available.title")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-sm text-muted-foreground">
          {t(`autopicks.${value.autopickStrategy}.description`)}
        </p>
      </div>

      <details className="group rounded-xl border border-border/70 bg-muted/20">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium">
          {t("advanced")}
          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div className="space-y-4 border-t border-border/60 px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Label htmlFor="draft-admin-override">{t("allowOverride")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("allowOverrideHint")}</p>
            </div>
            <Switch
              id="draft-admin-override"
              disabled={locked}
              checked={value.allowAdminOverride}
              onCheckedChange={(allowAdminOverride) => patch({ allowAdminOverride })}
            />
          </div>
        </div>
      </details>
    </div>
  );
}
