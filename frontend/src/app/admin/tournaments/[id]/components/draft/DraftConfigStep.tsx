"use client";

import Link from "next/link";
import { useId } from "react";
import { ArrowUpRight, ChevronDown, Clock3, TimerReset } from "lucide-react";
import { useTranslations } from "next-intl";

import { disclosureChevronClass } from "@/components/ui/chevron";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import FlexIcon from "@/components/icons/FlexIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import { isRoleSlot, slotCodesOf, type RosterShape } from "@/lib/roster/shape";
import type { DraftAutopickStrategy, DraftFormatSettings } from "@/types/draft.types";

import type { DraftRoundRule } from "./setup-model";
import type { DraftSetupConfig } from "./setup-types";

interface DraftConfigStepProps {
  value: DraftSetupConfig;
  onChange: (next: DraftSetupConfig) => void;
  /** Resolved on the server from the tournament; never editable here (T14 owns it). */
  rosterShape: RosterShape;
  /** The owner game's role dictionary: the names and glyphs of the shape's slots. */
  ontology: RoleOntology | null;
  /** The tournament's format rule, resolved to the round count; read-only here. */
  format: DraftFormatSettings;
  tournamentId: number;
  locked?: boolean;
}

const PICK_TIME_PRESETS = [30, 45, 60, 90];
const OVERTIME_PRESETS = [0, 15, 30, 60];

export function DraftConfigStep({
  value,
  onChange,
  rosterShape,
  ontology,
  format,
  tournamentId,
  locked = false
}: Readonly<DraftConfigStepProps>) {
  const t = useTranslations("draftAdmin");
  const slotLabel = useSlotLabel(ontology);
  // Straight off the server shape: deriving rounds from a size here is exactly
  // the mirror this feature removes.
  const rounds = rosterShape.draft_rounds;
  const pickTimeLabelId = useId();
  const overtimeLabelId = useId();

  const patch = (next: Partial<DraftSetupConfig>) => onChange({ ...value, ...next });

  return (
    <div className="space-y-6">
      {locked && <p className="text-caption text-warning">{t("configLocked")}</p>}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label>{t("teamSize")}</Label>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm tabular-nums">
            <span className="font-semibold">{rosterShape.team_size}</span>
            {slotCodesOf(rosterShape.slots).map((code) => {
              const label = slotLabel(code);
              return (
                <span
                  key={code}
                  className="inline-flex items-center gap-1 text-muted-foreground"
                  title={label}
                >
                  {isRoleSlot(code) ? (
                    <PlayerRoleIcon role={code} ontology={ontology} size={16} decorative />
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
        {/* A rule of the tournament, not of this draft: the server seeds every
            session with it, so the wizard only names it. */}
        <div className="space-y-2">
          <Label>{t("format")}</Label>
          <p className="text-sm font-semibold">{t(`formats.${format.format}.title`)}</p>
          {format.format === "custom" ? (
            <ol className="space-y-0.5 text-xs tabular-nums text-muted-foreground">
              {format.round_rules.map((rule, index) => (
                <li key={index}>
                  {/* `resolveDraftFormat` already coerced every entry to a known rule. */}
                  {t("roundNumber", { round: index + 1 })}: {t(`rules.${rule as DraftRoundRule}`)}
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-muted-foreground">
              {t(`formats.${format.format}.description`)}
            </p>
          )}
          <Link
            href={`/admin/tournaments/${tournamentId}/settings/draft`}
            className="inline-flex items-center text-xs font-medium text-primary hover:underline"
          >
            {t("changeFormatInSettings")}
            <ArrowUpRight className="ml-1 h-3.5 w-3.5" aria-hidden />
          </Link>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Clock3 className="h-4 w-4 text-muted-foreground" aria-hidden />
          <span id={pickTimeLabelId} className="text-sm font-medium leading-none">
            {t("pickTime")}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            variant="pill"
            size="sm"
            aria-labelledby={pickTimeLabelId}
            value={String(value.pickTimeSeconds)}
            onValueChange={(next) => patch({ pickTimeSeconds: Number(next) })}
          >
            {PICK_TIME_PRESETS.map((seconds) => (
              <ToggleGroupItem key={seconds} value={String(seconds)} disabled={locked} className="tabular-nums">
                {`${seconds}s`}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
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
              className="w-20"
            />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <TimerReset className="h-4 w-4 text-muted-foreground" aria-hidden />
          <span id={overtimeLabelId} className="text-sm font-medium leading-none">
            {t("overtime")}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            variant="pill"
            size="sm"
            aria-labelledby={overtimeLabelId}
            value={String(value.overtimeSeconds)}
            onValueChange={(next) => patch({ overtimeSeconds: Number(next) })}
          >
            {OVERTIME_PRESETS.map((seconds) => (
              <ToggleGroupItem key={seconds} value={String(seconds)} disabled={locked} className="tabular-nums">
                {seconds === 0 ? t("overtimeOff") : `${seconds}s`}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex items-center gap-2">
            <Label htmlFor="draft-overtime" className="text-xs font-normal text-muted-foreground">
              {t("customOvertime")}
            </Label>
            <NumberInput
              id="draft-overtime"
              integer
              min={0}
              max={300}
              disabled={locked}
              value={value.overtimeSeconds}
              onValueChange={(next) => patch({ overtimeSeconds: next ?? 0 })}
              className="w-20"
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground">{t("overtimeHint")}</p>
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

      <details className="group/disclosure rounded-xl border border-border">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium">
          {t("advanced")}
          <ChevronDown className={disclosureChevronClass} aria-hidden />
        </summary>
        <div className="space-y-4 border-t border-border px-4 py-4">
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
