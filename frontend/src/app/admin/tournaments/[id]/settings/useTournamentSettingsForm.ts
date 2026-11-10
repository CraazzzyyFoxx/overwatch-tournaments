"use client";

import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import type { TournamentUpdateInput } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";
import {
  useScopedSettingsForm,
  type ScopedSettingsForm
} from "@/components/kit/useScopedSettingsForm";
import {
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
 */
const SETTINGS_SECTION_FIELDS = {
  // The grid that seeds the tournament is read on every screen that describes it, so it sits with its name.
  // The results flags share the section: finishing a tournament is a fact about it, not a scoring rule.
  general: ["name", "slug", "description", "division_grid_version_id", "is_finished", "logs_official"],
  // One field, and deliberately alone: the published document is the section.
  // Saving the rules must not rewrite the results flags in the audit trail, nor the reverse.
  rules: ["rules"],
  schedule: ["start_date", "end_date", "auto_transitions_enabled"],
  challonge: ["challonge_slug"],
  // Sits beside the stream links: the delay the rules require of a POV stream.
  links: ["pov_stream_delay_s"],
  discord: ["discord_broadcasts_enabled", "discord_dms_enabled"],
  preview: ["is_hidden"]
} as const satisfies Record<string, readonly (keyof TournamentUpdateInput)[]>;

export type SettingsFormSection = keyof typeof SETTINGS_SECTION_FIELDS;

export interface TournamentSettingsForm
  extends ScopedSettingsForm<TournamentFormState, TournamentUpdateInput> {
  /** Never `null`: the tournament is loaded before a section mounts. */
  form: TournamentFormState;
  payload: TournamentUpdateInput;
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

  const baseline = useMemo(() => getTournamentForm(tournament), [tournament]);

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
    submit: async (payload) => {
      if (Object.keys(payload).length > 0) {
        await adminService.updateTournament(tournamentId, payload);
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
    payload: settings.payload ?? {}
  };
}
