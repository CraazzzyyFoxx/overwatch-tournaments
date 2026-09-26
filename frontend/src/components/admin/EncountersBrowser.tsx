"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter } from "@/lib/datetime/client";
import {
  CheckCircle,
  CircleAlert,
  Clock,
  FileCheck2,
  FileX2,
  Gavel,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Upload
} from "lucide-react";

import { AdminDataTable, adminColumnMeta, createKebabColumn } from "@/components/data-table";
import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import {
  EncounterForm,
  emptyEncounterForm,
  encounterCreatePayload,
  encounterFormError,
  encounterFormOf,
  encounterUpdatePayload,
  type EncounterFormMode,
  type EncounterFormState
} from "@/components/admin/EncounterForm";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { hasChallongeSource } from "@/components/admin/tournament-checklist";
import { TOURNAMENT_QUERY_PARAM, parseTournamentQueryParam } from "@/components/admin/tournament-filter";
import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { TournamentLogUploadDialog } from "@/app/admin/tournaments/[id]/components/TournamentLogUploadDialog";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import {
  bracketRoundLabelEn,
  UNKNOWN_ROUND_SHAPE
} from "@/lib/bracket/round-name";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import type { AdminMatchRow } from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import { EmptyNote } from "@/components/kit/EmptyNote";

const PAGE_SIZE = 15;

/** The stage or stage item an encounter was scheduled under. */
function encounterScopeLabel(encounter: Encounter): string {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? "—";
}

function EncounterStatusCell({ status }: Readonly<{ status?: string | null }>) {
  const upper = status?.toUpperCase() ?? "";
  if (upper === "COMPLETED") {
    return <StatusIcon icon={CheckCircle} label="Completed" variant="success" />;
  }
  if (upper === "PENDING") {
    return <StatusIcon icon={Clock} label="Pending" variant="warning" />;
  }
  return (
    <StatusIcon
      icon={CircleAlert}
      label={upper ? `${upper[0]}${upper.slice(1).toLowerCase()}` : "Unknown"}
      variant="muted"
    />
  );
}

/**
 * The planned start time, on the viewer's own clock (the app formatter's zone)
 * — the same zone the stage editor's round schedule is typed against. Its own
 * component so the column definitions stay independent of the formatter's
 * identity.
 */
function ScheduledAtCell({ value }: Readonly<{ value: Encounter["scheduled_at"] }>) {
  const format = useFormatter();
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const at = new Date(value);
  return (
    <time
      className="text-sm tabular-nums"
      dateTime={at.toISOString()}
      title={format.dateTime(at, { dateStyle: "full", timeStyle: "short" })}
    >
      {format.dateTime(at, {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
      })}
    </time>
  );
}

function InspectorField({
  label,
  children
}: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <div className="truncate text-sm">{children}</div>
    </div>
  );
}

/**
 * Encounters, for one tournament or for the whole workspace.
 *
 * One component rather than a hub tab and a near-identical browser page: the
 * two differed only by whether the tournament is pinned, and the two copies had
 * already drifted — the hub's table offered no paging, no closeness and sent a
 * lowercase `status` the backend does not accept, while the browser page had no
 * stage scope at all.
 *
 * Everything the admin narrows by lives in the URL through `FilterBar`, so
 * `?stage=` survives a move to the Standings or Reports view beside it.
 */
