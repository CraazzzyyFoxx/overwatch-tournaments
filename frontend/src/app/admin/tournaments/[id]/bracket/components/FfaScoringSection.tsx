"use client";

import { useId } from "react";
import { Trash2 } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  FFA_MAX_PLACES,
  FFA_SCORE_LABEL_MAX,
  FFA_SCORING_PRESETS,
  ffaScoringPresetOf,
  ordinalPlace
} from "@/lib/ffa/scoring-presets";

import type { StageForm } from "../stageForm";

/**
 * What an FFA league pays for: the stage's `ffa_scoring`.
 *
 * A preset only fills the table in. The points a place is worth are the
 * organizer's, and a league that pays nothing for placement (a score-only
 * lobby) is an empty table rather than a row of zeroes — that is the shape the
 * engine reads as "placement carries no points".
 */
export function FfaScoringSection({
  form,
  onChange
}: Readonly<{ form: StageForm; onChange: (patch: Partial<StageForm>) => void }>) {
  const ids = useId();
  const places = form.ffaPlacementPoints;
  const preset = ffaScoringPresetOf(places, form.ffaScorePoints);

  const setPlace = (index: number, points: number | null) =>
    onChange({
      ffaPlacementPoints: places.map((current, at) => (at === index ? (points ?? 0) : current))
    });

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-preset`}>Scoring preset</Label>
          <Select
            value={preset}
            onValueChange={(value) => {
              const picked = FFA_SCORING_PRESETS.find((option) => option.value === value);
              if (!picked) return;
              onChange({
                ffaPlacementPoints: [...picked.placementPoints],
                ffaScorePoints: picked.scorePoints
              });
            }}
          >
            <SelectTrigger id={`${ids}-preset`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FFA_SCORING_PRESETS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
              {/* Only reachable as a state, never as a choice: it IS the table
                  below once a place or the score rate has been edited. */}
              {preset === "custom" ? <SelectItem value="custom">Custom</SelectItem> : null}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-score-points`}>Points per score unit</Label>
          <NumberInput
            id={`${ids}-score-points`}
            min={0}
            value={form.ffaScorePoints}
            onValueChange={(next) => onChange({ ffaScorePoints: next ?? 0 })}
          />
          <p className="text-xs text-muted-foreground">
            What one unit of the score a team reports is worth: a kill, an elimination, a lap point.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-score-label`}>Score label</Label>
          <Input
            id={`${ids}-score-label`}
            maxLength={FFA_SCORE_LABEL_MAX}
            placeholder="Score"
            value={form.ffaScoreLabel}
            onChange={(event) => onChange({ ffaScoreLabel: event.target.value })}
          />
          <p className="text-xs text-muted-foreground">
            The column&apos;s name on the lobby table. Left empty it reads &quot;Score&quot;.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className={EYEBROW_CLASS}>Points per place</h3>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs text-primary"
            disabled={places.length >= FFA_MAX_PLACES}
            onClick={() => onChange({ ffaPlacementPoints: [...places, 0] })}
          >
            Add place
          </Button>
        </div>

        {places.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            No points for placement: a lobby is scored on its score column alone. Add a place to pay
            for finishing position too.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {places.map((points, index) => (
              // The index IS the place, and places are renumbered on removal —
              // there is no stabler key, and no row state to carry.
              <div key={index} className="flex items-end gap-1">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <Label
                    htmlFor={`${ids}-place-${index}`}
                  >{`${ordinalPlace(index + 1)} place`}</Label>
                  <NumberInput
                    id={`${ids}-place-${index}`}
                    min={0}
                    value={points}
                    onValueChange={(next) => setPlace(index, next)}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={`Remove ${ordinalPlace(index + 1)} place`}
                  onClick={() =>
                    onChange({ ffaPlacementPoints: places.filter((_, at) => at !== index) })
                  }
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          A place past the end of this table pays nothing, so a table shorter than the lobby is
          legal — the tail simply scores on its score column.
        </p>
      </div>
    </div>
  );
}
