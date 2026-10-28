import { Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import {
  GROUP_STAGE_SCORE_PRESETS,
  clampScoreValue,
  getScorePresetsForBestOf,
  type EncounterScore,
  type EncounterScorePreset,
} from "@/lib/encounter/score";

type EncounterScoreControlsProps = EncounterScore & {
  idPrefix: string;
  /** Team name where one is known; the generic slot label otherwise. */
  firstLabel?: string;
  secondLabel?: string;
  presetLabel?: string;
  showGroupStageHint?: boolean;
  /** When set, presets adapt to the series length; BO4+ shows no presets (manual only). */
  bestOf?: number;
  onScoreChange: (score: EncounterScore) => void;
  onPresetSelect?: (score: EncounterScore) => void;
};

export function EncounterScoreControls({
  idPrefix,
  one,
  two,
  firstLabel = "Team 1",
  secondLabel = "Team 2",
  presetLabel,
  showGroupStageHint = false,
  bestOf,
  onScoreChange,
  onPresetSelect,
}: EncounterScoreControlsProps) {
  const t = useTranslations();
  const scoreT = useTranslations("encounterScore");
  const presets: EncounterScorePreset[] =
    bestOf != null ? getScorePresetsForBestOf(bestOf) : GROUP_STAGE_SCORE_PRESETS;
  const selectedPreset = presets.find((preset) => preset.one === one && preset.two === two);
  const resolvedPresetLabel = presetLabel ?? t("matchEdit.resultPresets");

  const updateFirstScore = (value: string | number) => {
    onScoreChange({ one: clampScoreValue(value), two });
  };

  const updateSecondScore = (value: string | number) => {
    onScoreChange({ one, two: clampScoreValue(value) });
  };

  const applyPreset = (score: EncounterScore) => {
    if (onPresetSelect) {
      onPresetSelect(score);
      return;
    }

    onScoreChange(score);
  };

  return (
    <div className="space-y-4 rounded-xl border border-border/60 bg-muted/10 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className={eyebrowClass("muted")}>{t("matchEdit.matchScore")}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {showGroupStageHint ? scoreT("groupStageQuickResults") : t("matchEdit.manualEntry")}
          </p>
        </div>
        {/* Live region: stepper clicks move focus nowhere, so without it the new
            score is silent for a screen-reader user. */}
        <div
          role="status"
          aria-live="polite"
          className="rounded-lg border border-border/60 bg-background px-3.5 py-1.5 text-lg font-bold tracking-label text-foreground tabular-nums"
        >
          <span aria-hidden>
            {one} – {two}
          </span>
          <span className="sr-only">{`${firstLabel} ${one}, ${secondLabel} ${two}`}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <ScoreStepper
          id={`${idPrefix}-first-score`}
          label={firstLabel}
          value={one}
          onChange={updateFirstScore}
        />
        <ScoreStepper
          id={`${idPrefix}-second-score`}
          label={secondLabel}
          value={two}
          onChange={updateSecondScore}
        />
      </div>

      {presets.length > 0 ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-muted-foreground">{resolvedPresetLabel}</p>
            {selectedPreset ? (
              <span className="text-xs font-semibold text-foreground">
                  {t(`matchEdit.presetDescriptions.${selectedPreset.description}` as Parameters<typeof t>[0])}
              </span>
            ) : null}
          </div>
          <div className="grid grid-cols-5 gap-2">
            {presets.map((preset) => {
              const isSelected = selectedPreset?.label === preset.label;

              return (
                <Button
                  key={preset.label}
                  type="button"
                  variant="ghost"
                  className={cn(
                    "px-2 rounded-lg tabular-nums transition-all duration-150",
                    isSelected
                      ? "border border-primary bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
                      : "border border-border/60 bg-muted/10 text-foreground hover:border-border hover:bg-accent hover:text-accent-foreground"
                  )}
                  aria-pressed={isSelected}
                  aria-label={scoreT("setScore", {
                    firstLabel,
                    firstScore: preset.one,
                    secondLabel,
                    secondScore: preset.two
                  })}
                  title={t(`matchEdit.presetDescriptions.${preset.description}` as Parameters<typeof t>[0])}
                  onClick={() => applyPreset({ one: preset.one, two: preset.two })}
                >
                  {preset.label}
                </Button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

type ScoreStepperProps = {
  id: string;
  label: string;
  value: number;
  onChange: (value: string | number) => void;
};

function ScoreStepper({ id, label, value, onChange }: Readonly<ScoreStepperProps>) {
  const t = useTranslations("encounterScore");
  const decrement = () => onChange(value - 1);
  const increment = () => onChange(value + 1);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs font-semibold text-foreground">
        {label}
      </Label>
      <div className="flex gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="shrink-0"
          aria-label={t("lowerScore", { label })}
          onClick={decrement}
          disabled={value <= 0}
        >
          <Minus aria-hidden />
        </Button>
        <Input
          id={id}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="text-center tabular-nums"
          aria-label={t("scoreFor", { label })}
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="shrink-0"
          aria-label={t("raiseScore", { label })}
          onClick={increment}
        >
          <Plus aria-hidden />
        </Button>
      </div>
    </div>
  );
}
