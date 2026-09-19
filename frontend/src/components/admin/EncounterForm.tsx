"use client";

import { useId } from "react";
import { Star } from "lucide-react";

import { TeamCombobox } from "@/components/admin/TeamCombobox";
import { buildEncounterName } from "@/components/admin/encounter-name";
import { isGroupStageScoreContext } from "@/lib/encounter-score";
import { EncounterScoreControls } from "@/components/tournaments/EncounterScoreControls";
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
import type {
  EncounterCreateInput,
  EncounterEditableStatus,
  EncounterUpdateInput
} from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { Stage } from "@/types/tournament.types";

/**
 * One editable encounter, in the shape the form holds it.
 *
 * `status` is `EncounterEditableStatus`, not `string`: `COMPLETED` belongs to
 * the result endpoint, which moves score, status, result_status and the audit
 * row together. The hub's old copy typed it `string` and cast on submit, which
 * meant a lowercase `"open"` reached a backend that only answers to `OPEN`.
 */
export interface EncounterFormState {
  name: string;
  stage_id: number | null;
  stage_item_id: number | null;
  home_team_id: number | null;
  away_team_id: number | null;
  round: number;
  home_score: number;
  away_score: number;
  status: EncounterEditableStatus;
  /** 0..1; `null` when nobody rated the match. Editable only on an existing row. */
  closeness: number | null;
}

export type EncounterFormMode = "create" | "edit";

const EDITABLE_STATUSES: readonly EncounterEditableStatus[] = ["OPEN", "PENDING"];

/**
 * What a form may submit. `COMPLETED` is not editable, so an encounter that
 * already finished opens as `OPEN` rather than offering a value the backend
 * would reject.
 */
export function editableEncounterStatus(status?: string | null): EncounterEditableStatus {
  const upper = status?.toUpperCase();
  return EDITABLE_STATUSES.includes(upper as EncounterEditableStatus)
    ? (upper as EncounterEditableStatus)
    : "OPEN";
}

export function emptyEncounterForm(
  defaultStageId: number | null,
  defaultStageItemId: number | null
): EncounterFormState {
  return {
    name: "",
    stage_id: defaultStageId,
    stage_item_id: defaultStageItemId,
    home_team_id: null,
    away_team_id: null,
    round: 1,
    home_score: 0,
    away_score: 0,
    status: "OPEN",
    closeness: null
  };
}

export function encounterFormOf(encounter: Encounter): EncounterFormState {
  return {
    name: encounter.name,
    stage_id: encounter.stage_id ?? null,
    stage_item_id: encounter.stage_item_id ?? null,
    home_team_id: encounter.home_team_id,
    away_team_id: encounter.away_team_id,
    round: encounter.round,
    home_score: encounter.score.home,
    away_score: encounter.score.away,
    status: editableEncounterStatus(encounter.status),
    closeness: encounter.closeness
  };
}

/** The one blocking message, or `null` when the form may be submitted. */
export function encounterFormError(form: EncounterFormState): string | null {
  if (!form.name.trim()) return "Enter an encounter name.";
  if (form.stage_id == null) return "Select a stage before saving the encounter.";
  if (
    form.home_team_id != null &&
    form.away_team_id != null &&
    form.home_team_id === form.away_team_id
  ) {
    return "Pick two different teams.";
  }
  return null;
}

export function encounterCreatePayload(
  form: EncounterFormState,
  tournamentId: number
): EncounterCreateInput {
  return {
    name: form.name.trim(),
    tournament_id: tournamentId,
    stage_id: form.stage_id,
    stage_item_id: form.stage_item_id,
    home_team_id: form.home_team_id,
    away_team_id: form.away_team_id,
    round: form.round,
    home_score: form.home_score,
    away_score: form.away_score,
    status: form.status
  };
}

export function encounterUpdatePayload(form: EncounterFormState): EncounterUpdateInput {
  return {
    name: form.name.trim(),
    stage_id: form.stage_id,
    stage_item_id: form.stage_item_id,
    home_team_id: form.home_team_id,
    away_team_id: form.away_team_id,
    round: form.round,
    home_score: form.home_score,
    away_score: form.away_score,
    status: form.status,
    closeness: form.closeness
  };
}

function closenessToStars(closeness: number | null): number {
  if (closeness == null || closeness <= 0) return 0;
  return Math.max(1, Math.min(5, Math.round(closeness * 5)));
}

/**
 * The encounter fields, for both create and edit.
 *
 * There used to be two copies of this — one in the cross-tournament browser,
 * one in the hub tab — which had already drifted: only one of them kept
 * `stage_id` in step with the stage item, only one derived the encounter name
 * from the two teams, and they disagreed on the casing of `status`. `mode` is
 * the whole difference that remains: closeness is a rating of a match that has
 * been played, so it has nothing to rate on a row being created.
 */
