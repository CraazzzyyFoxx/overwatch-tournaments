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

type TournamentFormFieldsMode =
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
  challonge_slug?: string | null;
  // Public-URL slug (`/tournaments/<slug>`); blank at creation auto-generates
  // one from `name`. Renaming an existing tournament redirects the old link.
  slug?: string | null;
  is_finished?: boolean;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
  team_formation?: string;
};

/** Visual required marker; `required` on the control carries the semantics. */
const requiredMark = (
  <span aria-hidden className="ml-0.5 text-danger">
    *
  </span>
);

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
}: Readonly<TournamentFormFieldsProps<T>>) {
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
          <Label htmlFor={`${idPrefix}-challonge-separate`}>
            Challonge URL or slug{requiredMark}
          </Label>
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

      {mode !== "challonge-create" ? (
        <div className="col-span-full">
          <Label htmlFor={`${idPrefix}-name`}>
            Name
            {mode === "manual-create" ? requiredMark : null}
          </Label>
          <Input
            id={`${idPrefix}-name`}
            value={value.name}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            required={mode === "manual-create"}
            className="mt-1.5"
          />
        </div>
      ) : null}

      <div className="col-span-full">
        <Label htmlFor={`${idPrefix}-slug`}>Public URL slug</Label>
        <Input
          id={`${idPrefix}-slug`}
          value={value.slug ?? ""}
          onChange={(event) => onChange({ ...value, slug: event.target.value })}
          placeholder="auto-generated from name if left blank"
          className="mt-1.5"
        />
        <p className="mt-1.5 text-xs text-muted-foreground">
          {mode === "edit" || mode === "workspace-edit"
            ? "Used in the public tournament URL. Changing it keeps the previous link working via a redirect."
            : "Used in the public tournament URL. Leave blank to generate one from the name."}
        </p>
      </div>

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
                  <SelectItem value="registration">Team registration</SelectItem>
                  <SelectItem value="solo">Solo registration (FFA)</SelectItem>
                </SelectContent>
              </Select>
              <p className="mt-1.5 text-xs text-muted-foreground">
                How teams are formed for this tournament.
              </p>
            </div>
          ) : null}

          {showDivisionGrid ? (
            <div>
              <Label htmlFor={`${idPrefix}-division-grid-version`}>Division grid version</Label>
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
                    placeholder={divisionGridLoading ? "Loading division grids…" : "Select version"}
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
              Treat as league season
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
                Mark tournament as finished
              </Label>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="col-span-full">
        <Field>
          <FieldLabel htmlFor={`${idPrefix}-date-range`}>
            Date range
            {mode === "manual-create" || mode === "challonge-create" ? requiredMark : null}
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
          <p className="mb-3 text-sm font-medium">Scoring points</p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor={`${idPrefix}-win-points`}>Win</Label>
              <NumberInput
                id={`${idPrefix}-win-points`}
                value={value.win_points ?? 0}
                onValueChange={(next) => onChange({ ...value, win_points: next ?? 0 })}
                className="mt-1.5 tabular-nums"
              />
            </div>
            <div>
              <Label htmlFor={`${idPrefix}-draw-points`}>Draw</Label>
              <NumberInput
                id={`${idPrefix}-draw-points`}
                value={value.draw_points ?? 0}
                onValueChange={(next) => onChange({ ...value, draw_points: next ?? 0 })}
                className="mt-1.5 tabular-nums"
              />
            </div>
            <div>
              <Label htmlFor={`${idPrefix}-loss-points`}>Loss</Label>
              <NumberInput
                id={`${idPrefix}-loss-points`}
                value={value.loss_points ?? 0}
                onValueChange={(next) => onChange({ ...value, loss_points: next ?? 0 })}
                className="mt-1.5 tabular-nums"
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
