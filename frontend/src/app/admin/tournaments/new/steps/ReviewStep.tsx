"use client";

import { useRequirementDescription } from "@/components/admin/subscriptions/useRequirementDescription";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { SCHEDULABLE_PHASES, TOURNAMENT_STATUS_LABELS } from "@/lib/tournament-lifecycle";
import type { SubscriptionRequirement } from "@/types/registration.types";
import type { DivisionGridVersion } from "@/types/workspace.types";

import type {
  WizardFormData,
  WizardRegistrationState,
  WizardScheduleState,
  WizardSource
} from "../wizard-model";

interface ReviewStepProps {
  source: WizardSource;
  challongeSlug: string;
  form: WizardFormData;
  schedule: WizardScheduleState;
  registration: WizardRegistrationState;
  registrationVisible: boolean;
  divisionGridVersions: DivisionGridVersion[];
  /** The workspace-wide rule, fetched by the page alongside the division grids.
   *  The wizard no longer carries one: a tournament only chooses whether to
   *  enforce what the workspace already decided. */
  subscriptionRequirement: SubscriptionRequirement | undefined;
}

/** Same labels the Rules step offers, so the summary cannot rename a choice.
 *  A ternary here used to read every non-draft formation as "Auto-balance". */
const TEAM_FORMATION_LABELS: Record<string, string> = {
  balancer: "Auto-balance (Balancer)",
  draft: "Live draft",
  registration: "Team registration"
};

function Row({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/30 py-2 last:border-b-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-right text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

export function ReviewStep({
  source,
  challongeSlug,
  form,
  schedule,
  registration,
  registrationVisible,
  divisionGridVersions,
  subscriptionRequirement
}: Readonly<ReviewStepProps>) {
  const requirementRule = useRequirementDescription(subscriptionRequirement);
  const gridLabel =
    form.division_grid_version_id == null
      ? "Workspace default"
      : (divisionGridVersions.find((version) => version.id === form.division_grid_version_id)
          ?.label ?? `#${form.division_grid_version_id}`);
  const scheduledPhases = SCHEDULABLE_PHASES.filter(
    (phase) => schedule.phase_schedule[phase].starts_at
  );

  return (
    <div className="space-y-6">
      <section>
        <h3 className={`mb-1 ${EYEBROW_CLASS}`}>Basics</h3>
        <dl>
          <Row label="Source" value={source === "challonge" ? "From Challonge" : "Manual"} />
          {source === "challonge" ? (
            <Row label="Challonge URL or slug" value={challongeSlug || "—"} />
          ) : (
            <Row label="Name" value={form.name || "—"} />
          )}
          <Row label="Date range" value={`${form.start_date || "—"} → ${form.end_date || "—"}`} />
          <Row label="Treat as league season" value={form.is_league ? "Yes" : "No"} />
        </dl>
      </section>

      <section>
        <h3 className={`mb-1 ${EYEBROW_CLASS}`}>Schedule</h3>
        <dl>
          {scheduledPhases.length === 0 && <Row label="Phase schedule" value="Not configured" />}
          {scheduledPhases.map((phase) => (
            <Row
              key={phase}
              label={TOURNAMENT_STATUS_LABELS[phase]}
              value={`${schedule.phase_schedule[phase].starts_at}${
                schedule.phase_schedule[phase].ends_at
                  ? ` → ${schedule.phase_schedule[phase].ends_at}`
                  : ""
              }`}
            />
          ))}
          <Row
            label="Automatic phase transitions"
            value={schedule.auto_transitions_enabled ? "On" : "Off"}
          />
        </dl>
      </section>

      <section>
        <h3 className={`mb-1 ${EYEBROW_CLASS}`}>Rules</h3>
        <dl>
          <Row
            label="Team formation"
            value={TEAM_FORMATION_LABELS[form.team_formation ?? "balancer"] ?? form.team_formation}
          />
          <Row label="Division grid version" value={gridLabel} />
          <Row
            label="Scoring points (win / draw / loss)"
            value={`${form.win_points ?? 1} / ${form.draw_points ?? 0.5} / ${form.loss_points ?? 0}`}
          />
        </dl>
      </section>

      {registrationVisible && (
        <section>
          <h3 className={`mb-1 ${EYEBROW_CLASS}`}>Registration</h3>
          <p className="mb-2 text-xs text-muted-foreground">
            These choices are not applied automatically — finish them in the form builder
            (Registration tab of the hub) after creation.
          </p>
          <dl>
            <Row
              label="Auto-approve registrations"
              value={registration.auto_approve ? "On" : "Off"}
            />
            <Row
              label="Require open profile"
              value={registration.require_open_profile ? "Yes" : "No"}
            />
            {/* The composed workspace rule, not a bare Yes/No: an organizer
                reviewing the draft needs to see what the toggle will enforce. */}
            <Row
              label="Require subscription"
              value={
                registration.require_subscription
                  ? requirementRule || "On — but the workspace has no rule configured"
                  : "No"
              }
            />
          </dl>
        </section>
      )}
    </div>
  );
}