export function EncounterForm({
  mode,
  value,
  onChange,
  stages,
  teams
}: Readonly<{
  mode: EncounterFormMode;
  value: EncounterFormState;
  onChange: (next: EncounterFormState) => void;
  stages: Stage[];
  teams: Team[];
}>) {
  const prefix = useId();
  const stage = stages.find((entry) => entry.id === value.stage_id) ?? null;
  const stageItem = stage?.items.find((item) => item.id === value.stage_item_id) ?? null;
  const isGroupStage = isGroupStageScoreContext(stage, stageItem);
  const stars = closenessToStars(value.closeness);

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor={`${prefix}-name`}>Encounter name *</Label>
        <Input
          id={`${prefix}-name`}
          value={value.name}
          placeholder="e.g. Quarter Final 1"
          onChange={(event) => onChange({ ...value, name: event.target.value })}
        />
      </div>

      <div>
        <Label htmlFor={`${prefix}-stage`}>Stage *</Label>
        <Select
          value={value.stage_id?.toString() ?? ""}
          onValueChange={(next) => {
            const picked = stages.find((entry) => entry.id === Number(next)) ?? null;
            // Picking a stage moves the item with it: a stage item belonging to
            // another stage is a row the backend cannot place.
            onChange({
              ...value,
              stage_id: picked?.id ?? null,
              stage_item_id: picked?.items[0]?.id ?? null
            });
          }}
        >
          <SelectTrigger id={`${prefix}-stage`}>
            <SelectValue placeholder="Select stage" />
          </SelectTrigger>
          <SelectContent>
            {stages.map((entry) => (
              <SelectItem key={entry.id} value={entry.id.toString()}>
                {entry.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label htmlFor={`${prefix}-stage-item`}>Stage item</Label>
        <Select
          value={value.stage_item_id?.toString() ?? "none"}
          onValueChange={(next) => {
            const stageItemId = next === "none" ? null : Number(next);
            const owner =
              stageItemId == null
                ? null
                : (stages.find((entry) => entry.items.some((item) => item.id === stageItemId)) ??
                  null);
            onChange({
              ...value,
              stage_id: owner?.id ?? value.stage_id,
              stage_item_id: stageItemId
            });
          }}
        >
          <SelectTrigger id={`${prefix}-stage-item`}>
            <SelectValue placeholder="Select stage item" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">No stage item</SelectItem>
            {(stage?.items ?? []).map((item) => (
              <SelectItem key={item.id} value={item.id.toString()}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <Label htmlFor={`${prefix}-home`}>Home team</Label>
          <TeamCombobox
            id={`${prefix}-home`}
            teams={teams}
            value={value.home_team_id}
            placeholder="Select home team"
            onSelect={(team) => {
              const homeTeamId = team?.id ?? null;
              onChange({
                ...value,
                name: buildEncounterName(teams, homeTeamId, value.away_team_id),
                home_team_id: homeTeamId
              });
            }}
          />
        </div>
        <div>
          <Label htmlFor={`${prefix}-away`}>Away team</Label>
          <TeamCombobox
            id={`${prefix}-away`}
            teams={teams}
            value={value.away_team_id}
            placeholder="Select away team"
            onSelect={(team) => {
              const awayTeamId = team?.id ?? null;
              onChange({
                ...value,
                name: buildEncounterName(teams, value.home_team_id, awayTeamId),
                away_team_id: awayTeamId
              });
            }}
          />
        </div>
      </div>

      <div>
        <Label htmlFor={`${prefix}-round`}>Round *</Label>
        <NumberInput
          id={`${prefix}-round`}
          integer
          value={value.round}
          onValueChange={(next) => onChange({ ...value, round: next ?? 1 })}
        />
      </div>

      <EncounterScoreControls
        idPrefix={`${prefix}-score`}
        homeScore={value.home_score}
        awayScore={value.away_score}
        presetLabel={isGroupStage ? "Group stage presets" : "Result presets"}
        showGroupStageHint={isGroupStage}
        onScoreChange={(score) =>
          onChange({ ...value, home_score: score.homeScore, away_score: score.awayScore })
        }
      />

      <div>
        <Label htmlFor={`${prefix}-status`}>Status</Label>
        <Select
          value={value.status}
          onValueChange={(next) =>
            onChange({ ...value, status: next as EncounterEditableStatus })
          }
        >
          <SelectTrigger id={`${prefix}-status`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="OPEN">Open</SelectItem>
            <SelectItem value="PENDING">Pending</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {mode === "edit" ? (
        <div role="group" aria-label="Match closeness">
          <p className="text-sm font-medium leading-none">Match closeness</p>
          <div className="mt-2 flex items-center gap-1">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                className="p-1"
                aria-label={`Rate closeness ${star} of 5`}
                aria-pressed={star <= stars}
                onClick={() =>
                  onChange({
                    ...value,
                    // Clicking the current rating clears it, which is the only
                    // way back to "not rated" once a star has been set.
                    closeness: star === stars ? null : star / 5
                  })
                }
              >
                <Star
                  aria-hidden
                  className={
                    star <= stars ? "size-6 fill-warning text-warning" : "size-6 text-muted-foreground"
                  }
                />
              </button>
            ))}
            <span className="ml-2 text-sm tabular-nums text-muted-foreground">
              {stars > 0 ? `${stars}/5` : "Not set"}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
