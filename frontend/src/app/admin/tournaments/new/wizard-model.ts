// Pure model for the tournament creation wizard (/admin/tournaments/new).
// Pattern mirrors [id]/components/draft/setup-model.ts: a const step list,
// back-only navigation and per-step validation kept free of React.

import { getTournamentForm } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.helpers";
import type { TournamentFormFieldsValue } from "@/components/admin/tournaments/TournamentFormFields";
import type { SchedulablePhase } from "@/lib/tournament/lifecycle";
import type { TournamentCreateInput, TournamentUpdateInput } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";

export const WIZARD_STEPS = ["basics", "schedule", "rules", "registration", "review"] as const;

export type WizardStep = (typeof WIZARD_STEPS)[number];

export type WizardSource = "manual" | "challonge";

export interface WizardBasicsState {
  source: WizardSource;
  name: string;
  challongeSlug: string;
  startDate: string;
  endDate: string;
}

// UI state shared by page.tsx and the step components.

export type WizardFormData = TournamentFormFieldsValue & {
  name: string;
  description: string;
  is_league: boolean;
  start_date: string;
  end_date: string;
};

export interface WizardScheduleState {
  phase_schedule: Record<SchedulablePhase, { starts_at: string; ends_at: string }>;
  auto_transitions_enabled: boolean;
}

export interface WizardRegistrationState {
  auto_approve: boolean;
  require_open_profile: boolean;
  require_subscription: boolean;
}

/** Registration step is only offered to organizers who can manage teams (D17). */
export function visibleWizardSteps(canTeamImport: boolean): WizardStep[] {
  return WIZARD_STEPS.filter((step) => step !== "registration" || canTeamImport);
}

/** Basics is the only step that must be completed; everything else is optional. */
export function isWizardStepRequired(step: WizardStep): boolean {
  return step === "basics";
}

export function validateWizardStep(step: WizardStep, basics: WizardBasicsState): string[] {
  if (step !== "basics") return [];
  const errors: string[] = [];
  if (basics.source === "challonge") {
    if (!basics.challongeSlug.trim()) errors.push("challonge_slug_required");
  } else if (!basics.name.trim()) {
    errors.push("name_required");
  }
  if (!basics.startDate || !basics.endDate) errors.push("dates_required");
  return errors;
}

/** "Create now" (create with defaults for steps 2-4) unlocks once basics is valid. */
export function canCreateNow(basics: WizardBasicsState): boolean {
  return validateWizardStep("basics", basics).length === 0;
}

export function previousWizardStep(steps: WizardStep[], current: WizardStep): WizardStep {
  return steps[Math.max(0, steps.indexOf(current) - 1)];
}

export function nextWizardStep(steps: WizardStep[], current: WizardStep): WizardStep {
  return steps[Math.min(steps.length - 1, steps.indexOf(current) + 1)];
}

// ── Lazy Unpublished draft (D4) ──

/**
 * Steps whose entry needs a persisted tournament id: step 4 links the full
 * form builder (`…/{id}/registration/form`) and review publishes via PATCH.
 * "Create now" and "Review & Create" ensure the draft by construction.
 */
export function stepEntryRequiresDraft(step: WizardStep): boolean {
  return step === "registration" || step === "review";
}

/** POST payload for the lazy draft: current form state, always hidden. */
export function buildDraftCreateInput(
  workspaceId: number,
  form: WizardFormData
): TournamentCreateInput {
  return {
    workspace_id: workspaceId,
    name: form.name.trim(),
    description: form.description.trim() || undefined,
    is_league: form.is_league,
    slug: form.slug?.trim() || undefined,
    start_date: form.start_date,
    end_date: form.end_date,
    win_points: form.win_points,
    draw_points: form.draw_points,
    loss_points: form.loss_points,
    division_grid_version_id: form.division_grid_version_id ?? null,
    is_hidden: true
  };
}

/**
 * PATCH payload syncing the draft with the wizard state. `is_hidden` is only
 * touched when publishing (Review & Create); "Create now" leaves the draft
 * Unpublished — publication stays a deliberate act (Settings/Review).
 * The name is omitted when blank: Challonge-imported drafts own their name.
 */
export function buildDraftUpdateInput(
  form: WizardFormData,
  schedule: WizardScheduleState,
  { publish }: { publish: boolean }
): TournamentUpdateInput {
  const name = form.name.trim();
  const slug = form.slug?.trim();
  return {
    ...(name ? { name } : {}),
    ...(slug ? { slug } : {}),
    description: form.description.trim() || null,
    is_league: form.is_league,
    start_date: form.start_date,
    end_date: form.end_date,
    win_points: form.win_points,
    draw_points: form.draw_points,
    loss_points: form.loss_points,
    division_grid_version_id: form.division_grid_version_id ?? null,
    team_formation: form.team_formation,
    auto_transitions_enabled: schedule.auto_transitions_enabled,
    ...(publish ? { is_hidden: false } : {})
  };
}

/**
 * D4 resume: the latest Unpublished tournament of the current workspace that
 * has no stages yet (stages appear via Challonge import or the hub — such a
 * tournament is past wizard scope).
 */
export function findResumableDraft<
  T extends Pick<Tournament, "id" | "workspace_id" | "is_hidden" | "stages">
>(tournaments: readonly T[], workspaceId: number | null | undefined): T | null {
  if (!workspaceId) return null;
  let latest: T | null = null;
  for (const entry of tournaments) {
    if (!entry.is_hidden || entry.workspace_id !== workspaceId) continue;
    if ((entry.stages ?? []).length > 0) continue;
    if (!latest || entry.id > latest.id) latest = entry;
  }
  return latest;
}

/** Prefill the wizard from a resumed draft (dates/schedule in workspace time). */
export function wizardStateFromDraft(
  tournament: Tournament,
  timezone: string
): { form: WizardFormData; schedule: WizardScheduleState } {
  const state = getTournamentForm(tournament, timezone);
  return {
    form: {
      name: state.name,
      description: state.description,
      is_league: state.is_league,
      start_date: state.start_date,
      end_date: state.end_date,
      slug: state.slug,
      division_grid_version_id: state.division_grid_version_id,
      team_formation: state.team_formation,
      win_points: state.win_points,
      draw_points: state.draw_points,
      loss_points: state.loss_points
    },
    schedule: {
      phase_schedule: state.phase_schedule,
      auto_transitions_enabled: state.auto_transitions_enabled
    }
  };
}
