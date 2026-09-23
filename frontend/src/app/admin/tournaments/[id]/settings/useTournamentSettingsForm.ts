"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { DEFAULT_WORKSPACE_TIMEZONE } from "@/lib/workspace/timezone";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { TournamentUpdateInput } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";
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

export interface TournamentSettingsForm {
  form: TournamentFormState;
  /** Merges a partial into the form; the only way a section mutates it. */
  patch: (values: Partial<TournamentFormState>) => void;
  dirty: boolean;
  /** "2 changed fields" for the `SaveBar` summary. */
  summary: string;
  saving: boolean;
  /** The PATCH body this section would send right now — the diff, scoped. */
  payload: TournamentUpdateInput;
  save: () => void;
  discard: () => void;
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

  const initial = useMemo(
    () => getTournamentForm(tournament, timezone),
    [tournament, timezone]
  );
  const [form, setForm] = useState<TournamentFormState>(initial);

  // Re-baseline when the tournament changes under us (another admin's write
  // arriving through the shell's realtime invalidation, or the zone loading in).
  // Done during render, not in an effect: `initial` is derived from props, so an
  // effect would first commit a render whose `dirty`/`payload` compare the new
  // baseline against the old form and briefly report phantom changed fields.
  const [baseline, setBaseline] = useState(initial);
  if (baseline !== initial) {
    setBaseline(initial);
    setForm(initial);
  }

  const payload = useMemo(() => {
    const diff = getTournamentUpdatePayload(form, initial);
    const scoped: TournamentUpdateInput = {};
    for (const field of SETTINGS_SECTION_FIELDS[section]) {
      if (field in diff) {
        (scoped as Record<string, unknown>)[field] = (diff as Record<string, unknown>)[field];
      }
    }
    return scoped;
  }, [form, initial, section]);

  const scheduleChanged =
    section === "schedule" &&
    JSON.stringify(form.phase_schedule) !== JSON.stringify(initial.phase_schedule);

  const mutation = useMutation({
    mutationFn: async () => {
      if (Object.keys(payload).length > 0) {
        await adminService.updateTournament(tournamentId, payload);
      }
      if (scheduleChanged) {
        await adminService.setTournamentSchedule(
          tournamentId,
          getPhaseSchedulePayload(form.phase_schedule, timezone)
        );
      }
    },
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success("Settings saved");
    },
    onError: (error) => notify.apiError(error, { title: "Could not save these settings" })
  });

  const changedCount = Object.keys(payload).length + (scheduleChanged ? 1 : 0);
  const patch = useCallback(
    (values: Partial<TournamentFormState>) => setForm((current) => ({ ...current, ...values })),
    []
  );
  const discard = useCallback(() => setForm(initial), [initial]);

  return {
    form,
    patch,
    dirty: changedCount > 0,
    summary:
      changedCount === 1
        ? "1 changed field"
        : `${changedCount} changed fields`,
    saving: mutation.isPending,
    payload,
    save: () => mutation.mutate(),
    discard,
    timezone
  };
}
