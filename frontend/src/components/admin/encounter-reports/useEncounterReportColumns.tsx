"use client";

import { useMemo, type ReactNode } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { adminColumnMeta } from "@/components/data-table";
import { AdminReportPairCell } from "@/components/admin/AdminReportPairCell";
import { StatusPill } from "@/components/kit/StatusPill";
import { TONE_TEXT } from "@/components/kit/tone";
import type { DateFormatter } from "@/components/kit/format-time";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { AdminCaptainReport, EncounterReportsRow } from "@/types/admin.types";
import type { ReportCustomFieldDefinition } from "@/types/encounter.types";

import { DASH, fmtDate, mapCodes, submittedAt } from "./report-model";

/**
 * One field of both reports, home over away.
 *
 * Every added column compares the two sides, and a column that showed one side
 * would hide exactly the disagreement an admin opened the table to find.
 */
function SidesCell({ home, away }: Readonly<{ home: ReactNode; away: ReactNode }>) {
  return (
    <div className="space-y-0.5 text-xs">
      <p className="truncate">
        <span className="mr-1 text-muted-foreground">H</span>
        {home}
      </p>
      <p className="truncate">
        <span className="mr-1 text-muted-foreground">A</span>
        {away}
      </p>
    </div>
  );
}

/** A column reading one string off each report, blank rendered as an em dash. */
function sidesColumn(
  id: string,
  header: string,
  read: (report: AdminCaptainReport | null) => string,
  meta: Parameters<typeof adminColumnMeta<EncounterReportsRow>>[0]
): ColumnDef<EncounterReportsRow> {
  return {
    id,
    header,
    // The endpoint sorts on none of these, so a sort control would be a lie.
    enableSorting: false,
    cell: ({ row }) => {
      const home = read(row.original.home_report);
      const away = read(row.original.away_report);
      return (
        <SidesCell
          home={<span title={home || undefined}>{home || DASH}</span>}
          away={<span title={away || undefined}>{away || DASH}</span>}
        />
      );
    },
    meta: adminColumnMeta<EncounterReportsRow>(meta)
  };
}

/**
 * The dispute table's columns: what both captains said, side by side, plus the
 * recorded state the admin is about to change.
 *
 * Only the first handful are on by default — the rest answer the second
 * question ("who filed that, and when"), and a table that opened with twenty
 * columns answered none of them.
 */
