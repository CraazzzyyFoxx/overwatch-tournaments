"use client";

import { useTranslations } from "next-intl";

import { DateRangePicker } from "@/components/ui/date-range-picker";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Switch } from "@/components/ui/switch";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { getUtcOffsetLabel } from "@/lib/workspace/timezone";
import {
  SCHEDULABLE_PHASES,
  type SchedulablePhase
} from "@/lib/tournament/lifecycle";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

export default function ScheduleSettingsPage() {
  return (
    <SettingsSectionPage section="schedule">
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
  const tStatus = useTranslations("common.statusBadge");
  const t = useTranslations("adminTournament.schedule");
  const { form, patch, dirty, summary, saving, save, discard, timezone, error } =
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
      <div className="flex flex-col gap-4">
        <SettingGroup id="dates" title={t("dates")}>
          <SettingRow htmlFor="settings-date-range" label={t("duration")} stacked>
            <DateRangePicker
              id="settings-date-range"
              startDate={form.start_date}
              endDate={form.end_date}
              onChange={(start, end) => patch({ start_date: start, end_date: end })}
            />
          </SettingRow>
        </SettingGroup>

        <SettingGroup
          id="phases"
          title={t("title")}
          description={
            <>
              {t("hint")}
              <span className="mt-1 block font-medium text-foreground/80">
                {t("timezoneLabel", { label: t("timezone"), timezone, offset: getUtcOffsetLabel(timezone) })}
              </span>
            </>
          }
        >
          {/* One header row instead of four repeated label pairs. Stacked
              below lg, where each picker shows its own labels again. */}
          <div
            role="group"
            aria-label={t("aria")}
            className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(6rem,8rem)_1fr_1fr] lg:items-center lg:gap-x-4 lg:gap-y-3"
          >
            <div aria-hidden className="hidden lg:contents">
              <span />
              <span className={eyebrowClass("muted")}>{t("starts")}</span>
              <span className={eyebrowClass("muted")}>{t("ends")}</span>
            </div>

            {visiblePhases.map((phase) => (
              <div key={phase} className="flex flex-col gap-2 lg:contents">
                <p className="text-xs font-medium text-foreground lg:py-1">
                  {tStatus(phase)}
                </p>
                <DateTimePicker
                  id={`settings-phase-${phase}-starts`}
                  timeId={`settings-phase-${phase}-starts-time`}
                  dateLabel={`${tStatus(phase)} starts at`}
                  timeLabel={`${tStatus(phase)} start time`}
                  labelClassName="lg:sr-only"
                  value={form.phase_schedule[phase].starts_at}
                  onChange={(next) => setPhaseField(phase, "starts_at", next)}
                />
                <DateTimePicker
                  id={`settings-phase-${phase}-ends`}
                  timeId={`settings-phase-${phase}-ends-time`}
                  dateLabel={`${tStatus(phase)} ends at (optional)`}
                  timeLabel={`${tStatus(phase)} end time`}
                  labelClassName="lg:sr-only"
                  value={form.phase_schedule[phase].ends_at}
                  onChange={(next) => setPhaseField(phase, "ends_at", next)}
                />
              </div>
            ))}
          </div>
        </SettingGroup>

        <SettingGroup id="automation" title={t("automation")}>
          <SettingRow
            htmlFor="settings-auto-transitions"
            label={t("automatic")}
            hint={t("automaticHint")}
          >
            <Switch
              id="settings-auto-transitions"
              checked={form.auto_transitions_enabled}
              disabled={disabled}
              onCheckedChange={(checked) => patch({ auto_transitions_enabled: checked })}
            />
          </SettingRow>
        </SettingGroup>
      </div>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
