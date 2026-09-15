"use client";

import { useMemo, useState, type ReactNode } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, Clock3, Gavel, ScrollText } from "lucide-react";

import { AdminDataTable, adminColumnMeta } from "@/components/admin-data-table";
import { AdminReportPairCell } from "@/components/admin/AdminReportPairCell";
import { ResolveResultDialog } from "@/components/admin/ResolveResultDialog";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { AdminInspector } from "@/components/admin/kit/AdminInspector";
import { useAdminFilters, type FilterDef } from "@/components/admin/kit/useAdminFilters";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { EYEBROW_CLASS, TONE_TEXT } from "@/components/admin/tone";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import { Button } from "@/components/ui/button";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import reportFormService from "@/services/report-form.service";
import tournamentService from "@/services/tournament.service";
import type {
  AdminCaptainReport,
  EncounterReportsQuery,
  EncounterReportsRow
} from "@/types/admin.types";
import type { ReportCustomFieldDefinition } from "@/types/encounter.types";
import { invalidateTournamentWorkspace } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.queryKeys";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

const PAGE_SIZE = 25;
const DASH = "—";

/** Lobby codes in play order — the report stores them unordered. */
function mapCodes(report: AdminCaptainReport | null): string {
  if (!report || report.map_codes.length === 0) return "";
  return [...report.map_codes]
    .sort((a, b) => a.map_index - b.map_index)
    .map((entry) => `M${entry.map_index + 1} ${entry.code}`)
    .join(", ");
}

/** What the captain last stood behind: an edited report supersedes its filing. */
function submittedAt(report: AdminCaptainReport | null): string | null {
  return report ? (report.updated_at ?? report.created_at) : null;
}

function fmtDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : DASH;
}

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
 * Everything one captain filed, in full.
 *
 * The table cell is a summary by necessity; this is the surface an admin
 * settling a dispute reads, so it withholds nothing the report carries —
 * including the organizer's own questions, whose labels come from the
 * tournament's report form rather than the raw storage keys.
 */
function ReportDetail({
  label,
  teamName,
  report,
  customFields
}: Readonly<{
  label: string;
  teamName: string;
  report: AdminCaptainReport | null;
  customFields: ReportCustomFieldDefinition[];
}>) {
  if (!report) {
    return (
      <section className="rounded-xl border border-dashed border-border/60 p-3">
        <p className={EYEBROW_CLASS}>
          {label} · {teamName}
        </p>
        <p className="mt-1 text-sm italic text-muted-foreground">No report filed.</p>
      </section>
    );
  }

  // Answers to questions the form no longer defines still happened, so they are
  // listed under their key rather than dropped with the definition.
  const known = new Set(customFields.map((field) => field.key));
  const extras = Object.entries(report.custom_fields).filter(([key]) => !known.has(key));
  const codes = mapCodes(report);

  return (
    <section className="space-y-2 rounded-xl border border-border/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className={EYEBROW_CLASS}>
          {label} · {teamName}
        </p>
        <p className="font-mono text-sm font-semibold tabular-nums">
          {report.home_score} &ndash; {report.away_score}
        </p>
      </div>

      <dl className="space-y-1 text-sm">
        <Field label="Reported by" value={report.reporter_name ?? "unknown"} />
        <Field label="Submitted" value={fmtDate(submittedAt(report))} mono />
        <Field
          label="Closeness"
          value={report.closeness == null ? "not rated" : `${report.closeness}/10`}
        />
        {codes ? <Field label="Lobby codes" value={codes} mono /> : null}
        {report.comment ? <Field label="Comment" value={report.comment} /> : null}
        {customFields.map((field) => (
          <Field
            key={field.key}
            label={field.label}
            value={report.custom_fields[field.key] || DASH}
          />
        ))}
        {extras.map(([key, value]) => (
          <Field key={key} label={key} value={value} />
        ))}
      </dl>
    </section>
  );
}

function Field({
  label,
  value,
  mono
}: Readonly<{ label: string; value: string; mono?: boolean }>) {
  return (
    <div className="grid grid-cols-[9rem_minmax(0,1fr)] gap-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("min-w-0 break-words", mono && "font-mono text-xs tabular-nums")}>
        {value}
      </dd>
    </div>
  );
}