export function EncountersBrowser({
  tournamentId,
  workspaceId
}: Readonly<{
  /** `null` = every tournament in the workspace, with the chip unpinned. */
  tournamentId: number | null;
  workspaceId: number | null;
}>) {
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row is on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const canCreate = canAccessPermission("match.create", workspaceId);
  const canUpdate = canAccessPermission("match.update", workspaceId);
  const canDelete = canAccessPermission("match.delete", workspaceId);
  // Encounter sync hits the Challonge import endpoint, so it is gated on the
  // Challonge grant rather than on `match.*`.
  const canSync = canAccessPermission("challonge.update", workspaceId);

  const [pageRows, setPageRows] = useState<Encounter[]>([]);
  const [formMode, setFormMode] = useState<EncounterFormMode | null>(null);
  const [editing, setEditing] = useState<Encounter | null>(null);
  const [form, setForm] = useState<EncounterFormState>(emptyEncounterForm(null, null));
  const [formInitial, setFormInitial] = useState<EncounterFormState>(emptyEncounterForm(null, null));
  const [saveError, setSaveError] = useState<string | undefined>();
  const [pendingDelete, setPendingDelete] = useState<Encounter | null>(null);

  // Scope: pinned by the hub, or picked with a chip on the workspace browser.
  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null),
    enabled: tournamentId == null
  });

  const tournamentQuery = useQuery({
    queryKey: ["admin", "tournament", scopeTournamentId],
    queryFn: () => adminService.getTournament(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  const stagesQuery = useQuery({
    queryKey: ["admin", "stages", scopeTournamentId],
    queryFn: () => adminService.getStages(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  const teamsQuery = useQuery({
    queryKey: ["teams", scopeTournamentId],
    queryFn: () => teamService.getAll({ tournamentId: scopeTournamentId }),
    enabled: scopeTournamentId != null
  });

  const stages = stagesQuery.data ?? [];
  const teams = teamsQuery.data?.results ?? [];
  const stageItems = stages.flatMap((stage) => stage.items);

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
    if (stages.length > 0) {
      list.push({
        key: "stage",
        label: "Stage",
        kind: "single",
        options: stages.map((stage) => ({ value: String(stage.id), label: stage.name }))
      });
    }
    if (stageItems.length > 0) {
      list.push({
        key: "group",
        label: "Group",
        kind: "single",
        options: stageItems.map((item) => ({ value: String(item.id), label: item.name }))
      });
    }
    list.push(
      {
        key: "status",
        label: "Status",
        kind: "single",
        options: [
          { value: "OPEN", label: "Open" },
          { value: "PENDING", label: "Pending" },
          { value: "COMPLETED", label: "Completed" }
        ]
      },
      {
        key: "has_logs",
        label: "Logs",
        kind: "single",
        options: [
          { value: "true", label: "Logs available" },
          { value: "false", label: "No logs" }
        ]
      }
    );
    return list;
  }, [tournamentId, tournamentsQuery.data, stages, stageItems]);

  const filters = useFilters(defs);
  const stageFilter = String(filters.values.stage ?? "");
  const groupFilter = String(filters.values.group ?? "");
  const statusFilter = String(filters.values.status ?? "");
  const logsFilter = String(filters.values.has_logs ?? "");

  // The inspector shows a row from the page on screen, so a deep-linked `?id=`
  // that the current filters exclude leaves it closed rather than fetching an
  // encounter the list does not contain.
  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const reportsQuery = useQuery({
    queryKey: ["encounter-reports", "encounter", openRow?.id ?? null, workspaceId],
    queryFn: () => adminService.listEncounterReports({
      workspace_id: workspaceId!,
      tournament_id: openRow!.tournament_id,
      query: openRow!.name,
      per_page: 25
    }),
    enabled: openRow != null && workspaceId != null
  });
  const reportRow = reportsQuery.data?.results.find((row) => row.id === openRow?.id) ?? null;

  const parsedMapsQuery = useQuery({
    queryKey: ["admin-matches", "encounter", openRow?.id ?? null, workspaceId],
    queryFn: () => adminService.listAdminMatches({
      workspace_id: workspaceId!,
      encounter_id: openRow!.id,
      per_page: 25
    }),
    enabled: openRow != null && workspaceId != null
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["encounters"] });
    if (scopeTournamentId != null) {
      invalidateTournamentWorkspace(queryClient, scopeTournamentId, workspaceId);
    }
  };

  const closeForm = () => {
    setFormMode(null);
    setEditing(null);
    setSaveError(undefined);
  };

  const saveMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (payload: EncounterFormState) =>
      editing
        ? adminService.updateEncounter(editing.id, encounterUpdatePayload(payload))
        : adminService.createEncounter(encounterCreatePayload(payload, scopeTournamentId!)),
    onSuccess: () => {
      const created = editing == null;
      invalidate();
      closeForm();
      notify.success(created ? "Encounter created" : "Encounter updated");
    },
    onError: (error: Error) => setSaveError(`Could not save the encounter. ${error.message}`)
  });

  const deleteMutation = useMutation({
    mutationFn: (encounterId: number) => adminService.deleteEncounter(encounterId),
    onSuccess: () => {
      const removed = pendingDelete;
      invalidate();
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success("Encounter deleted");
    }
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncEncountersFromChallonge(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      notify.success("Encounters synced from Challonge");
    }
  });

  // `saveMutation` is rebuilt on every state transition; `reset` is not, so the
  // memoised `openEdit` below hangs on the callback instead of the container.
  const { reset: resetSaveMutation } = saveMutation;

  const openCreate = () => {
    const stage = stages[0] ?? null;
    const blank = emptyEncounterForm(stage?.id ?? null, stage?.items[0]?.id ?? null);
    resetSaveMutation();
    setSaveError(undefined);
    setEditing(null);
    setForm(blank);
    setFormInitial(blank);
    setFormMode("create");
  };

  // The kebab column closes over this, so the column memo has to depend on it —
  // which means it needs an identity that only moves when its inputs do. Every
  // other name it touches is a `useState` setter (stable by contract).
  const openEdit = useCallback(
    (encounter: Encounter) => {
      const initial = encounterFormOf(encounter);
      resetSaveMutation();
      setSaveError(undefined);
      setEditing(encounter);
      setForm(initial);
      setFormInitial(initial);
      setFormMode("edit");
    },
    [resetSaveMutation]
  );

  const columns = useMemo<ColumnDef<Encounter>[]>(
    () => [
      {
        accessorKey: "id",
        header: "#",
        size: 76,
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {row.original.id}
          </span>
        )
      },
      {
        accessorKey: "name",
        header: "Encounter",
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[18rem]">
            <p className="truncate font-medium text-foreground" title={row.original.name}>
              {row.original.name}
            </p>
            <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
              <TeamName team={row.original.home_team} fallback="TBD" size="xs" />
              <span>vs</span>
              <TeamName team={row.original.away_team} fallback="TBD" size="xs" />
            </p>
          </div>
        )
      },
      {
        id: "stage",
        header: "Stage / Round",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="text-sm">
            {encounterScopeLabel(row.original)}
            <span className="text-muted-foreground"> · R</span>
            <span className="tabular-nums text-muted-foreground">{row.original.round}</span>
          </div>
        )
      },
      {
        accessorKey: "scheduled_at",
        header: "Scheduled",
        size: 132,
        cell: ({ row }) => <ScheduledAtCell value={row.original.scheduled_at} />
      },
      {
        accessorKey: "score",
        header: "Score",
        size: 92,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-sm font-semibold tabular-nums">
            {row.original.score.home} &ndash; {row.original.score.away}
          </span>
        )
      },
      {
        accessorKey: "status",
        header: "Status",
        size: 132,
        meta: adminColumnMeta<Encounter>({ align: "center" }),
        cell: ({ row }) => <EncounterStatusCell status={row.original.status} />
      },
      {
        id: "result",
        header: "Result",
        size: 132,
        enableSorting: false,
        cell: ({ row }) => (
          <StatusPill tone={row.original.result_status === "disputed" ? "danger" : "neutral"}>
            {row.original.result_status}
          </StatusPill>
        )
      },
      {
        accessorKey: "has_logs",
        header: "Logs",
        size: 108,
        meta: adminColumnMeta<Encounter>({ align: "center" }),
        cell: ({ row }) =>
          row.original.has_logs ? (
            <StatusIcon icon={FileCheck2} label="Available" variant="success" />
          ) : (
            <StatusIcon icon={FileX2} label="Missing" variant="muted" />
          )
      },
      createKebabColumn<Encounter>(
        (row) => [
          { label: "Edit encounter", icon: Pencil, hidden: !canUpdate, onSelect: () => openEdit(row) },
          {
            label: "Delete encounter",
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => setPendingDelete(row)
          }
        ],
        { rowLabel: (row) => row.name }
      )
    ],
    // `openEdit` was missing here: the kebab's "Edit encounter" called whichever
    // closure the first render happened to build.
    [canUpdate, canDelete, openEdit]
  );

  if (workspaceId == null) {
    return (
      <EmptyNote>
        Encounters are scoped to a workspace. Pick one to see what has been scheduled.
      </EmptyNote>
    );
  }

  const tournament = tournamentQuery.data;
  const challongeReady = hasChallongeSource(tournament, stages);
  const reportsHref =
    tournamentId != null
      ? `/admin/tournaments/${tournamentId}/matches/reports`
      : "/admin/matches?view=reports";

  const trailing = (
    <>
      {canSync ? (
        <Button
          variant="outline"
          size="sm"
          disabled={syncMutation.isPending || scopeTournamentId == null || !challongeReady}
          onClick={() => syncMutation.mutate()}
        >
          <RefreshCw aria-hidden className="size-4" />
          Sync from Challonge
        </Button>
      ) : null}
      {canCreate ? (
        <Button
          size="sm"
          disabled={scopeTournamentId == null || stages.length === 0 || teams.length < 2}
          onClick={openCreate}
        >
          <Plus aria-hidden className="size-4" />
          Create encounter
        </Button>
      ) : null}
    </>
  );

  return (
    <div
      className={cn(
        "grid items-start gap-4",
        openRow && "lg:grid-cols-[minmax(0,1fr)_380px]"
      )}
    >
      <div className="min-w-0">
        <AdminDataTable<Encounter>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          searchPlaceholder="Search encounters…"
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={
            <FilterBar
              defs={defs}
              filters={filters}
              trailing={trailing}
              pinned={
                tournamentId != null
                  ? [
                      {
                        key: TOURNAMENT_QUERY_PARAM,
                        label: `Tournament: ${tournament?.name ?? `#${tournamentId}`}`
                      }
                    ]
                  : undefined
              }
            />
          }
          emptyMessage={
            scopeTournamentId == null
              ? "No encounters yet. Pick a tournament to see its bracket."
              : "No encounters match. Sync from Challonge or create the first one."
          }
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{row.original.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {encounterScopeLabel(row.original)} · R{row.original.round} ·{" "}
                <span className="font-mono tabular-nums">
                  {row.original.score.home}&ndash;{row.original.score.away}
                </span>
              </p>
              <p className="text-xs text-muted-foreground">
                {row.original.status} · {row.original.has_logs ? "logs" : "no logs"}
              </p>
            </div>
          )}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "encounters",
            scopeTournamentId,
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            { stage: stageFilter, group: groupFilter, status: statusFilter, has_logs: logsFilter }
          ]}
          queryFn={async (page, search, pageSize, sortField, sortDir) => {
            const result = await encounterService.getAll(
              page,
              search,
              scopeTournamentId,
              pageSize,
              sortField,
              sortDir,
              undefined,
              {
                stage_id: stageFilter ? Number(stageFilter) : null,
                stage_item_id: groupFilter ? Number(groupFilter) : null,
                status: statusFilter || null,
                has_logs: logsFilter ? logsFilter === "true" : null
              }
            );
            // The inspector pages through the rows currently on screen, and the
            // table owns the fetch, so this is where that page is observed.
            setPageRows(result.results);
            return result;
          }}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? `Encounter #${openRow.id}` : ""}
        subtitle={
          openRow
            ? `${openRow.tournament?.name ?? "Unknown tournament"} · ${encounterScopeLabel(openRow)} · ${bracketRoundLabelEn(openRow.round, UNKNOWN_ROUND_SHAPE)}`
            : undefined
        }
        onPrev={openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined}
        onNext={
          openIndex >= 0 && openIndex < pageRows.length - 1
            ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
            : undefined
        }
        actions={
          openRow ? (
            <>
              {canUpdate ? (
                <Button variant="outline" size="sm" onClick={() => openEdit(openRow)}>
                  <Pencil aria-hidden className="size-3.5" />
                  Edit
                </Button>
              ) : null}
              {canUpdate ? (
                <TournamentLogUploadDialog
                  tournamentId={openRow.tournament_id}
                  encounters={[openRow]}
                  initialEncounterId={openRow.id}
                  onUploaded={invalidate}
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
                    href={`${reportsHref}${reportsHref.includes("?") ? "&" : "?"}search=${encodeURIComponent(openRow.name)}&id=${openRow.id}`}
                  >
                    <Gavel aria-hidden className="size-3.5" />
                    Resolve result
                  </Link>
                </Button>
              ) : null}
              <AuditTrailButton
                scope={{ entityType: "encounter", entityId: openRow.id, workspaceId }}
                target={openRow.name}
              />
            </>
          ) : null
        }
      >
        {openRow ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <InspectorField label="Teams">
                <span className="flex items-center gap-1.5">
                  <TeamName team={openRow.home_team} fallback="TBD" size="xs" />
                  <span className="text-muted-foreground">vs</span>
                  <TeamName team={openRow.away_team} fallback="TBD" size="xs" />
                </span>
              </InspectorField>
              <InspectorField label="Score">
                <span className="font-mono tabular-nums">
                  {openRow.score.home} &ndash; {openRow.score.away}
                </span>
              </InspectorField>
              <InspectorField label="Status">
                <EncounterStatusCell status={openRow.status} />
              </InspectorField>
              <InspectorField label="Result">{openRow.result_status}</InspectorField>
              <InspectorField label="Best of">
                <span className="tabular-nums">{openRow.best_of}</span>
              </InspectorField>
              <InspectorField label="Logs">
                {openRow.has_logs ? "Attached" : "None"}
              </InspectorField>
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
              <p className={EYEBROW_CLASS}>
                Parsed maps ({parsedMapsQuery.data?.total ?? 0})
              </p>
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
        ) : null}
      </Inspector>

      <EntityFormDialog
        open={formMode != null}
        onOpenChange={(next) => {
          if (!next) closeForm();
        }}
        title={formMode === "edit" ? "Edit encounter" : "Create encounter"}
        description="Create or update a tournament encounter."
        isSubmitting={saveMutation.isPending}
        submittingLabel={formMode === "edit" ? "Updating encounter…" : "Creating encounter…"}
        errorMessage={saveError}
        isDirty={formMode != null && hasUnsavedChanges(form, formInitial)}
        onSubmit={(event) => {
          event.preventDefault();
          const invalid = encounterFormError(form);
          if (invalid) {
            setSaveError(invalid);
            return;
          }
          saveMutation.mutate(form);
        }}
      >
        <EncounterForm
          mode={formMode === "edit" ? "edit" : "create"}
          value={form}
          onChange={setForm}
          stages={stages}
          teams={teams}
        />
      </EntityFormDialog>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: "Delete encounter",
          description: `Deleting “${pendingDelete?.name ?? "this encounter"}” removes the encounter and everything recorded under it. This cannot be undone.`,
          confirmLabel: "Delete encounter",
          tone: "danger",
          cascade: ["All matches in this encounter", "Attached match statistics and logs"]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
