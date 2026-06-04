"use client";

import type { DivisionGridVersion } from "@/types/workspace.types";
import { Checkbox } from "@/components/ui/checkbox";
import { DateTimePicker } from "@/components/ui/date-picker";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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
  registration_opens_at?: string | null;
  registration_closes_at?: string | null;
  check_in_opens_at?: string | null;
  check_in_closes_at?: string | null;
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
  const showPeriods = mode === "workspace-edit";
  const showTeamFormation =
    mode === "workspace-edit" || mode === "manual-create" || mode === "challonge-create";

  return (
    <div className="space-y-4">
      {showSeparateChallonge ? (
        <div>
          <Label htmlFor={`${idPrefix}-challonge-separate`}>Challonge URL or Slug *</Label>
          <Input
            id={`${idPrefix}-challonge-separate`}
            placeholder="e.g. my-tournament or https://challonge.com/my-tournament"
            value={challongeSlugValue ?? ""}
            onChange={(event) => onChallongeSlugValueChange?.(event.target.value)}
            required
          />
          <p className="mt-1 text-xs text-muted-foreground">
            The Challonge bracket must have group stages enabled (two-stage). All stages will be
            created automatically.
          </p>
        </div>
      ) : null}

      {mode !== "challonge-create" ? (
        <div>
          <Label htmlFor={`${idPrefix}-name`}>{mode === "manual-create" ? "Name *" : "Name"}</Label>
          <Input
            id={`${idPrefix}-name`}
            value={value.name}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            required={mode === "manual-create"}
          />
        </div>
      ) : null}

      {showNumber ? (
        <div>
          <Label htmlFor={`${idPrefix}-number`}>
            {mode === "challonge-create" ? "Number *" : "Number"}
          </Label>
          <Input
            id={`${idPrefix}-number`}
            type="number"
            value={value.number ?? ""}
            onChange={(event) =>
              onChange({
                ...value,
                number: event.target.value ? Number(event.target.value) : null,
              })
            }
            required={mode === "challonge-create"}
          />
        </div>
      ) : null}

      {showDescription ? (
        <div>
          <Label htmlFor={`${idPrefix}-description`}>Description</Label>
          <Textarea
            id={`${idPrefix}-description`}
            value={value.description ?? ""}
            onChange={(event) => onChange({ ...value, description: event.target.value })}
          />
        </div>
      ) : null}

      {showInlineChallonge ? (
        <div>
          <Label htmlFor={`${idPrefix}-challonge`}>Challonge URL or Slug</Label>
          <Input
            id={`${idPrefix}-challonge`}
            placeholder="e.g. my-tournament or https://challonge.com/my-tournament"
            value={value.challonge_slug ?? ""}
            onChange={(event) => onChange({ ...value, challonge_slug: event.target.value })}
          />
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        <Checkbox
          id={`${idPrefix}-is-league`}
          checked={value.is_league}
          onCheckedChange={(checked) => onChange({ ...value, is_league: checked === true })}
        />
        <Label htmlFor={`${idPrefix}-is-league`} className="cursor-pointer">
          {mode === "workspace-edit" ? "Treat as league season" : "Is League"}
        </Label>
      </div>

      {showTeamFormation ? (
        <div>
          <Label htmlFor={`${idPrefix}-team-formation`}>Team formation</Label>
          <Select
            value={value.team_formation ?? "balancer"}
            onValueChange={(nextValue) => onChange({ ...value, team_formation: nextValue })}
          >
            <SelectTrigger id={`${idPrefix}-team-formation`}>
              <SelectValue placeholder="Select method" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="balancer">Auto-balance (Balancer)</SelectItem>
              <SelectItem value="draft">Live draft</SelectItem>
            </SelectContent>
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">
            How teams are formed for this tournament.
          </p>
        </div>
      ) : null}

      {showFinished ? (
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${idPrefix}-is-finished`}
            checked={value.is_finished ?? false}
            onCheckedChange={(checked) => onChange({ ...value, is_finished: checked === true })}
          />
          <Label htmlFor={`${idPrefix}-is-finished`} className="cursor-pointer">
            {mode === "workspace-edit"
              ? "Mark tournament as finished"
              : "Is Finished"}
          </Label>
        </div>
      ) : null}

      <Field>
        <FieldLabel htmlFor={`${idPrefix}-date-range`}>
          {mode === "manual-create" || mode === "challonge-create" ? "Date Range *" : "Date Range"}
        </FieldLabel>
        <DateRangePicker
          id={`${idPrefix}-date-range`}
          startDate={value.start_date}
          endDate={value.end_date}
          onChange={(start, end) => onChange({ ...value, start_date: start, end_date: end })}
        />
      </Field>

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
            <SelectTrigger id={`${idPrefix}-division-grid-version`}>
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

      {showScoring ? (
        <div className="mt-4 border-t border-border/40 pt-4">
          <p className="mb-3 text-sm font-medium">Scoring Points</p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor={`${idPrefix}-win-points`}>Win</Label>
              <Input
                id={`${idPrefix}-win-points`}
                type="number"
                step="0.5"
                value={value.win_points ?? 0}
                onChange={(event) =>
                  onChange({ ...value, win_points: Number(event.target.value) })
                }
              />
            </div>
            <div>
              <Label htmlFor={`${idPrefix}-draw-points`}>Draw</Label>
              <Input
                id={`${idPrefix}-draw-points`}
                type="number"
                step="0.5"
                value={value.draw_points ?? 0}
                onChange={(event) =>
                  onChange({ ...value, draw_points: Number(event.target.value) })
                }
              />
            </div>
            <div>
              <Label htmlFor={`${idPrefix}-loss-points`}>Loss</Label>
              <Input
                id={`${idPrefix}-loss-points`}
                type="number"
                step="0.5"
                value={value.loss_points ?? 0}
                onChange={(event) =>
                  onChange({ ...value, loss_points: Number(event.target.value) })
                }
              />
            </div>
          </div>
        </div>
      ) : null}

      {showPeriods ? (
        <>
          <div className="mt-4 border-t border-border/40 pt-4">
            <p className="mb-3 text-sm font-medium">Registration Period</p>
            <div className="grid gap-3 xl:grid-cols-2">
              <DateTimePicker
                id={`${idPrefix}-registration-opens`}
                timeId={`${idPrefix}-registration-opens-time`}
                dateLabel="Opens at"
                timeLabel="Time"
                value={value.registration_opens_at ?? ""}
                onChange={(nextValue) => onChange({ ...value, registration_opens_at: nextValue })}
              />
              <DateTimePicker
                id={`${idPrefix}-registration-closes`}
                timeId={`${idPrefix}-registration-closes-time`}
                dateLabel="Closes at"
                timeLabel="Time"
                value={value.registration_closes_at ?? ""}
                onChange={(nextValue) => onChange({ ...value, registration_closes_at: nextValue })}
              />
            </div>
          </div>

          <div className="mt-4 border-t border-border/40 pt-4">
            <p className="mb-3 text-sm font-medium">Check-in Period</p>
            <div className="grid gap-3 xl:grid-cols-2">
              <DateTimePicker
                id={`${idPrefix}-check-in-opens`}
                timeId={`${idPrefix}-check-in-opens-time`}
                dateLabel="Opens at"
                timeLabel="Time"
                value={value.check_in_opens_at ?? ""}
                onChange={(nextValue) => onChange({ ...value, check_in_opens_at: nextValue })}
              />
              <DateTimePicker
                id={`${idPrefix}-check-in-closes`}
                timeId={`${idPrefix}-check-in-closes-time`}
                dateLabel="Closes at"
                timeLabel="Time"
                value={value.check_in_closes_at ?? ""}
                onChange={(nextValue) => onChange({ ...value, check_in_closes_at: nextValue })}
              />
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
