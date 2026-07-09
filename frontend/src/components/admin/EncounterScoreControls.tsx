import { Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import {
  GROUP_STAGE_SCORE_PRESETS,
  clampScoreValue,
  getMatchingScorePreset,
  type EncounterScore,
} from "@/components/admin/encounter-score";

type EncounterScoreControlsProps = EncounterScore & {
  idPrefix: string;
  homeLabel?: string;
  awayLabel?: string;
  presetLabel?: string;
  showGroupStageHint?: boolean;
  onScoreChange: (score: EncounterScore) => void;
  onPresetSelect?: (score: EncounterScore) => void;
};

export function EncounterScoreControls({
  idPrefix,
  homeScore,
  awayScore,
  homeLabel = "Home Score",
  awayLabel = "Away Score",
  presetLabel,
  showGroupStageHint = false,
  onScoreChange,
  onPresetSelect,
}: EncounterScoreControlsProps) {
  const t = useTranslations();
  const selectedPreset = getMatchingScorePreset(homeScore, awayScore);
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
    <div className="space-y-4 rounded-xl border border-zinc-800/80 bg-zinc-950/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">
            {t("matchEdit.matchScore")}
          </p>
          <p className="mt-0.5 text-[11px] font-medium text-zinc-500">
            {showGroupStageHint ? "Group-stage quick results" : t("matchEdit.manualEntry")}
          </p>
        </div>
        <div
          className="rounded-lg border border-zinc-800 bg-[#09090b] px-3.5 py-1.5 text-lg font-bold font-mono tracking-widest text-white tabular-nums"
          aria-label={`Current score ${homeScore} to ${awayScore}`}
        >
          {homeScore} - {awayScore}
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

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-semibold text-zinc-400">{resolvedPresetLabel}</p>
          {selectedPreset ? (
            <span className="text-xs font-semibold text-zinc-300">
              {t(`matchEdit.presetDescriptions.${selectedPreset.description}` as Parameters<typeof t>[0])}
            </span>
          ) : null}
        </div>
        <div className="grid grid-cols-5 gap-2">
          {GROUP_STAGE_SCORE_PRESETS.map((preset) => {
            const isSelected = selectedPreset?.label === preset.label;

            return (
              <Button
                key={preset.label}
                type="button"
                variant="ghost"
                className={cn(
                  "h-9 px-2 font-bold font-mono rounded-lg transition-all duration-150",
                  isSelected
                    ? "bg-white text-zinc-950 border border-white hover:bg-white hover:text-zinc-950"
                    : "bg-zinc-900/40 border border-zinc-800/80 text-zinc-200 hover:bg-zinc-800 hover:text-white hover:border-zinc-700"
                )}
                aria-pressed={isSelected}
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
    </div>
  );
}

type ScoreStepperProps = {
  id: string;
  label: string;
  value: number;
  onChange: (value: string | number) => void;
};

function ScoreStepper({ id, label, value, onChange }: ScoreStepperProps) {
  const decrement = () => onChange(value - 1);
  const increment = () => onChange(value + 1);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs font-semibold text-zinc-300">
        {label}
      </Label>
      <div className="flex h-10 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/40 shadow-sm focus-within:border-zinc-300 focus-within:ring-0 transition-colors">
        <Button
          type="button"
          variant="ghost"
          className="h-full w-12 shrink-0 rounded-r-none border-r border-zinc-800/80 px-0 text-zinc-400 hover:text-white hover:bg-zinc-800/50 transition-colors"
          aria-label={`Decrease ${label.toLowerCase()}`}
          onClick={decrement}
          disabled={value <= 0}
        >
          <Minus className="size-4" />
        </Button>
        <Input
          id={id}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-full rounded-none border-0 bg-transparent text-center text-base font-bold font-mono text-white shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
          aria-label={label}
        />
        <Button
          type="button"
          variant="ghost"
          className="h-full w-12 shrink-0 rounded-l-none border-l border-zinc-800/80 px-0 text-zinc-400 hover:text-white hover:bg-zinc-800/50 transition-colors"
          aria-label={`Increase ${label.toLowerCase()}`}
          onClick={increment}
        >
          <Plus className="size-4" />
        </Button>
      </div>
    </div>
  );
}

