"use client";

import { useTranslations } from "next-intl";

import { DateRangePicker } from "@/components/ui/date-range-picker";
import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { useWorkspaceTimezone } from "@/hooks/useWorkspaceTimezone";
import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import { getUtcOffsetLabel } from "@/lib/workspace/timezone";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";
import { NodeScheduleEditor } from "./NodeScheduleEditor";

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
  const t = useTranslations("adminTournament.schedule");
  const timezone = useWorkspaceTimezone();
  const { form, patch, dirty, summary, saving, save, discard, error } =
    useTournamentSettingsForm(tournament, tournamentId, "schedule");

  // The lifecycle nodes in the order a tournament runs them; a leaderboard has no schedule.
  const nodes = (["registration", "formation", "stage"] as const).flatMap((kind) =>
    nodesOfKind(tournament, kind)
  );

  return (
    <>
      <div className="flex flex-col gap-4">
        <SettingsGrid>
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

          {nodes.length === 0 ? (
            <SettingGroup id="phases" title={t("title")}>
              <p className="text-caption text-muted-foreground">{t("noNodes")}</p>
            </SettingGroup>
          ) : null}
        </SettingsGrid>

        {nodes.length > 0 ? (
          <>
            {/* Said once for every node below, not repeated in each card. */}
            <p className="max-w-prose text-xs text-muted-foreground">
              {t("hint")}
              <span className="mt-1 block font-medium text-foreground/80">
                {t("timezoneLabel", { label: t("timezone"), timezone, offset: getUtcOffsetLabel(timezone) })}
              </span>
            </p>
            {/* A grid, not `SettingsGrid`: each editor carries its own sticky `SaveBar`, and a wrapper each keeps
                them from stacking; the cards are alike in height, so rows leave no holes. */}
            <div className="grid grid-cols-[repeat(auto-fill,minmax(min(36rem,100%),1fr))] items-start gap-4">
              {nodes.map((node) => (
                <div key={node.id}>
                  <NodeScheduleEditor tournamentId={tournamentId} node={node} disabled={disabled} />
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
