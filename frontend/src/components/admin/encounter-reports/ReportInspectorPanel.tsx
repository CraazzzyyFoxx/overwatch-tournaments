"use client";

import { encounterStatusKey } from "@/components/admin/encounters/EncounterCells";
import { InspectorField, InspectorSection } from "@/components/kit/InspectorField";
import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { useFormatter } from "@/lib/datetime/client";
import { useTranslations } from "next-intl";
import type { EncounterReportsRow } from "@/types/admin.types";
import type { ReportCustomFieldDefinition } from "@/types/encounter.types";

import { reportOf, scoreline } from "@/lib/encounter/reports";
import { seatsBySlot } from "@/lib/encounter/seats";

import { ReportDetail } from "./ReportDetail";
import { fmtDate } from "./report-model";

/**
 * One encounter's whole filing, not a summary of it: this is the surface an
 * admin adjudicates from, and a field left out here is a field they would have
 * to go find in the database. What the row and the inspector header already
 * say (teams, tournament, stage, filed count) is not repeated.
 */
export function ReportInspectorPanel({
  row,
  customFields
}: Readonly<{
  row: EncounterReportsRow;
  customFields: ReportCustomFieldDefinition[];
}>) {
  const format = useFormatter();
  const t = useTranslations("adminMatches.reports");
  const encounterT = useTranslations("adminMatches.encounters");
  const seats = seatsBySlot(row.participations);
  const seatIds = seats.map((seat) => seat.encounter_team_id);
  const status = encounterStatusKey(row.status);
  const result = (["none", "pending_confirmation", "confirmed", "disputed"] as const).find(
    (value) => value === row.result_status
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <InspectorField label={t("result")}>{result ? encounterT(`resultStatus.${result}`) : null}</InspectorField>
        <InspectorField label={t("status")}>{status ? encounterT(status) : null}</InspectorField>
        <InspectorField label={t("seriesCheck")}>
          {/* Advisory, not an error: reports predate per-round best-of. */}
          {row.series_score_valid ? (
            t("withinBo")
          ) : (
            <span className={TONE_TEXT.warning} title={t("outsideBoTitle")}>
              {t("outsideBo")}
            </span>
          )}
        </InspectorField>
      </div>

      {seats.map((seat) => {
        const report = reportOf(row.reports, seat.encounter_team_id);
        return (
          <ReportDetail
            key={seat.encounter_team_id}
            label={t("slot", { slot: seat.slot })}
            teamName={seat.name}
            standing={report ? scoreline(report.results, seatIds) : ""}
            report={report}
            replayCodes={row.replay_codes.filter((code) => code.encounter_team_id === seat.encounter_team_id)}
            customFields={customFields}
          />
        );
      })}

      {row.last_resolution ? (
        <InspectorSection title={t("lastResolution")}>
          <p className="text-sm">
            {t("resolutionBy", {
              action: t(`actions.${row.last_resolution.action}`),
              actor: row.last_resolution.actor_name ?? t("automatedProcess")
            })}
          </p>
          <p className="text-xs tabular-nums text-muted-foreground">{fmtDate(format, row.last_resolution.created_at)}</p>
        </InspectorSection>
      ) : null}
    </div>
  );
}
