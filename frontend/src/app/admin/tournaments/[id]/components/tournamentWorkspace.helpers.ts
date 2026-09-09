import type { Tournament, TournamentStatus } from "@/types/tournament.types";
import type { Tone } from "@/components/admin/tone";
import type { TournamentPhaseScheduleEntryInput, TournamentUpdateInput } from "@/types/admin.types";
import { utcToZonedInput, zonedInputToUtc } from "@/lib/timezone";
import {
  SCHEDULABLE_PHASES,
  isSchedulablePhase,
  type SchedulablePhase
} from "@/lib/tournament-lifecycle";
import type { RosterSlotMap } from "@/lib/roster-shape";
import { normalizeSlots } from "@/components/roster-shape/roster-shape-editor.model";
import { normalizeChallongeSlug } from "@/lib/challonge";

export type PhaseScheduleFormState = Record<
  SchedulablePhase,
  { starts_at: string; ends_at: string }
>;

export type TournamentFormState = {
  name: string;
  description: string;
  challonge_slug: string;
  // Public-URL slug (`/tournaments/<slug>`); renaming it redirects the old link.
  slug: string;
  is_league: boolean;
  is_finished: boolean;
  is_hidden: boolean;
  start_date: string;
  end_date: string;
  win_points: number;
  draw_points: number;
  loss_points: number;
  auto_transitions_enabled: boolean;
  allow_late_registration: boolean;
  phase_schedule: PhaseScheduleFormState;
  division_grid_version_id: number | null;
  team_formation: string;
  /**
   * Roster shape override; `null` = inherit. Normalized on the way in so the
   * tab's `JSON.stringify` dirty check does not trip over key order.
   */
  roster_slots_json: RosterSlotMap | null;
};

export const TOURNAMENT_DETAIL_PREVIEW_LIMIT = 8;

export function formatDate(value?: Date | string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}

/**
 * Tone of the hub header's status pill.
 *
 * Statuses are not qualities, so this is not a good/bad scale: `live` is the
 * one that wants attention, a finished tournament is neutral, everything
 * before kickoff is informational. A `Record` rather than a `switch` with a
 * default, so a new lifecycle status is a compile error here instead of
 * silently rendering grey.
 */
export const TOURNAMENT_STATUS_TONE: Record<TournamentStatus, Tone> = {
  announcement: "info",
  registration: "info",
  check_in: "info",
  draft: "info",
  live: "danger",
  playoffs: "danger",
  completed: "success",
  archived: "neutral"
};

function toDateInput(value?: Date | string | null) {
  if (!value) return "";
  return new Date(value).toISOString().split("T")[0] ?? "";
}

function getPhaseScheduleForm(
  tournament: Tournament,
  timezone: string
): PhaseScheduleFormState {
  const schedule = Object.fromEntries(
    SCHEDULABLE_PHASES.map((phase) => [phase, { starts_at: "", ends_at: "" }])
  ) as PhaseScheduleFormState;

  for (const row of tournament.phase_schedule ?? []) {
    if (isSchedulablePhase(row.status)) {
      schedule[row.status] = {
        starts_at: utcToZonedInput(row.starts_at, timezone),
        ends_at: utcToZonedInput(row.ends_at, timezone)
      };
    }
  }

  return schedule;
}

export function getPhaseSchedulePayload(
  schedule: PhaseScheduleFormState,
  timezone: string
): TournamentPhaseScheduleEntryInput[] {
  return SCHEDULABLE_PHASES.filter((phase) => schedule[phase].starts_at).map((phase) => ({
    status: phase,
    starts_at: zonedInputToUtc(schedule[phase].starts_at, timezone) ?? schedule[phase].starts_at,
    ends_at: zonedInputToUtc(schedule[phase].ends_at, timezone)
  }));
}

export function getTournamentForm(tournament: Tournament, timezone: string): TournamentFormState {
  return {
    name: tournament.name,
    description: tournament.description ?? "",
    challonge_slug: tournament.challonge_slug ?? "",
    slug: tournament.slug,
    is_league: tournament.is_league,
    is_finished: tournament.is_finished,
    is_hidden: tournament.is_hidden ?? false,
    start_date: toDateInput(tournament.start_date),
    end_date: toDateInput(tournament.end_date),
    win_points: tournament.win_points ?? 1,
    draw_points: tournament.draw_points ?? 0.5,
    loss_points: tournament.loss_points ?? 0,
    auto_transitions_enabled: tournament.auto_transitions_enabled ?? true,
    allow_late_registration: tournament.allow_late_registration ?? false,
    phase_schedule: getPhaseScheduleForm(tournament, timezone),
    division_grid_version_id: tournament.division_grid_version_id ?? null,
    team_formation: tournament.team_formation ?? "balancer",
    roster_slots_json: tournament.roster_slots_json
      ? normalizeSlots(tournament.roster_slots_json)
      : null
  };
}

// Every field `TournamentUpdateInput` can carry, keyed the same as
// `TournamentFormState` (minus `phase_schedule`, which travels through
// `setTournamentSchedule` instead). Kept in one place so the diff below and
// `getTournamentForm` above cannot drift out of sync field-by-field.
type TournamentUpdateValues = Required<Omit<TournamentUpdateInput, "description" | "challonge_slug" | "division_grid_version_id" | "roster_slots_json">> & {
  description: string | null;
  challonge_slug: string | null;
  division_grid_version_id: number | null;
  roster_slots_json: RosterSlotMap | null;
};

function normalizeTournamentFormValues(form: TournamentFormState): TournamentUpdateValues {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    challonge_slug: form.challonge_slug ? normalizeChallongeSlug(form.challonge_slug) : null,
    // Blank is a no-op on the backend (see update_tournament), not a clear.
    slug: form.slug.trim() || null,
    is_league: form.is_league,
    is_finished: form.is_finished,
    is_hidden: form.is_hidden,
    start_date: form.start_date,
    end_date: form.end_date,
    win_points: form.win_points,
    draw_points: form.draw_points,
    loss_points: form.loss_points,
    auto_transitions_enabled: form.auto_transitions_enabled,
    allow_late_registration: form.allow_late_registration,
    division_grid_version_id: form.division_grid_version_id,
    team_formation: form.team_formation,
    roster_slots_json: form.roster_slots_json
  };
}

/**
 * Diffs the (normalized) current form against the (normalized) initial form
 * and keeps only the fields that actually changed. The admin audit trail
 * records exactly the keys a PATCH sends (`TournamentUpdate.model_dump(exclude_unset=True)`
 * on the backend), so sending every field on every save -- even ones the
 * admin never touched -- made every edit look like a full rewrite of the
 * tournament in the audit log.
 */
export function getTournamentUpdatePayload(
  current: TournamentFormState,
  initial: TournamentFormState
): TournamentUpdateInput {
  const next = normalizeTournamentFormValues(current);
  const prev = normalizeTournamentFormValues(initial);
  const payload: TournamentUpdateInput = {};
  for (const key of Object.keys(next) as (keyof TournamentUpdateValues)[]) {
    if (JSON.stringify(next[key]) !== JSON.stringify(prev[key])) {
      (payload as Record<string, unknown>)[key] = next[key];
    }
  }
  return payload;
}
