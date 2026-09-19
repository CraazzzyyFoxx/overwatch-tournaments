import { Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import {
  GROUP_STAGE_SCORE_PRESETS,
  clampScoreValue,
  getScorePresetsForBestOf,
  type EncounterScore,
  type EncounterScorePreset,
} from "@/lib/encounter-score";

type EncounterScoreControlsProps = EncounterScore & {
  idPrefix: string;
  /** Team name where one is known; the generic side otherwise. */
  homeLabel?: string;
  awayLabel?: string;
  presetLabel?: string;
  showGroupStageHint?: boolean;
  /** When set, presets adapt to the series length; BO4+ shows no presets (manual only). */
  bestOf?: number;
  onScoreChange: (score: EncounterScore) => void;
  onPresetSelect?: (score: EncounterScore) => void;
};

export function EncounterScoreControls({
  idPrefix,
  homeScore,
  awayScore,
  homeLabel = "Home",
  awayLabel = "Away",
  presetLabel,
  showGroupStageHint = false,
  bestOf,
  onScoreChange,
  onPresetSelect,
}: EncounterScoreControlsProps) {
  const t = useTranslations();
  const presets: EncounterScorePreset[] =
    bestOf != null ? getScorePresetsForBestOf(bestOf) : GROUP_STAGE_SCORE_PRESETS;
  const selectedPreset = presets.find(
    (preset) => preset.homeScore === homeScore && preset.awayScore === awayScore
  );
  const resolvedPresetLabel = presetLabel ?? t("matchEdit.resultPresets");

  const updateHomeScore = (value: string | number) => {
    onScoreChange({ homeScore: clampScoreValue(value), awayScore });
  };

  const updateAwayScore = (value: string | number) => {
    onScoreChange({ homeScore, awayScore: clampScoreValue(value) });
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
          <p className={EYEBROW_CLASS}>{t("matchEdit.matchScore")}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {showGroupStageHint ? "Group-stage quick results" : t("matchEdit.manualEntry")}
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
            {homeScore} – {awayScore}
          </span>
          <span className="sr-only">{`${homeLabel} ${homeScore}, ${awayLabel} ${awayScore}`}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <ScoreStepper
          id={`${idPrefix}-home-score`}
          label={homeLabel}
          value={homeScore}
          onChange={updateHomeScore}
        />
        <ScoreStepper
          id={`${idPrefix}-away-score`}
          label={awayLabel}
          value={awayScore}
          onChange={updateAwayScore}
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
                    "h-9 px-2 font-bold rounded-lg tabular-nums transition-all duration-150",
                    isSelected
                      ? "border border-primary bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
                      : "border border-border/60 bg-muted/10 text-foreground hover:border-border hover:bg-accent hover:text-accent-foreground"
                  )}
                  aria-pressed={isSelected}
                  aria-label={`Set the score to ${homeLabel} ${preset.homeScore}, ${awayLabel} ${preset.awayScore}`}
                  title={t(`matchEdit.presetDescriptions.${preset.description}` as Parameters<typeof t>[0])}
                  onClick={() =>
                    applyPreset({
                      homeScore: preset.homeScore,
                      awayScore: preset.awayScore,
                    })
                  }
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
  const decrement = () => onChange(value - 1);
  const increment = () => onChange(value + 1);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs font-semibold text-foreground">
        {label}
      </Label>
      <div className="flex h-10 overflow-hidden rounded-lg border border-border/60 bg-muted/10 shadow-sm transition-colors focus-within:border-ring focus-within:ring-0">
        <Button
          type="button"
          variant="ghost"
          className="h-full w-12 shrink-0 rounded-r-none border-r border-border/60 px-0 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          aria-label={`Lower the score for ${label}`}
          onClick={decrement}
          disabled={value <= 0}
        >
          <Minus className="size-4" aria-hidden />
        </Button>
        <Input
          id={id}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-full rounded-none border-0 bg-transparent text-center text-base font-bold tabular-nums text-foreground shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
          aria-label={`Score for ${label}`}
        />
        <Button
          type="button"
          variant="ghost"
          className="h-full w-12 shrink-0 rounded-l-none border-l border-border/60 px-0 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          aria-label={`Raise the score for ${label}`}
          onClick={increment}
        >
          <Plus className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}