/**
 * Captain reports, for one tournament or for the whole workspace.
 *
 * One component rather than a hub tab and a near-identical browser page: the
 * two differ only by whether `tournamentId` is pinned, and a second copy of a
 * table with this much derived state would drift within a release.
 *
 * A dispute used to be invisible outside the per-encounter dialog; this lists
 * what needs attention and hands each row to the one write surface that can
 * settle it.
 *
 * Filters are chips in `AdminFilterBar` and the row detail is `AdminInspector`,
 * so a narrowed list and the open row both travel in the URL — a disputed
 * encounter can be pasted to whoever has to settle it.
 */
export function EncounterReportsBrowser({
  tournamentId,
  workspaceId,
  canUpdateEncounter,
  tournamentName
}: Readonly<{
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  workspaceId: number | null;
  canUpdateEncounter: boolean;
  /** Names the pinned chip inside a hub; the chip reads `#id` without it. */
  tournamentName?: string | null;
}>) {
  const queryClient = useQueryClient();
  // `id` is the inspector, not a filter: opening a row must not drop its page.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;
  const [pageRows, setPageRows] = useState<EncounterReportsRow[]>([]);
  const [resolving, setResolving] = useState<EncounterReportsRow | null>(null);
  const showTournament = tournamentId == null;

  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const scopeParams = useMemo<EncounterReportsQuery | null>(
    () =>
      workspaceId == null
        ? null
        : { workspace_id: workspaceId, tournament_id: scopeTournamentId ?? undefined },
    [workspaceId, scopeTournamentId]
  );

  // Counters take the scope alone — not the chips, not the search box. The
  // numbers answer "how much in this scope needs attention", so they stay put
  // while the admin narrows the list or looks one encounter up, instead of
  // collapsing to what is on screen.
  const statsQuery = useQuery({
    queryKey: ["encounter-reports", "stats", scopeParams],
    queryFn: () => adminService.getEncounterReportStats(scopeParams!),
    enabled: scopeParams != null
  });

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null),
    enabled: workspaceId != null && tournamentId == null
  });

  const stagesQuery = useQuery({
    queryKey: ["admin", "stages", scopeTournamentId],
    queryFn: () => adminService.getStages(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  // Organizer-defined questions, so their answers can be labelled instead of
  // shown under raw storage keys. Per tournament, so it is only asked for once
  // a single tournament is in scope; workspace-wide the keys stand in.
  const reportFormQuery = useQuery({
    queryKey: ["admin", "report-form", scopeTournamentId],
    queryFn: () => reportFormService.getReportForm(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });
  const customFields = useMemo(
    () => reportFormQuery.data?.custom_fields ?? [],
    [reportFormQuery.data]
  );

  const stats = statsQuery.data;

  const defs = useMemo<FilterDef[]>(() => {
    const list: FilterDef[] = [];
    if (tournamentId == null) {
      list.push({
        key: TOURNAMENT_QUERY_PARAM,
        label: "Tournament",
        kind: "single",
        options: (tournamentsQuery.data?.results ?? []).map((entry) => ({
          value: String(entry.id),
          label: entry.name
        }))
      });
    }
    if ((stagesQuery.data ?? []).length > 0) {
      list.push({
        key: "stage",
        label: "Stage",
        kind: "single",
        options: (stagesQuery.data ?? []).map((stage) => ({
          value: String(stage.id),
          label: stage.name
        }))
      });
    }
    list.push(
      {
        key: "result_status",
        label: "Result",
        // The endpoint's field is a list and the service repeats the param once
        // per checked value, so this narrows to several states at once.
        kind: "multi",
        options: [
          { value: "none", label: "None" },
          { value: "pending_confirmation", label: "Pending confirmation" },
          { value: "confirmed", label: "Confirmed" },
          { value: "disputed", label: "Disputed" }
        ]
      },
      {
        key: "reported_count",
        label: "Reports filed",
        // `reported_count` is a scalar on the endpoint, so this is single
        // select: "0 or 2" is not a question the query param can ask.
        kind: "single",
        options: [
          { value: "0", label: "No reports" },
          { value: "1", label: "Awaiting second" },
          { value: "2", label: "Both reported" }
        ]
      },
      // Looks like `result_status: disputed` but is not: that is the recorded
      // result state, this is the live disagreement between two reports. A
      // dispute an admin already settled still has two divergent reports on
      // file, which is why they are two filters.
      { key: "mismatch_only", label: "Reports disagree", kind: "toggle" }
    );
    return list;
  }, [tournamentId, tournamentsQuery.data, stagesQuery.data]);

  const filters = useAdminFilters(defs);
  const stageFilter = String(filters.values.stage ?? "");
  const resultStatusFilter = Array.isArray(filters.values.result_status)
    ? (filters.values.result_status as string[])
    : [];
  const reportedCountFilter = String(filters.values.reported_count ?? "");
  const mismatchOnly = filters.values.mismatch_only === true;

  // The inspector shows a row from the page on screen, so a deep-linked `?id=`
  // the current chips exclude leaves it closed rather than showing detail for
  // an encounter the list does not contain.
  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const columns = useMemo<ColumnDef<EncounterReportsRow>[]>(
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
          <span className="text-xs tabular-nums">{fmtDate(row.original.scheduled_at)}</span>
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
        return at ? new Date(at).toLocaleString() : "";
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
              <p className="tabular-nums text-muted-foreground">{fmtDate(resolution.created_at)}</p>
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
    [showTournament, customFields]
  );

  if (workspaceId == null) {
    return (
      <EmptyNote>
        Captain reports are scoped to a workspace. Pick one to see what has been reported.
      </EmptyNote>
    );
  }

  return (
    <div className="space-y-3">
      <StatTileGrid>
        <StatTile
          label="Confirmed"
          value={stats?.by_result_status.confirmed ?? 0}
          icon={ClipboardCheck}
          tone="success"
        />
        <StatTile
          label="Disputed"
          value={stats?.by_result_status.disputed ?? 0}
          detail="Recorded result state"
          icon={AlertTriangle}
          tone="danger"
        />
        <StatTile
          label="Reports disagree"
          value={stats?.mismatch_count ?? 0}
          detail="Both captains reported, scores differ"
          icon={ScrollText}
          tone="warning"
        />
        <StatTile
          label="Awaiting second"
          value={stats?.awaiting_second_count ?? 0}
          detail="One captain has reported"
          icon={Clock3}
          tone="info"
        />
      </StatTileGrid>

      <p className="text-sm text-muted-foreground">
        Both captains report independently. Matching scores confirm the encounter; a disagreement
        marks it disputed.
      </p>

      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <AdminDataTable<EncounterReportsRow>
            columns={columns}
            filterKey={filters.filterKey}
            initialPageSize={PAGE_SIZE}
            columnsStorageKey="encounter-reports-table-columns"
            searchPlaceholder="Search team or encounter"
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={
              <AdminFilterBar
                defs={defs}
                filters={filters}
                pinned={
                  tournamentId != null
                    ? [
                        {
                          key: TOURNAMENT_QUERY_PARAM,
                          label: `Tournament: ${tournamentName ?? `#${tournamentId}`}`
                        }
                      ]
                    : undefined
                }
              />
            }
            emptyMessage="No encounters match this filter."
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.original.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {row.original.home_team?.name ?? "?"} vs {row.original.away_team?.name ?? "?"} ·{" "}
                  {row.original.reported_count}/2 reported
                </p>
                <p className="text-xs text-muted-foreground">{row.original.result_status}</p>
              </div>
            )}
            queryKey={(page, search, pageSize) => [
              "encounter-reports",
              {
                workspaceId,
                tournamentId: scopeTournamentId,
                mismatchOnly,
                page,
                search,
                pageSize,
                filters: {
                  stage: stageFilter,
                  result_status: resultStatusFilter,
                  reported_count: reportedCountFilter
                }
              }
            ]}
            queryFn={async (page, search, pageSize) => {
              const result = await adminService.listEncounterReports({
                workspace_id: workspaceId,
                tournament_id: scopeTournamentId ?? undefined,
                stage_id: stageFilter ? Number(stageFilter) : undefined,
                query: search || undefined,
                result_status: resultStatusFilter.length ? resultStatusFilter : undefined,
                // Zero is a real value here ("neither captain reported"), so the
                // guard is on the string, never on the number.
                reported_count: reportedCountFilter ? Number(reportedCountFilter) : undefined,
                mismatch_only: mismatchOnly || undefined,
                page,
                per_page: pageSize
              });
              // The inspector pages through the rows on screen, and the table
              // owns the fetch, so this is where that page is observed.
              setPageRows(result.results);
              return result;
            }}
          />
        </div>

        <AdminInspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow ? openRow.name : ""}
          subtitle={
            openRow
              ? `${showTournament ? `${openRow.tournament_name ?? "Unknown tournament"} · ` : ""}${openRow.stage_name ?? "Unassigned"} · Round ${openRow.round} · BO${openRow.best_of}`
              : undefined
          }
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
          openHref={openRow ? `/encounters/${openRow.id}` : undefined}
          actions={
            openRow && canUpdateEncounter ? (
              <Button type="button" size="sm" variant="secondary" onClick={() => setResolving(openRow)}>
                <Gavel aria-hidden className="size-3.5" />
                {openRow.result_status === "confirmed" ? "Review result" : "Resolve result"}
              </Button>
            ) : null
          }
        >
          {openRow ? (
            <div className="space-y-4">
              <AdminReportPairCell
                homeReport={openRow.home_report}
                awayReport={openRow.away_report}
                scoresMatch={openRow.scores_match}
                seriesScoreValid={openRow.series_score_valid}
              />

              {/* The whole filing, not a summary of it: this is the surface an
                  admin adjudicates from, and a field left out here is a field
                  they would have to go find in the database. */}
              <ReportDetail
                label="Home"
                teamName={openRow.home_team?.name ?? "?"}
                report={openRow.home_report}
                customFields={customFields}
              />
              <ReportDetail
                label="Away"
                teamName={openRow.away_team?.name ?? "?"}
                report={openRow.away_report}
                customFields={customFields}
              />

              <div className="grid grid-cols-2 gap-3">
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Recorded teams</p>
                  <p className="truncate text-sm">
                    {openRow.home_team?.name ?? "?"} vs {openRow.away_team?.name ?? "?"}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Result</p>
                  <p className="truncate text-sm">{openRow.result_status}</p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Encounter status</p>
                  <p className="truncate text-sm">{openRow.status}</p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Reports filed</p>
                  <p className="truncate text-sm tabular-nums">{openRow.reported_count}/2</p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Scheduled</p>
                  <p className="truncate text-sm tabular-nums">{fmtDate(openRow.scheduled_at)}</p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Series check</p>
                  <p className={cn("truncate text-sm", !openRow.series_score_valid && TONE_TEXT.warning)}>
                    {openRow.series_score_valid ? "Within best-of" : "Score outside best-of"}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Encounter ID</p>
                  <p className="truncate text-sm tabular-nums">{openRow.id}</p>
                </div>
                <div className="min-w-0">
                  <p className={EYEBROW_CLASS}>Tournament</p>
                  <p className="truncate text-sm">
                    {openRow.tournament_name ?? `#${openRow.tournament_id}`}
                  </p>
                </div>
              </div>

              {openRow.last_resolution ? (
                <section className="rounded-xl border border-border/60 p-3">
                  <p className={EYEBROW_CLASS}>Last resolution</p>
                  <p className="mt-1 text-sm">
                    {openRow.last_resolution.action} by{" "}
                    {openRow.last_resolution.actor_name ?? "an automated process"}
                  </p>
                  <p className="text-xs tabular-nums text-muted-foreground">
                    {fmtDate(openRow.last_resolution.created_at)}
                  </p>
                </section>
              ) : null}
            </div>
          ) : null}
        </AdminInspector>
      </div>

      <ResolveResultDialog
        row={resolving}
        open={resolving != null}
        onOpenChange={(next) => setResolving(next ? resolving : null)}
        onResolved={() => {
          // A settled result moves the encounter, the standings and the
          // bracket, so the invalidation is wider than this list. Scoped to
          // prefixes rather than exact keys because the list key carries the
          // whole filter object and every variant of it is now stale.
          void queryClient.invalidateQueries({ queryKey: ["encounter-reports"] });
          void queryClient.invalidateQueries({ queryKey: ["encounters"] });
          void queryClient.invalidateQueries({ queryKey: ["admin-matches"] });
          void queryClient.invalidateQueries({
            queryKey: scopeTournamentId == null ? ["standings"] : ["standings", scopeTournamentId]
          });
          if (scopeTournamentId != null) {
            invalidateTournamentWorkspace(queryClient, scopeTournamentId, workspaceId);
          }
        }}
      />
    </div>
  );
}
