"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Gavel, Pencil, Upload } from "lucide-react";

import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { TournamentLogUploadDialog } from "@/app/admin/tournaments/[id]/components/TournamentLogUploadDialog";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import adminService from "@/services/admin.service";
import type { AdminMatchRow } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";

import { EncounterStatusCell, InspectorField } from "./EncounterCells";

/**
 * What the row detail adds to the table: the captains' filings and the maps a
 * parser has already read, both fetched only for the row actually open.
 */
export function EncounterInspectorPanel({
  encounter,
  workspaceId
}: Readonly<{
  encounter: Encounter;
  workspaceId: number;
}>) {
  const reportsQuery = useQuery({
    queryKey: encounterQueryKeys.reportsByEncounter(encounter.id, workspaceId),
    queryFn: () =>
      adminService.listEncounterReports({
        workspace_id: workspaceId,
        tournament_id: encounter.tournament_id,
        query: encounter.name,
        per_page: 25
      })
  });
  const reportRow = reportsQuery.data?.results.find((row) => row.id === encounter.id) ?? null;

  const parsedMapsQuery = useQuery({
    queryKey: adminQueryKeys.matchEncounter(encounter.id, workspaceId),
    queryFn: () =>
      adminService.listAdminMatches({
        workspace_id: workspaceId,
        encounter_id: encounter.id,
        per_page: 25
      })
  });

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <InspectorField label="Teams">
          <span className="flex items-center gap-1.5">
            <TeamName team={encounter.home_team} fallback="TBD" size="xs" />
            <span className="text-muted-foreground">vs</span>
            <TeamName team={encounter.away_team} fallback="TBD" size="xs" />
          </span>
        </InspectorField>
        <InspectorField label="Score">
          <span className="font-mono tabular-nums">
            {encounter.score.home} &ndash; {encounter.score.away}
          </span>
        </InspectorField>
        <InspectorField label="Status">
          <EncounterStatusCell status={encounter.status} />
        </InspectorField>
        <InspectorField label="Result">{encounter.result_status}</InspectorField>
        <InspectorField label="Best of">
          <span className="tabular-nums">{encounter.best_of}</span>
        </InspectorField>
        <InspectorField label="Logs">{encounter.has_logs ? "Attached" : "None"}</InspectorField>
      </div>

      <section className="rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Captain reports</p>
        {reportsQuery.isLoading ? (
          <p className="mt-2 text-xs text-muted-foreground">Loading…</p>
        ) : reportRow == null ? (
          <p className="mt-2 text-xs text-muted-foreground">
            No captain has reported this encounter.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {(
              [
                ["Home", reportRow.home_report],
                ["Away", reportRow.away_report]
              ] as const
            ).map(([side, report]) => (
              <li key={side} className="flex items-center gap-2">
                <span className="w-12 text-xs uppercase text-muted-foreground">{side}</span>
                {report ? (
                  <>
                    <span className="font-mono tabular-nums">
                      {report.home_score} &ndash; {report.away_score}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      {report.reporter_name ?? "unknown"}
                    </span>
                  </>
                ) : (
                  <span className="text-xs italic text-muted-foreground">no report</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Parsed maps ({parsedMapsQuery.data?.total ?? 0})</p>
        {parsedMapsQuery.isLoading ? (
          <p className="mt-2 text-xs text-muted-foreground">Loading…</p>
        ) : (parsedMapsQuery.data?.results.length ?? 0) === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            No map has been parsed for this encounter yet.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {(parsedMapsQuery.data?.results ?? []).map((map: AdminMatchRow) => (
              <li key={map.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{map.map_name}</span>
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {map.home_score}&ndash;{map.away_score}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** The header actions of the same row: every write an admin can start from it. */
export function EncounterInspectorActions({
  encounter,
  workspaceId,
  canUpdate,
  reportsHref,
  onEdit,
  onUploaded
}: Readonly<{
  encounter: Encounter;
  workspaceId: number;
  canUpdate: boolean;
  /** Where the captain reports view lives for this scope. */
  reportsHref: string;
  onEdit: (encounter: Encounter) => void;
  onUploaded: () => void;
}>) {
  return (
    <>
      {canUpdate ? (
        <Button variant="outline" size="sm" onClick={() => onEdit(encounter)}>
          <Pencil aria-hidden className="size-3.5" />
          Edit
        </Button>
      ) : null}
      {canUpdate ? (
        <TournamentLogUploadDialog
          tournamentId={encounter.tournament_id}
          encounters={[encounter]}
          initialEncounterId={encounter.id}
          onUploaded={onUploaded}
          trigger={
            <Button variant="outline" size="sm">
              <Upload aria-hidden className="size-3.5" />
              Upload log
            </Button>
          }
        />
      ) : null}
      {canUpdate ? (
        <Button asChild variant="outline" size="sm">
          {/* The captain reports view owns resolution: score, status,
              result_status and the audit row move together there. */}
          <Link
            href={`${reportsHref}${reportsHref.includes("?") ? "&" : "?"}search=${encodeURIComponent(encounter.name)}&id=${encounter.id}`}
          >
            <Gavel aria-hidden className="size-3.5" />
            Resolve result
          </Link>
        </Button>
      ) : null}
      <AuditTrailButton
        scope={{ entityType: "encounter", entityId: encounter.id, workspaceId }}
        target={encounter.name}
      />
    </>
  );
}
