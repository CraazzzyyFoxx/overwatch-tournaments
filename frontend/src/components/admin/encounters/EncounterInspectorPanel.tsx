"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import { InspectorField, InspectorSection } from "@/components/kit/InspectorField";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LogUploadDialog } from "@/components/logs/LogUploadDialog";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { pregameRoomHref } from "@/lib/encounter/pregame-room";
import adminService from "@/services/admin.service";
import type { AdminMatchRow } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import { reportOf, scoreline } from "@/lib/encounter/reports";
import { scoreLine } from "@/lib/encounter/detail";
import { mapWithModeName } from "@/lib/catalog/mode";
import { isLobby, seatsBySlot } from "@/lib/encounter/seats";

/**
 * What the row detail adds to the table: the captains' filings and the maps a
 * parser has already read, both fetched only for the row actually open. The
 * row's own columns (score, status, result, logs) are not repeated here.
 */
export function EncounterInspectorPanel({
  encounter,
  workspaceId
}: Readonly<{
  encounter: Encounter;
  workspaceId: number;
}>) {
  const t = useTranslations("adminMatches.encounters");
  const commonT = useTranslations("adminMatches.common");
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

  const seats = seatsBySlot(encounter.teams);
  const seatIds = seats.map((seat) => seat.id);

  return (
    <div className="space-y-4">
      <InspectorField label={t("bestOf")}>
        <span className="tabular-nums">{encounter.best_of}</span>
      </InspectorField>

      <InspectorSection title={t("captainReports")}>
        {reportsQuery.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : reportRow == null ? (
          <p className="text-xs text-muted-foreground">{t("noCaptainReport")}</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {seats.map((seat) => {
              const report = reportOf(reportRow.reports, seat.id);
              return (
                <li key={seat.id} className="flex items-center gap-2">
                  <span className="w-24 truncate text-xs text-muted-foreground" title={seat.name}>
                    {seat.name}
                  </span>
                  {report ? (
                    <>
                      <span className="tabular-nums">{scoreline(report.results, seatIds)}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {report.reporter_name ?? commonT("unknown")}
                      </span>
                    </>
                  ) : (
                    <span className="text-xs text-muted-foreground">{commonT("noReport")}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </InspectorSection>

      <InspectorSection title={t("parsedMaps", { count: parsedMapsQuery.data?.total ?? 0 })}>
        {parsedMapsQuery.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : (parsedMapsQuery.data?.results.length ?? 0) === 0 ? (
          <p className="text-xs text-muted-foreground">{t("noParsedMap")}</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {(parsedMapsQuery.data?.results ?? []).map((map: AdminMatchRow) => (
              <li key={map.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{mapWithModeName(map.map, map.mode)}</span>
                <span className="text-xs tabular-nums text-muted-foreground">{scoreLine(map.participants)}</span>
              </li>
            ))}
          </ul>
        )}
      </InspectorSection>
    </div>
  );
}

/** The header actions of the same row: every write an admin can start from it. */
export function EncounterInspectorActions({
  encounter,
  workspaceId,
  canUpdate,
  reportsHref,
  returnTo,
  onEdit,
  onUploaded
}: Readonly<{
  encounter: Encounter;
  workspaceId: number;
  canUpdate: boolean;
  /** Where the captain reports view lives for this scope. */
  reportsHref: string;
  /** Where the pre-game room hands the organizer back — this list, as filtered. */
  returnTo: string;
  onEdit: (encounter: Encounter) => void;
  onUploaded: () => void;
}>) {
  const t = useTranslations("adminMatches.encounters");
  return (
    <>
      {isLobby(encounter) ? null : (
        <Button asChild variant="outline" size="sm">
          {/* Readiness, the veto and the per-map reports all live in the room,
              and the organizer controls there are the same ones a captain
              cannot reach. */}
          <Link href={pregameRoomHref(encounter.tournament_id, encounter.id, returnTo)}>{t("openRoom")}</Link>
        </Button>
      )}
      {canUpdate ? (
        <Button variant="outline" size="sm" onClick={() => onEdit(encounter)}>
          {t("edit")}
        </Button>
      ) : null}
      {canUpdate ? (
        <LogUploadDialog
          scope={{ tournamentId: encounter.tournament_id, encounterId: encounter.id }}
          encounters={[encounter]}
          onUploaded={onUploaded}
          trigger={
            <Button variant="outline" size="sm">
              {t("uploadLog")}
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
            {t("resolve")}
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
