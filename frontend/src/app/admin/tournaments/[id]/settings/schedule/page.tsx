"use client";

import { Card, CardContent } from "@/components/ui/card";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Field, FieldLabel } from "@/components/ui/field";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { SaveBar } from "@/components/kit/SaveBar";
import { getUtcOffsetLabel } from "@/lib/timezone";
import {
  SCHEDULABLE_PHASES,
  TOURNAMENT_STATUS_LABELS,
  type SchedulablePhase
} from "@/lib/tournament-lifecycle";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

export default function ScheduleSettingsPage() {
  return (
    <SettingsSectionPage
      section="schedule"
      description="Operational dates, the registration and check-in windows, and automatic phase transitions."
    >
      {({ tournament, tournamentId, canUpdateTournament }) => (
        <ScheduleForm
          tournament={tournament}
          tournamentId={tournamentId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function ScheduleForm({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const { form, patch, dirty, summary, saving, save, discard, timezone } =
    useTournamentSettingsForm(tournament, tournamentId, "schedule");

  const setPhaseField = (
    phase: SchedulablePhase,
    field: "starts_at" | "ends_at",
    nextValue: string
  ) =>
    patch({
      phase_schedule: {
        ...form.phase_schedule,
        [phase]: { ...form.phase_schedule[phase], [field]: nextValue }
      }
    });

  const visiblePhases = SCHEDULABLE_PHASES.filter(
    (phase) => phase !== "draft" || form.team_formation === "draft"
  );

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          <Field>
            <FieldLabel htmlFor="settings-date-range" className="font-normal text-foreground">
              Tournament duration range
            </FieldLabel>
            <DateRangePicker
              id="settings-date-range"
              startDate={form.start_date}
              endDate={form.end_date}
              onChange={(start, end) => patch({ start_date: start, end_date: end })}
            />
          </Field>

          <section className="flex flex-col gap-4 border-t border-border pt-4">
            <div>
              <h2 className={EYEBROW_CLASS}>Phase schedule</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Each phase starts automatically at its start time when automatic transitions are
                enabled. An end time only closes that phase&apos;s action window early — it never
                changes the tournament status.
              </p>
              <p className="mt-1 text-xs font-medium text-foreground/80">
                Time zone: {timezone} ({getUtcOffsetLabel(timezone)})
              </p>
            </div>

            {/* One header row instead of four repeated label pairs. Stacked
                below lg, where each picker shows its own labels again. */}
            <div
              role="group"
              aria-label="Phase schedule"
              className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(6rem,8rem)_1fr_1fr] lg:items-center lg:gap-x-4 lg:gap-y-3"
            >
              <div aria-hidden className="hidden lg:contents">
                <span />
                <span className={EYEBROW_CLASS}>Starts at</span>
                <span className={EYEBROW_CLASS}>Ends at (optional)</span>
              </div>

              {visiblePhases.map((phase) => (
                <div key={phase} className="flex flex-col gap-2 lg:contents">
                  <p className="text-xs font-medium text-foreground lg:py-1">
                    {TOURNAMENT_STATUS_LABELS[phase]}
                  </p>
                  <DateTimePicker
                    id={`settings-phase-${phase}-starts`}
                    timeId={`settings-phase-${phase}-starts-time`}
                    dateLabel={`${TOURNAMENT_STATUS_LABELS[phase]} starts at`}
                    timeLabel={`${TOURNAMENT_STATUS_LABELS[phase]} start time`}
                    labelClassName="lg:sr-only"
                    value={form.phase_schedule[phase].starts_at}
                    onChange={(next) => setPhaseField(phase, "starts_at", next)}
                  />
                  <DateTimePicker
                    id={`settings-phase-${phase}-ends`}
                    timeId={`settings-phase-${phase}-ends-time`}
                    dateLabel={`${TOURNAMENT_STATUS_LABELS[phase]} ends at (optional)`}
                    timeLabel={`${TOURNAMENT_STATUS_LABELS[phase]} end time`}
                    labelClassName="lg:sr-only"
                    value={form.phase_schedule[phase].ends_at}
                    onChange={(next) => setPhaseField(phase, "ends_at", next)}
                  />
                </div>
              ))}
            </div>
          </section>

          <div className="flex flex-col gap-4 rounded-lg border border-border bg-muted/20 p-3.5">
            <div className="flex items-center justify-between gap-4">
              <div className="flex flex-col gap-0.5">
                <Label htmlFor="settings-auto-transitions" className="cursor-pointer">
                  Automatic phase transitions
                </Label>
                <p className="text-xs text-muted-foreground">
                  Re-enabling immediately catches up any overdue phases. Manual status changes
                  switch this off.
                </p>
              </div>
              <Switch
                id="settings-auto-transitions"
                checked={form.auto_transitions_enabled}
                disabled={disabled}
                onCheckedChange={(checked) => patch({ auto_transitions_enabled: checked })}
              />
            </div>

            <div className="flex items-center justify-between gap-4 border-t border-border pt-4">
              <div className="flex flex-col gap-0.5">
                <Label htmlFor="settings-allow-late-registration" className="cursor-pointer">
                  Allow late registration
                </Label>
                <p className="text-xs text-muted-foreground">
                  Keeps sign-ups open past the registration window&apos;s end time, so the
                  advertised closing date stays on the page. Does not open registration that never
                  started, and never reopens a finished tournament.
                </p>
                {!form.phase_schedule.registration.ends_at && (
                  <p className="text-xs text-warning">
                    No end time is set on the registration window above, so registration is already
                    open-ended and this changes nothing.
                  </p>
                )}
              </div>
              <Switch
                id="settings-allow-late-registration"
                checked={form.allow_late_registration}
                disabled={disabled}
                onCheckedChange={(checked) => patch({ allow_late_registration: checked })}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
