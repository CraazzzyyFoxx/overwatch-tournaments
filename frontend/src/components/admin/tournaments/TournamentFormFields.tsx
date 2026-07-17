"use client";

import type { DivisionGridVersion } from "@/types/workspace.types";
import { Checkbox } from "@/components/ui/checkbox";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

export type TournamentFormFieldsMode =
  | "manual-create"
  | "challonge-create"
  | "edit"
  | "workspace-edit";

export type TournamentFormFieldsValue = {
  name: string;
  description?: string | null;
  is_league: boolean;
  start_date: string;
  end_date: string;
  number?: number | null;
  challonge_slug?: string | null;
  is_finished?: boolean;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
  team_formation?: string;
};

interface TournamentFormFieldsProps<T extends TournamentFormFieldsValue> {
  value: T;
  onChange: (next: T) => void;
  mode: TournamentFormFieldsMode;
  idPrefix?: string;
  challongeSlugValue?: string;
  onChallongeSlugValueChange?: (value: string) => void;
  divisionGridVersions?: DivisionGridVersion[];
  divisionGridLoading?: boolean;
}

export function TournamentFormFields<T extends TournamentFormFieldsValue>({
  value,
  onChange,
  mode,
  idPrefix = "tournament",
  challongeSlugValue,
  onChallongeSlugValueChange,
  divisionGridVersions = [],
  divisionGridLoading = false,
}: TournamentFormFieldsProps<T>) {
  const showNumber = mode !== "edit";
  const showDescription = mode !== "challonge-create";
  const showInlineChallonge = mode === "edit" || mode === "workspace-edit";
  const showSeparateChallonge = mode === "challonge-create";
  const showFinished = mode === "edit" || mode === "workspace-edit";
  const showDivisionGrid =
    mode === "workspace-edit" || mode === "manual-create" || mode === "challonge-create";
  const showScoring = mode === "workspace-edit";
  const showTeamFormation =
    mode === "workspace-edit" || mode === "manual-create" || mode === "challonge-create";

  return (
    <div className="grid gap-5">
      {showSeparateChallonge ? (
        <div className="col-span-full">
          <Label htmlFor={`${idPrefix}-challonge-separate`}>Challonge URL or Slug *</Label>
          <Input
            id={`${idPrefix}-challonge-separate`}
            placeholder="e.g. my-tournament or https://challonge.com/my-tournament"
            value={challongeSlugValue ?? ""}
            onChange={(event) => onChallongeSlugValueChange?.(event.target.value)}
            required
            className="mt-1.5"
          />
          <p className="mt-1.5 text-xs text-muted-foreground">
            The Challonge bracket must have group stages enabled (two-stage). All stages will be
            created automatically.
          </p>
        </div>
      ) : null}

      {mode !== "challonge-create" || showNumber ? (
        <div className={showNumber ? "grid grid-cols-1 sm:grid-cols-[3fr_1fr] gap-4" : ""}>
          {mode !== "challonge-create" ? (
            <div>
              <Label htmlFor={`${idPrefix}-name`}>{mode === "manual-create" ? "Name *" : "Name"}</Label>
              <Input
                id={`${idPrefix}-name`}
                value={value.name}
                onChange={(event) => onChange({ ...value, name: event.target.value })}
                required={mode === "manual-create"}
                className="mt-1.5"
              />
            </div>
          ) : null}

          {showNumber ? (
            <div>
              <Label htmlFor={`${idPrefix}-number`}>
                {mode === "challonge-create" ? "Number *" : "Number"}
              </Label>
              <NumberInput
                id={`${idPrefix}-number`}
                integer
                value={value.number}
                onValueChange={(next) => onChange({ ...value, number: next })}
                required={mode === "challonge-create"}
                className="mt-1.5"
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {showDescription ? (
        <div className="col-span-full">
          <Label htmlFor={`${idPrefix}-description`}>Description</Label>
          <Textarea
            id={`${idPrefix}-description`}
            value={value.description ?? ""}
            onChange={(event) => onChange({ ...value, description: event.target.value })}
            className="mt-1.5 min-h-[80px]"
          />
        </div>
      ) : null}

      {showInlineChallonge ? (
        <div className="col-span-full">
          <Label htmlFor={`${idPrefix}-challonge`}>Challonge URL or Slug</Label>
          <Input
            id={`${idPrefix}-challonge`}
            placeholder="e.g. my-tournament or https://challonge.com/my-tournament"
            value={value.challonge_slug ?? ""}
            onChange={(event) => onChange({ ...value, challonge_slug: event.target.value })}
            className="mt-1.5"
          />
        </div>
      ) : null}

      {/* Select fields group */}
      {showTeamFormation || showDivisionGrid ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 col-span-full">
          {showTeamFormation ? (
            <div>
              <Label htmlFor={`${idPrefix}-team-formation`}>Team formation</Label>
              <Select
                value={value.team_formation ?? "balancer"}
                onValueChange={(nextValue) => onChange({ ...value, team_formation: nextValue })}
              >
                <SelectTrigger id={`${idPrefix}-team-formation`} className="mt-1.5">
                  <SelectValue placeholder="Select method" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="balancer">Auto-balance (Balancer)</SelectItem>
                  <SelectItem value="draft">Live draft</SelectItem>
                </SelectContent>
              </Select>
              <p className="mt-1.5 text-xs text-muted-foreground">
                How teams are formed for this tournament.
              </p>
            </div>
          ) : null}

          {showDivisionGrid ? (
            <div>
              <Label htmlFor={`${idPrefix}-division-grid-version`}>Division Grid Version</Label>
              <Select
                value={value.division_grid_version_id?.toString() ?? "none"}
                onValueChange={(nextValue) =>
                  onChange({
                    ...value,
                    division_grid_version_id: nextValue === "none" ? null : Number(nextValue),
                  })
                }
              >
                <SelectTrigger id={`${idPrefix}-division-grid-version`} className="mt-1.5">
                  <SelectValue
                    placeholder={divisionGridLoading ? "Loading division grids..." : "Select version"}
                  />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Workspace default</SelectItem>
                  {divisionGridVersions.map((version) => (
                    <SelectItem key={version.id} value={version.id.toString()}>
                      {version.label} (v{version.version}, {version.status})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Checkboxes grouped in a premium panel */}
      {mode === "workspace-edit" || mode === "manual-create" || mode === "challonge-create" || showFinished ? (
        <div className="flex flex-col sm:flex-row gap-5 bg-muted/20 border border-border/50 rounded-lg p-3.5 col-span-full">
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${idPrefix}-is-league`}
              checked={value.is_league}
              onCheckedChange={(checked) => onChange({ ...value, is_league: checked === true })}
            />
            <Label htmlFor={`${idPrefix}-is-league`} className="cursor-pointer text-sm font-medium">
              {mode === "workspace-edit" ? "Treat as league season" : "Is League"}
            </Label>
          </div>

          {showFinished ? (
            <div className="flex items-center gap-2">
              <Checkbox
                id={`${idPrefix}-is-finished`}
                checked={value.is_finished ?? false}
                onCheckedChange={(checked) => onChange({ ...value, is_finished: checked === true })}
              />
              <Label htmlFor={`${idPrefix}-is-finished`} className="cursor-pointer text-sm font-medium">
                {mode === "workspace-edit"
                  ? "Mark tournament as finished"
                  : "Is Finished"}
              </Label>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="col-span-full">
        <Field>
          <FieldLabel htmlFor={`${idPrefix}-date-range`}>
            {mode === "manual-create" || mode === "challonge-create" ? "Date Range *" : "Date Range"}
          </FieldLabel>
          <div className="mt-1.5">
            <DateRangePicker
              id={`${idPrefix}-date-range`}
              startDate={value.start_date}
              endDate={value.end_date}
              onChange={(start, end) => onChange({ ...value, start_date: start, end_date: end })}
            />
          </div>
        </Field>
      </div>

      {showScoring ? (
        <div className="col-span-full border-t border-border/40 pt-4">
          <p className="mb-3 text-sm font-medium">Scoring Points</p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor={`${idPrefix}-win-points`}>Win</Label>
              <NumberInput
                id={`${idPrefix}-win-points`}
                value={value.win_points ?? 0}
                onValueChange={(next) => onChange({ ...value, win_points: next ?? 0 })}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor={`${idPrefix}-draw-points`}>Draw</Label>
              <NumberInput
                id={`${idPrefix}-draw-points`}
                value={value.draw_points ?? 0}
                onValueChange={(next) => onChange({ ...value, draw_points: next ?? 0 })}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor={`${idPrefix}-loss-points`}>Loss</Label>
              <NumberInput
                id={`${idPrefix}-loss-points`}
                value={value.loss_points ?? 0}
                onValueChange={(next) => onChange({ ...value, loss_points: next ?? 0 })}
                className="mt-1.5"
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