export function useEncounterReportColumns({
  showTournament,
  customFields
}: Readonly<{
  /** The scope is wider than one tournament, so each row must name its own. */
  showTournament: boolean;
  /** Organizer-defined questions, one hidden column each. */
  customFields: ReportCustomFieldDefinition[];
}>): ColumnDef<EncounterReportsRow>[] {
  const format: DateFormatter = useFormatter();

  return useMemo<ColumnDef<EncounterReportsRow>[]>(
    () => [
      {
        id: "encounter",
        header: "Encounter",
        // The server sorts none of these, so offering a sort control would be a
        // lie the header cannot honour.
        enableSorting: false,
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[18rem]">
            <p className="truncate font-medium text-foreground" title={row.original.name}>
              {row.original.name}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {showTournament ? `${row.original.tournament_name ?? "Unknown tournament"} · ` : ""}
              {row.original.stage_name ?? "Unassigned"} · Round {row.original.round} · BO
              {row.original.best_of}
            </p>
          </div>
        ),
        // The one column that names the row: hiding it would leave a table of
        // anonymous numbers, so the picker renders it checked and disabled.
        meta: adminColumnMeta<EncounterReportsRow>({ category: "core", mandatory: true })
      },
      {
        id: "teams",
        header: "Recorded teams",
        enableSorting: false,
        cell: ({ row }) => (
          <p className="max-w-[16rem] truncate text-xs text-muted-foreground">
            {row.original.home_team?.name ?? "?"} vs {row.original.away_team?.name ?? "?"}
          </p>
        ),
        meta: adminColumnMeta<EncounterReportsRow>({ category: "core" })
      },
      {
        id: "reports",
        header: "Captain reports",
        size: 320,
        enableSorting: false,
        cell: ({ row }) => (
          <AdminReportPairCell
            homeReport={row.original.home_report}
            awayReport={row.original.away_report}
            scoresMatch={row.original.scores_match}
            seriesScoreValid={row.original.series_score_valid}
          />
        ),
        meta: adminColumnMeta<EncounterReportsRow>({ category: "core" })
      },
      // Match quality decides seeding and prize splits in some formats, so it
      // is on by default rather than buried in the picker: the reason to open
      // this table at all is often "how close were these".
      sidesColumn(
        "closeness",
        "Closeness",
        (report) =>
          report == null || report.closeness == null ? "" : `${report.closeness}/10`,
        { category: "core", numeric: true, className: "min-w-[86px]" }
      ),
      {
        id: "result",
        header: "Result",
        size: 132,
        enableSorting: false,
        cell: ({ row }) => (
          <div className="space-y-1">
            <StatusPill tone={row.original.result_status === "disputed" ? "danger" : "neutral"}>
              {row.original.result_status}
            </StatusPill>
            {row.original.last_resolution ? (
              <p className="text-xs text-muted-foreground">
                {row.original.last_resolution.action} by{" "}
                {row.original.last_resolution.actor_name ?? "an automated process"}
              </p>
            ) : null}
          </div>
        ),
        meta: adminColumnMeta<EncounterReportsRow>({ category: "core" })
      },
      {
        id: "reported_count",
        header: "Filed",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-xs tabular-nums">{row.original.reported_count}/2</span>
        ),
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "meta",
          defaultHidden: true,
          align: "center",
          numeric: true
        })
      },
      {
        id: "scheduled_at",
        header: "Scheduled",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-xs tabular-nums">{fmtDate(format, row.original.scheduled_at)}</span>
        ),
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "meta",
          defaultHidden: true,
          responsive: "lg",
          className: "min-w-[150px]"
        })
      },
      sidesColumn("reporters", "Reported by", (report) => report?.reporter_name ?? "", {
        category: "meta",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[140px]"
      }),
      sidesColumn("submitted", "Submitted", (report) => {
        const at = submittedAt(report);
        return at ? format.dateTime(new Date(at), { dateStyle: "medium", timeStyle: "short" }) : "";
      }, {
        category: "meta",
        defaultHidden: true,
        responsive: "lg",
        numeric: true,
        className: "min-w-[150px]"
      }),
      sidesColumn(
        "scores",
        "Reported score",
        (report) => (report ? `${report.home_score} – ${report.away_score}` : ""),
        { category: "meta", defaultHidden: true, numeric: true, className: "min-w-[100px]" }
      ),
      sidesColumn("map_codes", "Lobby codes", mapCodes, {
        category: "meta",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[180px] max-w-[240px]"
      }),
      sidesColumn("comments", "Comments", (report) => report?.comment ?? "", {
        category: "meta",
        defaultHidden: true,
        responsive: "lg",
        className: "min-w-[200px] max-w-[280px]"
      }),
      {
        id: "series_score_valid",
        header: "Series check",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.series_score_valid ? (
            <span className="text-xs text-muted-foreground">ok</span>
          ) : (
            // Advisory, not an error: reports predate per-round best-of.
            <span className={cn("text-xs", TONE_TEXT.warning)} title="A reported score is impossible for this encounter's best-of">
              outside BO
            </span>
          ),
        meta: adminColumnMeta<EncounterReportsRow>({ category: "meta", defaultHidden: true })
      },
      {
        id: "status",
        header: "Encounter status",
        enableSorting: false,
        cell: ({ row }) => <span className="text-xs">{row.original.status}</span>,
        meta: adminColumnMeta<EncounterReportsRow>({ category: "meta", defaultHidden: true })
      },
      {
        id: "stage",
        header: "Stage",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-xs">{row.original.stage_name ?? "Unassigned"}</span>
        ),
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "meta",
          defaultHidden: true,
          responsive: "lg"
        })
      },
      {
        id: "round",
        header: "Round",
        enableSorting: false,
        cell: ({ row }) => <span className="text-xs tabular-nums">{row.original.round}</span>,
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "meta",
          defaultHidden: true,
          align: "center",
          numeric: true
        })
      },
      {
        id: "best_of",
        header: "Best of",
        enableSorting: false,
        cell: ({ row }) => <span className="text-xs tabular-nums">{row.original.best_of}</span>,
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "meta",
          defaultHidden: true,
          align: "center",
          numeric: true
        })
      },
      {
        id: "tournament",
        header: "Tournament",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-xs">{row.original.tournament_name ?? `#${row.original.tournament_id}`}</span>
        ),
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "meta",
          // The encounter cell already names it whenever the scope is wider
          // than one tournament; as its own column it is a duplicate.
          defaultHidden: true,
          responsive: "lg"
        })
      },
      {
        id: "resolution",
        header: "Last resolution",
        enableSorting: false,
        cell: ({ row }) => {
          const resolution = row.original.last_resolution;
          if (!resolution) return <span className="text-xs text-muted-foreground">{DASH}</span>;
          return (
            <div className="text-xs">
              <p className="truncate">
                {resolution.action} by {resolution.actor_name ?? "an automated process"}
              </p>
              <p className="tabular-nums text-muted-foreground">{fmtDate(format, resolution.created_at)}</p>
            </div>
          );
        },
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "admin",
          defaultHidden: true,
          responsive: "lg",
          className: "min-w-[180px]"
        })
      },
      {
        id: "encounter_id",
        header: "ID",
        enableSorting: false,
        cell: ({ row }) => <span className="text-xs tabular-nums">{row.original.id}</span>,
        meta: adminColumnMeta<EncounterReportsRow>({
          category: "admin",
          defaultHidden: true,
          numeric: true
        })
      },
      // One column per organizer-defined question. Off by default: a form may
      // define a dozen, and they are only labelled while a single tournament
      // is in scope.
      ...customFields.map((field) =>
        sidesColumn(
          `custom_${field.key}`,
          field.label,
          (report) => report?.custom_fields[field.key] ?? "",
          {
            category: "admin",
            defaultHidden: true,
            responsive: "lg",
            className: "min-w-[160px] max-w-[240px]"
          }
        )
      )
    ],
    [showTournament, customFields, format]
  );
}
