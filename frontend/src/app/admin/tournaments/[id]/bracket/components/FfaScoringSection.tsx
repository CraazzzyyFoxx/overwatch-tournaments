"use client";

import { useId } from "react";
import { Trash2 } from "lucide-react";

import { ffaErrorEntries, useFfaErrorMessage } from "@/components/admin/ffa/FfaGameResultsDialog";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Textarea } from "@/components/ui/textarea";
import {
  FFA_COLUMN_KEY_MAX,
  FFA_COLUMN_LABEL_MAX,
  FFA_FORMULA_FUNCTIONS,
  FFA_FORMULA_MAX,
  FFA_FORMULA_VARIABLES,
  FFA_MAX_COLUMNS,
  FFA_MAX_PLACES,
  FFA_SCORING_PRESETS,
  ffaScoringPresetOf,
  ordinalPlace
} from "@/lib/ffa/scoring-presets";
import type { FfaColumn } from "@/types/ffa.types";

import type { StageForm } from "../stageForm";

/**
 * How an FFA league is scored: the stage's `ffa_scoring`.
 *
 * Three things, and the third is the rule: the columns a game records, the
 * points a place pays, and the formula that turns both into the points of that
 * game. A preset only fills them in — the organizer's own rule is what gets
 * saved.
 *
 * The formula is the one field here the server parses rather than stores, so it
 * is the one field that can be refused by position. `saveError` is the last
 * refusal of the save; the parts of it this section owns are shown under the
 * field they are about, because a toast cannot point at character 14.
 */
