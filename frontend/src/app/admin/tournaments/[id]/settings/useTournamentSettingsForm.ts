"use client";

import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import { DEFAULT_WORKSPACE_TIMEZONE } from "@/lib/workspace/timezone";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { TournamentUpdateInput } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";
import {
  useScopedSettingsForm,
  type ScopedSettingsForm
} from "@/components/admin/settings/useScopedSettingsForm";
import {
  getPhaseSchedulePayload,
  getTournamentForm,
  getTournamentUpdatePayload,
  type TournamentFormState
} from "../components/tournamentWorkspace.helpers";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";

/**
 * Which tournament fields each settings section owns.
 *
 * The point of the table is the negative: a section saves its own fields and
 * nothing else. One 714-line form used to PATCH every field it held on every
 * save, so editing the tournament name recorded a full rewrite of the rules,
 * the schedule and the scoring in the audit trail
 * (`TournamentUpdate.model_dump(exclude_unset=True)` records exactly the keys
 * a PATCH sends).
 *
 * `phase_schedule` is not here: it travels through `setTournamentSchedule`,
 * and only the `schedule` section sends it.
 */
export const SETTINGS_SECTION_FIELDS = {
  // How teams form and which grid seeds them are read on every screen that
  // describes the tournament, so they sit with its name rather than with the
  // points a result is worth.
  general: ["name", "slug", "description", "team_formation", "division_grid_version_id"],
  // One field, and deliberately alone: the published document is the section.
  // Saving the scoring must not rewrite it in the audit trail, nor the reverse.
  rules: ["rules"],
  scoring: ["is_league", "is_finished", "win_points", "draw_points", "loss_points"],
  schedule: ["start_date", "end_date", "auto_transitions_enabled", "allow_late_registration"],
  roster: ["roster_slots_json"],
  challonge: ["challonge_slug"],
  discord: ["discord_broadcasts_enabled", "discord_dms_enabled"],
  preview: ["is_hidden"]
} as const satisfies Record<string, readonly (keyof TournamentUpdateInput)[]>;

export type SettingsFormSection = keyof typeof SETTINGS_SECTION_FIELDS;

export interface TournamentSettingsForm
  extends ScopedSettingsForm<TournamentFormState, TournamentUpdateInput> {
  /** Never `null`: the tournament is loaded before a section mounts. */
  form: TournamentFormState;
  payload: TournamentUpdateInput;
  /** Zone the schedule section enters and shows times in; storage stays UTC. */
  timezone: string;
}

/**
 * Form state of one settings section, and the scoped diff it saves.
 *
 * Every section shares this hook, so "what changed" is computed once and each
 * page only decides which controls to render for it.
 */
export function useTournamentSettingsForm(
  tournament: Tournament,
  tournamentId: number,
  section: SettingsFormSection
): TournamentSettingsForm {
  const queryClient = useQueryClient();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const timezone =
    workspaces.find((workspace) => workspace.id === tournament.workspace_id)?.timezone ??
    DEFAULT_WORKSPACE_TIMEZONE;

  const baseline = useMemo(
    () => getTournamentForm(tournament, timezone),
    [tournament, timezone]
  );

  // The schedule travels through its own endpoint, so it is neither in the
  // PATCH body nor in its key count — but the save bar still has to see it.
  const scheduleChanged = (form: TournamentFormState, base: TournamentFormState) =>
    section === "schedule" &&
    JSON.stringify(form.phase_schedule) !== JSON.stringify(base.phase_schedule);

  const settings = useScopedSettingsForm<TournamentFormState, TournamentUpdateInput>({
    baseline,
    toPayload: (form, base) => {
      const diff = getTournamentUpdatePayload(form, base);
      const scoped: TournamentUpdateInput = {};
      for (const field of SETTINGS_SECTION_FIELDS[section]) {
        if (field in diff) {
          (scoped as Record<string, unknown>)[field] = (diff as Record<string, unknown>)[field];
        }
      }
      return scoped;
    },
    countChanges: (payload, form, base) =>
      Object.keys(payload).length + (scheduleChanged(form, base) ? 1 : 0),
    submit: async (payload, form, base) => {
      if (Object.keys(payload).length > 0) {
        await adminService.updateTournament(tournamentId, payload);
      }
      if (scheduleChanged(form, base)) {
        await adminService.setTournamentSchedule(
          tournamentId,
          getPhaseSchedulePayload(form.phase_schedule, timezone)
        );
      }
    },
    onSaved: () => invalidateTournamentWorkspace(queryClient, tournamentId)
  });

  return {
    ...settings,
    // The generic hook only reports `null` before its entity loads; here the
    // tournament is a prop, so the baseline is the value of the very first
    // render.
    form: settings.form ?? baseline,
    payload: settings.payload ?? {},
    timezone
  };
}
