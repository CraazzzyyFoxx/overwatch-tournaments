"use client";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  SCHEDULABLE_PHASES,
  TOURNAMENT_STATUS_LABELS,
  type SchedulablePhase
} from "@/lib/tournament/lifecycle";

import type { WizardScheduleState } from "../wizard-model";

interface ScheduleStepProps {
  value: WizardScheduleState;
  onChange: (next: WizardScheduleState) => void;
  showDraftPhase: boolean;
}

export function ScheduleStep({ value, onChange, showDraftPhase }: Readonly<ScheduleStepProps>) {
  const visiblePhases = SCHEDULABLE_PHASES.filter(
    (phase) => phase !== "draft" || showDraftPhase
  );

  const setPhaseField = (
    phase: SchedulablePhase,
    field: "starts_at" | "ends_at",
    nextValue: string
  ) =>
    onChange({
      ...value,
      phase_schedule: {
        ...value.phase_schedule,
        [phase]: { ...value.phase_schedule[phase], [field]: nextValue }
      }
    });

  return (
    <div className="space-y-5">
      <div>
        <h3 className={EYEBROW_CLASS}>Phase schedule</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Each phase starts automatically at its start time when automatic transitions are
          enabled. Leave a phase empty to skip scheduling it.
        </p>
      </div>

      {visiblePhases.map((phase) => (
        <div key={phase} className="space-y-2">
          <h4 className="text-xs font-medium text-foreground">{TOURNAMENT_STATUS_LABELS[phase]}</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <DateTimePicker
              id={`wizard-phase-${phase}-starts`}
              timeId={`wizard-phase-${phase}-starts-time`}
              dateLabel="Starts at"
              timeLabel="Time"
              value={value.phase_schedule[phase].starts_at}
              onChange={(nextValue) => setPhaseField(phase, "starts_at", nextValue)}
            />
            <DateTimePicker
              id={`wizard-phase-${phase}-ends`}
              timeId={`wizard-phase-${phase}-ends-time`}
              dateLabel="Ends at (optional)"
              timeLabel="Time"
              value={value.phase_schedule[phase].ends_at}
              onChange={(nextValue) => setPhaseField(phase, "ends_at", nextValue)}
            />
          </div>
        </div>
      ))}

      <div className="flex flex-col gap-4 bg-muted/20 border border-border/50 rounded-lg p-3.5">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <Label htmlFor="wizard-auto-transitions" className="cursor-pointer text-sm font-medium">
              Automatic phase transitions
            </Label>
            <p className="text-xs text-muted-foreground">
              Phases advance on their own following the schedule above.
            </p>
          </div>
          <Switch
            id="wizard-auto-transitions"
            checked={value.auto_transitions_enabled}
            onCheckedChange={(checked) =>
              onChange({ ...value, auto_transitions_enabled: checked })
            }
          />
        </div>

        {/* No "allow late registration": registration openness is the
            REGISTRATION window above, and late registration is simply an
            `ends_at` that reaches past the LIVE start. */}
      </div>
    </div>
  );
}