export function FfaScoringSection({
  form,
  onChange,
  saveError
}: Readonly<{
  form: StageForm;
  onChange: (patch: Partial<StageForm>) => void;
  saveError?: unknown;
}>) {
  const ids = useId();
  const describeError = useFfaErrorMessage();
  const columns = form.ffaColumns;
  const places = form.ffaPlacementPoints;
  const preset = ffaScoringPresetOf(columns, places, form.ffaFormula);

  const codes = ffaErrorEntries(saveError).map((entry) => entry.code);
  const formulaError = codes.some((code) => code.startsWith("ffa_formula_"))
    ? describeError(saveError)
    : null;
  const columnsError = codes.some((code) => code.startsWith("ffa_column"))
    ? describeError(saveError)
    : null;

  const setColumn = (index: number, patch: Partial<FfaColumn>) =>
    onChange({
      ffaColumns: columns.map((column, at) => (at === index ? { ...column, ...patch } : column))
    });

  const setPlace = (index: number, points: number | null) =>
    onChange({
      ffaPlacementPoints: places.map((current, at) => (at === index ? (points ?? 0) : current))
    });

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5 sm:max-w-xs">
        <Label htmlFor={`${ids}-preset`}>Scoring preset</Label>
        <Select
          value={preset}
          onValueChange={(value) => {
            const picked = FFA_SCORING_PRESETS.find((option) => option.value === value);
            if (!picked) return;
            onChange({
              ffaColumns: picked.columns.map((column) => ({ ...column })),
              ffaPlacementPoints: [...picked.placementPoints],
              ffaFormula: picked.formula
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
            {/* Only reachable as a state, never as a choice: it IS the fields
                below once a column, a place or the formula has been edited. */}
            {preset === "custom" ? <SelectItem value="custom">Custom</SelectItem> : null}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className={EYEBROW_CLASS}>Game columns</h3>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs text-primary"
            disabled={columns.length >= FFA_MAX_COLUMNS}
            onClick={() =>
              onChange({
                ffaColumns: [...columns, { key: "", label: "", public: true, better: "higher" }]
              })
            }
          >
            Add column
          </Button>
        </div>

        {columns.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            Nothing is entered per game: the lobby is scored on its places alone. Add a column to
            record kills, damage or a penalty.
          </p>
        ) : (
          columns.map((column, index) => (
            // The index IS the position in the table, and columns are renumbered
            // on removal — there is no stabler key, and no row state to carry.
            <div key={index} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto_auto_auto]">
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor={`${ids}-key-${index}`}>{`Column ${index + 1} key`}</Label>
                <Input
                  id={`${ids}-key-${index}`}
                  maxLength={FFA_COLUMN_KEY_MAX}
                  placeholder="kills"
                  className="font-mono"
                  spellCheck={false}
                  value={column.key}
                  onChange={(event) => setColumn(index, { key: event.target.value })}
                />
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor={`${ids}-label-${index}`}>{`Column ${index + 1} label`}</Label>
                <Input
                  id={`${ids}-label-${index}`}
                  maxLength={FFA_COLUMN_LABEL_MAX}
                  placeholder="Kills"
                  value={column.label}
                  onChange={(event) => setColumn(index, { label: event.target.value })}
                />
              </div>
              <span className="flex items-center gap-2 pb-2 text-xs text-muted-foreground">
                <Checkbox
                  checked={column.public}
                  aria-label={`Show column ${index + 1} in the table`}
                  onCheckedChange={(checked) => setColumn(index, { public: checked === true })}
                />
                <span>In the table</span>
              </span>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${ids}-better-${index}`}>{`Column ${index + 1} direction`}</Label>
                <Select
                  value={column.better}
                  onValueChange={(value) => setColumn(index, { better: value as FfaColumn["better"] })}
                >
                  <SelectTrigger id={`${ids}-better-${index}`} className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="higher">Higher is better</SelectItem>
                    <SelectItem value="lower">Lower is better</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="mb-0.5 text-muted-foreground hover:text-foreground"
                aria-label={`Remove column ${index + 1}`}
                onClick={() => onChange({ ffaColumns: columns.filter((_, at) => at !== index) })}
              >
                <Trash2 className="size-4" aria-hidden />
              </Button>
            </div>
          ))
        )}

        {columnsError ? (
          <p role="alert" className="text-xs text-danger">
            {columnsError}
          </p>
        ) : null}

        <p className="text-xs text-muted-foreground">
          The key is what the formula reads — lowercase letters, digits and underscores, up to{" "}
          {FFA_COLUMN_KEY_MAX} characters. A column left out of the table is still entered and still
          scored; the public lobby never shows its values. A column with values in it can be
          relabelled, but not renamed or removed. At most {FFA_MAX_COLUMNS} columns.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${ids}-formula`}>Points formula</Label>
        <Textarea
          id={`${ids}-formula`}
          rows={2}
          maxLength={FFA_FORMULA_MAX}
          className="font-mono text-sm"
          spellCheck={false}
          placeholder="place_pts + kills * 2 - deaths"
          value={form.ffaFormula}
          onChange={(event) => onChange({ ffaFormula: event.target.value })}
          aria-describedby={`${ids}-formula-hint`}
          aria-invalid={formulaError != null || undefined}
          aria-errormessage={formulaError != null ? `${ids}-formula-error` : undefined}
        />
        {formulaError ? (
          <p id={`${ids}-formula-error`} role="alert" className="text-xs text-danger">
            {formulaError}
          </p>
        ) : null}
        <p id={`${ids}-formula-hint`} className="text-xs text-muted-foreground">
          <span className="font-mono">
            {[...columns.map((column) => column.key).filter(Boolean), ...FFA_FORMULA_VARIABLES].join(
              ", "
            )}
          </span>{" "}
          · functions <span className="font-mono">{FFA_FORMULA_FUNCTIONS.join(", ")}</span> ·
          arithmetic, comparisons and <span className="font-mono">and / or / not</span>.
        </p>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">place</span> is the finishing place,{" "}
          <span className="font-mono">place_pts</span> what that place pays in the table below, and{" "}
          <span className="font-mono">teams</span> the size of the lobby. Reading{" "}
          <span className="font-mono">place</span> or <span className="font-mono">place_pts</span> is
          what makes a place REQUIRED when a game is entered; a formula that reads neither derives
          the places from the points instead.
        </p>
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
            No points for placement: <span className="font-mono">place_pts</span> is zero for
            everyone. Add a place to pay for finishing position too.
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
          legal — the tail scores on its columns alone.
        </p>
      </div>
    </div>
  );
}
