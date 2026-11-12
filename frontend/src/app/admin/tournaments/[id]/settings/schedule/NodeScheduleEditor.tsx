"use client";

import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup } from "@/components/kit/SettingRow";
import { useScopedSettingsForm } from "@/components/kit/useScopedSettingsForm";
import { DateTimePicker } from "@/components/ui/date-picker";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { useWorkspaceTimezone } from "@/hooks/useWorkspaceTimezone";
import { SCHEDULE_PHASES } from "@/lib/tournament/lifecycle";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { utcToZonedInput, zonedInputToUtc } from "@/lib/workspace/timezone";
import adminService from "@/services/admin.service";
import type { FlowNodeScheduleEntry, TournamentFlowNode } from "@/types/flow.types";

type ScheduledKind = keyof typeof SCHEDULE_PHASES;
type Phase = (typeof SCHEDULE_PHASES)[ScheduledKind][number];
type PhaseTimes = { starts_at: string; ends_at: string };
type ScheduleForm = Partial<Record<Phase, PhaseTimes>>;

/**
 * The schedule of one lifecycle node: a start (and an optional end) for each phase its kind may schedule
 * (`SCHEDULE_PHASES`), entered in the workspace zone and saved whole by `PUT /admin/flow-nodes/{id}/schedule`.
 * The scheduler moves the node when a start arrives; an end only closes that phase's action window.
 * Remount it per node (`key={node.id}`): a pending edit belongs to the node it was typed into.
 */
export function NodeScheduleEditor({
  tournamentId,
  node,
  disabled = false
}: Readonly<{ tournamentId: number; node: TournamentFlowNode; disabled?: boolean }>) {
  const t = useTranslations("adminTournament.schedule");
  const client = useQueryClient();
  const timezone = useWorkspaceTimezone();
  const phases: readonly Phase[] = SCHEDULE_PHASES[node.kind as ScheduledKind];

  const baseline = useMemo<ScheduleForm>(
    () =>
      Object.fromEntries(
        phases.map((phase) => {
          const row = node.schedule.find((entry) => entry.phase === phase);
          return [
            phase,
            {
              starts_at: row ? utcToZonedInput(row.starts_at, timezone) : "",
              ends_at: row ? utcToZonedInput(row.ends_at, timezone) : ""
            }
          ];
        })
      ),
    [node, phases, timezone]
  );

  const { form, patch, dirty, summary, saving, save, discard, error } = useScopedSettingsForm<
    ScheduleForm,
    FlowNodeScheduleEntry[]
  >({
    baseline,
    // The whole schedule: the endpoint replaces it, and a phase with no start has no row.
    toPayload: (current) =>
      phases
        .filter((phase) => current[phase]?.starts_at)
        .map((phase) => ({
          phase,
          starts_at: zonedInputToUtc(current[phase]!.starts_at, timezone) ?? current[phase]!.starts_at,
          ends_at: zonedInputToUtc(current[phase]!.ends_at, timezone)
        })),
    countChanges: (_payload, current, base) =>
      phases.filter((phase) => JSON.stringify(current[phase]) !== JSON.stringify(base[phase])).length,
    submit: (payload) => adminService.setNodeSchedule(node.id, payload),
    onSaved: () => void invalidateTournamentWorkspace(client, tournamentId)
  });
  if (!form) return null;

  const setField = (phase: Phase, field: keyof PhaseTimes, value: string) =>
    patch({ [phase]: { ...form[phase], [field]: value } as PhaseTimes });

  return (
    <>
      <SettingGroup id={`schedule-node-${node.id}`} title={node.name}>
        {/* One header row instead of repeated label pairs, once the card fits two pickers side by side; narrower,
            each picker shows its own labels again. The card's body is the container. */}
        <div
          role="group"
          aria-label={`${t("aria")}: ${node.name}`}
          className="flex flex-col gap-4 @min-[48rem]:grid @min-[48rem]:grid-cols-[minmax(6rem,8rem)_1fr_1fr] @min-[48rem]:items-center @min-[48rem]:gap-x-4 @min-[48rem]:gap-y-3"
        >
          <div aria-hidden className="hidden @min-[48rem]:contents">
            <span />
            <span className={eyebrowClass("muted")}>{t("starts")}</span>
            <span className={eyebrowClass("muted")}>{t("ends")}</span>
          </div>

          {phases.map((phase) => {
            const label = t(`phases.${phase}`);
            return (
              <div key={phase} className="flex flex-col gap-2 @min-[48rem]:contents">
                <p className="text-xs font-medium text-foreground @min-[48rem]:py-1">{label}</p>
                <DateTimePicker
                  id={`schedule-${node.id}-${phase}-starts`}
                  timeId={`schedule-${node.id}-${phase}-starts-time`}
                  dateLabel={t("phaseStartsAt", { phase: label })}
                  timeLabel={t("phaseStartTime", { phase: label })}
                  labelClassName="@min-[48rem]:sr-only"
                  disabled={disabled}
                  value={form[phase]?.starts_at}
                  onChange={(next) => setField(phase, "starts_at", next)}
                />
                <DateTimePicker
                  id={`schedule-${node.id}-${phase}-ends`}
                  timeId={`schedule-${node.id}-${phase}-ends-time`}
                  dateLabel={t("phaseEndsAt", { phase: label })}
                  timeLabel={t("phaseEndTime", { phase: label })}
                  labelClassName="@min-[48rem]:sr-only"
                  disabled={disabled}
                  value={form[phase]?.ends_at}
                  onChange={(next) => setField(phase, "ends_at", next)}
                />
              </div>
            );
          })}
        </div>
      </SettingGroup>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
