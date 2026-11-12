"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { Trash2 } from "lucide-react";

import { ffaErrorEntries, useFfaErrorMessage } from "@/components/admin/ffa/FfaGameResultsDialog";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
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
 * How an FFA league is scored: the rule half of the stage's `scoring`.
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
  const t = useTranslations("adminBracket.ffa");
  const tRoot = useTranslations("adminBracket");
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
    <SettingGroup id="stage-ffa-scoring" title={tRoot("editor.ffaScoring")}>
      <SettingRow htmlFor={`${ids}-preset`} label={t("preset")}>
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
                {tRoot(`labels.ffaScoringPresets.${option.labelKey}` as never)}
              </SelectItem>
            ))}
            {/* Only reachable as a state, never as a choice: it IS the fields
                below once a column, a place or the formula has been edited. */}
            {preset === "custom" ? <SelectItem value="custom">{t("custom")}</SelectItem> : null}
          </SelectContent>
        </Select>
      </SettingRow>

      <SettingRow
        label={t("columns")}
        hint={t("keyHelp", { max: FFA_COLUMN_KEY_MAX, maxColumns: FFA_MAX_COLUMNS })}
        stacked
      >
        <div className="flex w-full min-w-0 flex-col gap-2">
          {columns.length === 0 ? (
            <EmptyNote size="sm">{t("noColumns")}</EmptyNote>
          ) : (
            columns.map((column, index) => (
              // The index IS the position in the table, and columns are renumbered
              // on removal — there is no stabler key, and no row state to carry.
              <div key={index} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto_auto_auto]">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <Label htmlFor={`${ids}-key-${index}`}>{t("columnKey", { number: index + 1 })}</Label>
                  <Input
                    id={`${ids}-key-${index}`}
                    maxLength={FFA_COLUMN_KEY_MAX}
                    placeholder={t("keyPlaceholder")}
                    className="font-mono"
                    spellCheck={false}
                    value={column.key}
                    onChange={(event) => setColumn(index, { key: event.target.value })}
                  />
                </div>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <Label htmlFor={`${ids}-label-${index}`}>{t("columnLabel", { number: index + 1 })}</Label>
                  <Input
                    id={`${ids}-label-${index}`}
                    maxLength={FFA_COLUMN_LABEL_MAX}
                    placeholder={t("labelPlaceholder")}
                    value={column.label}
                    onChange={(event) => setColumn(index, { label: event.target.value })}
                  />
                </div>
                <span className="flex items-center gap-2 pb-2 text-xs text-muted-foreground">
                  <Checkbox
                    checked={column.public}
                    aria-label={t("showColumn", { number: index + 1 })}
                    onCheckedChange={(checked) => setColumn(index, { public: checked === true })}
                  />
                  <span>{t("inTable")}</span>
                </span>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`${ids}-better-${index}`}>{t("direction", { number: index + 1 })}</Label>
                  <Select
                    value={column.better}
                    onValueChange={(value) => setColumn(index, { better: value as FfaColumn["better"] })}
                  >
                    <SelectTrigger id={`${ids}-better-${index}`} className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="higher">{t("higher")}</SelectItem>
                      <SelectItem value="lower">{t("lower")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="mb-0.5 text-muted-foreground hover:text-foreground"
                  aria-label={t("removeColumn", { number: index + 1 })}
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

          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto self-start p-0 text-primary"
            disabled={columns.length >= FFA_MAX_COLUMNS}
            onClick={() =>
              onChange({
                ffaColumns: [...columns, { key: "", label: "", public: true, better: "higher" }]
              })
            }
          >
            {t("addColumn")}
          </Button>
        </div>
      </SettingRow>

      <SettingRow htmlFor={`${ids}-formula`} label={t("formula")} stacked>
        <div className="flex w-full min-w-0 flex-col gap-1.5">
          <Textarea
            id={`${ids}-formula`}
            rows={2}
            maxLength={FFA_FORMULA_MAX}
            className="font-mono"
            spellCheck={false}
            placeholder={t("formulaPlaceholder")}
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
            {t.rich("formulaHelp", {
              variables: [...columns.map((column) => column.key).filter(Boolean), ...FFA_FORMULA_VARIABLES].join(", "),
              functionList: FFA_FORMULA_FUNCTIONS.join(", "),
              logic: t("logic"),
              variablesCode: (chunks) => <code>{chunks}</code>,
              functionCode: (chunks) => <code>{chunks}</code>,
              logicCode: (chunks) => <code>{chunks}</code>
            })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("placeHelp")}
          </p>
        </div>
      </SettingRow>

      <SettingRow label={t("pointsPerPlace")} hint={t("tail")} stacked>
        <div className="flex w-full min-w-0 flex-col gap-2">
          {places.length === 0 ? (
            <EmptyNote size="sm">{t("noPlacement")}</EmptyNote>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {places.map((points, index) => (
                // The index IS the place, and places are renumbered on removal —
                // there is no stabler key, and no row state to carry.
                <div key={index} className="flex items-end gap-1">
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <Label
                      htmlFor={`${ids}-place-${index}`}
                    >{t("place", { ordinal: ordinalPlace(index + 1) })}</Label>
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
                    aria-label={t("removePlace", { ordinal: ordinalPlace(index + 1) })}
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

          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto self-start p-0 text-primary"
            disabled={places.length >= FFA_MAX_PLACES}
            onClick={() => onChange({ ffaPlacementPoints: [...places, 0] })}
          >
            {t("addPlace")}
          </Button>
        </div>
      </SettingRow>
    </SettingGroup>
  );
}
