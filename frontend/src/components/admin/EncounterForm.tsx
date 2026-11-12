"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { TeamCombobox } from "@/components/admin/TeamCombobox";
import { buildEncounterName } from "@/components/admin/encounter-name";
import { duelSeats } from "@/lib/encounter/seats";
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
  /** The team seated in slot 1 / slot 2. Chosen at creation; a seat changes hands through the slot swap. */
  first_team_id: number | null;
  second_team_id: number | null;
  round: number;
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
function editableEncounterStatus(status?: string | null): EncounterEditableStatus {
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
    first_team_id: null,
    second_team_id: null,
    round: 1,
    status: "OPEN",
    closeness: null
  };
}

export function encounterFormOf(encounter: Encounter): EncounterFormState {
  const [first, second] = duelSeats(encounter.teams);
  return {
    name: encounter.name,
    stage_id: encounter.stage_id ?? null,
    stage_item_id: encounter.stage_item_id ?? null,
    first_team_id: first?.team_id ?? null,
    second_team_id: second?.team_id ?? null,
    round: encounter.round,
    status: editableEncounterStatus(encounter.status),
    closeness: encounter.closeness
  };
}

/** The one blocking message, or `null` when the form may be submitted. */
export function encounterFormError(form: EncounterFormState): string | null {
  if (!form.name.trim()) return "enterName";
  if (form.stage_id == null) return "selectStageBefore";
  if (
    form.first_team_id != null &&
    form.second_team_id != null &&
    form.first_team_id === form.second_team_id
  ) {
    return "differentTeams";
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
    // Only the seats a team was picked for: an empty seat is filled later.
    teams: [form.first_team_id, form.second_team_id].flatMap((teamId, index) =>
      teamId == null ? [] : [{ slot: index + 1, team_id: teamId }]
    ),
    round: form.round,
    status: form.status
  };
}

export function encounterUpdatePayload(form: EncounterFormState): EncounterUpdateInput {
  return {
    name: form.name.trim(),
    stage_id: form.stage_id,
    stage_item_id: form.stage_item_id,
    round: form.round,
    status: form.status,
    closeness: form.closeness
  };
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
  const t = useTranslations("adminMatches.form");
  const prefix = useId();
  const stage = stages.find((entry) => entry.id === value.stage_id) ?? null;

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor={`${prefix}-name`}>{t("name")}</Label>
        <Input
          id={`${prefix}-name`}
          value={value.name}
          placeholder={t("namePlaceholder")}
          onChange={(event) => onChange({ ...value, name: event.target.value })}
        />
      </div>

      <div>
        <Label htmlFor={`${prefix}-stage`}>{t("stageRequired")}</Label>
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
            <SelectValue placeholder={t("selectStage")} />
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
        <Label htmlFor={`${prefix}-stage-item`}>{t("stageItem")}</Label>
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
            <SelectValue placeholder={t("selectStageItem")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">{t("noStageItem")}</SelectItem>
            {(stage?.items ?? []).map((item) => (
              <SelectItem key={item.id} value={item.id.toString()}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {mode === "create" ? (
        // A seat changes hands through the slot swap, not through a field edit,
        // so the teams are chosen once, here.
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <Label htmlFor={`${prefix}-first`}>{t("firstTeam")}</Label>
            <TeamCombobox
              id={`${prefix}-first`}
              teams={teams}
              value={value.first_team_id}
              placeholder={t("selectFirst")}
              onSelect={(team) => {
                const firstTeamId = team?.id ?? null;
                onChange({
                  ...value,
                  name: buildEncounterName(teams, firstTeamId, value.second_team_id),
                  first_team_id: firstTeamId
                });
              }}
            />
          </div>
          <div>
            <Label htmlFor={`${prefix}-second`}>{t("secondTeam")}</Label>
            <TeamCombobox
              id={`${prefix}-second`}
              teams={teams}
              value={value.second_team_id}
              placeholder={t("selectSecond")}
              onSelect={(team) => {
                const secondTeamId = team?.id ?? null;
                onChange({
                  ...value,
                  name: buildEncounterName(teams, value.first_team_id, secondTeamId),
                  second_team_id: secondTeamId
                });
              }}
            />
          </div>
        </div>
      ) : null}

      <div>
        <Label htmlFor={`${prefix}-round`}>{t("round")}</Label>
        <NumberInput
          id={`${prefix}-round`}
          integer
          value={value.round}
          onValueChange={(next) => onChange({ ...value, round: next ?? 1 })}
        />
      </div>

      <div>
        <Label htmlFor={`${prefix}-status`}>{t("status")}</Label>
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
            <SelectItem value="OPEN">{t("open")}</SelectItem>
            <SelectItem value="PENDING">{t("pending")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {mode === "edit" ? (
        // The same 1–10 scale captains report on, so the two read alike.
        <div>
          <Label htmlFor={`${prefix}-closeness`}>{t("closeness")}</Label>
          <div className="flex items-center gap-2">
            <NumberInput
              id={`${prefix}-closeness`}
              integer
              min={1}
              max={10}
              className="w-20"
              value={value.closeness == null ? null : Math.round(value.closeness * 10)}
              onValueChange={(next) => onChange({ ...value, closeness: next == null ? null : next / 10 })}
            />
            <span className="text-sm text-muted-foreground">/10</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
