"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { Crown, Lock } from "lucide-react";

import { DataTable, columnMeta, readColumnMeta, type DataTableGroup } from "@/components/data-table";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { NumberInput } from "@/components/ui/number-input";
import { Spinner } from "@/components/ui/spinner";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import adminService from "@/services/admin.service";
import type { PlayerStanding } from "@/types/admin.types";
import type { Stage, Tournament } from "@/types/tournament.types";

import { tabError, tabFallback } from "../../hubQueries";
import {
  pinsDirty,
  pinsPayload,
  standingRows,
  type PinEdits,
  type PlayerStandingRow
} from "./playerStandings.model";

/** Same cadence as the public standings of a live tournament. */
const REFRESH_MS = 15_000;

/**
 * The personal table of an `individual_swiss` stage, one table grouped by role:
 * pin a player's place, and — once the stage is completed — lock the
 * qualification, which excludes everyone below the cut and moves the
 * tournament to its draft.
 */
export function PlayerStandingsSection({
  stage,
  tournament,
  onChanged
}: Readonly<{ stage: Stage; tournament: Tournament | undefined; onChanged: () => void }>) {
  const t = useTranslations("adminBracket.individual");
  const queryClient = useQueryClient();
  const ontology =
    useDisciplineMetadata(tournament?.workspace_id ?? "all", tournament?.discipline ?? null).data ??
    null;
  const slotLabel = useSlotLabel(ontology);
  const [edits, setEdits] = useState<PinEdits>({});
  const [confirmingLock, setConfirmingLock] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);

  const standingsKey = adminQueryKeys.tournamentPlayerStandings(stage.tournament_id);
  const standingsQuery = useQuery({
    queryKey: standingsKey,
    queryFn: () => adminService.listPlayerStandings(stage.tournament_id),
    refetchInterval: REFRESH_MS
  });

  const stageRows = useMemo(
    () => (standingsQuery.data ?? []).filter((row) => row.stage_id === stage.id),
    [standingsQuery.data, stage.id]
  );
  const dirty = pinsDirty(stageRows, edits);

  const filterDefs: FilterDef[] = [
    {
      key: "role",
      label: t("role"),
      kind: "multi",
      options: [...new Set(stageRows.map((row) => row.role))].map((role) => ({
        value: role,
        label: slotLabel(role)
      }))
    }
  ];
  const filters = useFilters(filterDefs);
  // `values` is rebuilt every render; its joined form changes only with the filter.
  const roleKey = (filters.values.role as string[]).join(",");
  // A new array repaints every row, so it changes only with the data, a pin draft or the filter.
  const rows = useMemo(() => {
    const shown = roleKey ? roleKey.split(",") : [];
    const all = standingRows(stageRows, edits);
    return shown.length > 0 ? all.filter((row) => shown.includes(row.role)) : all;
  }, [stageRows, edits, roleKey]);

  // Stable: a cell function that changed identity would remount the pin input mid-typing. The draft
  // reaches the input through the row's `pin`.
  const columns = useMemo<ColumnDef<PlayerStandingRow>[]>(() => {
    const numeric = columnMeta<PlayerStandingRow>({ align: "right", numeric: true });
    const defs: ColumnDef<PlayerStandingRow>[] = [
      {
        accessorKey: "position",
        header: t("place"),
        cell: ({ row }) => row.original.position ?? "–",
        meta: columnMeta<PlayerStandingRow>({ numeric: true })
      },
      {
        accessorKey: "display_name",
        header: t("player"),
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-1.5">
            {row.original.display_name}
            {row.original.is_captain ? (
              <Crown aria-label={t("captain")} className="size-3.5 text-[color:var(--aqt-warm)]" />
            ) : null}
          </span>
        ),
        meta: columnMeta<PlayerStandingRow>({ searchValue: (row) => row.display_name })
      },
      { accessorKey: "role", header: t("role"), cell: ({ row }) => slotLabel(row.original.role) },
      { accessorKey: "points", header: t("points"), meta: numeric },
      {
        id: "record",
        header: t("record"),
        accessorFn: (row) => `${row.wins}–${row.draws}–${row.losses}`,
        meta: numeric
      },
      {
        accessorKey: "map_diff",
        header: t("mapDiff"),
        cell: ({ row }) => (row.original.map_diff > 0 ? `+${row.original.map_diff}` : row.original.map_diff),
        meta: numeric
      },
      {
        accessorKey: "buchholz",
        header: t("buchholz"),
        cell: ({ row }) => row.original.buchholz.toFixed(1),
        meta: numeric
      },
      {
        accessorKey: "pin",
        header: t("pin"),
        // As wide as its input: an even share would leave a blank band at the table's right edge.
        size: 128,
        cell: ({ row }) => (
          <NumberInput
            integer
            min={1}
            max={row.original.roleSize}
            size="sm"
            className="w-24"
            aria-label={t("pinLabel", { name: row.original.display_name })}
            placeholder="–"
            value={row.original.pin}
            onValueChange={(next) =>
              setEdits((current) => ({ ...current, [row.original.workspace_member_id]: next }))
            }
          />
        )
      }
    ];
    // Places and the cut read only in the server's order, so nothing sorts; the cut and the
    // players below it are drawn across the whole row.
    return defs.map((column) => ({
      ...column,
      enableSorting: false,
      meta: columnMeta<PlayerStandingRow>({
        ...readColumnMeta<PlayerStandingRow>(column.meta),
        onCell: (row) => ({
          className: cn(
            row.atCut && "border-b-2 border-b-[color:var(--aqt-border-3)]",
            !row.is_qualified && "text-[color:var(--aqt-fg-dim)]"
          )
        })
      })
    }));
  }, [t, slotLabel]);

  const groupByRole = (pageRows: Row<PlayerStandingRow>[]): DataTableGroup<PlayerStandingRow>[] => {
    const groups = new Map<string, Row<PlayerStandingRow>[]>();
    for (const row of pageRows) groups.set(row.original.role, [...(groups.get(row.original.role) ?? []), row]);
    return [...groups].map(([role, roleRows]) => ({ key: role, label: slotLabel(role), rows: roleRows }));
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      adminService.setPlayerStandingPins(stage.tournament_id, stage.id, pinsPayload(stageRows, edits)),
    onSuccess: (pins) => {
      // The recalculation that applies the pins is a job: show them now, the poll brings the new places.
      const pinned = new Map(pins.map((pin) => [pin.workspace_member_id, pin.position]));
      queryClient.setQueryData<PlayerStanding[]>(standingsKey, (current) =>
        current?.map((row) =>
          row.stage_id === stage.id
            ? {
                ...row,
                is_pinned: pinned.has(row.workspace_member_id),
                position: pinned.get(row.workspace_member_id) ?? row.position
              }
            : row
        )
      );
      setEdits({});
      notify.success(t("pinsSaved"));
    },
    onError: (error) => notify.apiError(error, { title: t("pinsError") })
  });

  const lockMutation = useMutation({
    mutationFn: () => adminService.lockQualification(stage.tournament_id, stage.id),
    onSuccess: (result) => {
      setConfirmingLock(false);
      setLockError(null);
      notify.success(
        t("locked", { qualified: result.qualified.length, captains: result.captains.length })
      );
      invalidateTournamentWorkspace(queryClient, stage.tournament_id);
      void queryClient.invalidateQueries({ queryKey: standingsKey });
      onChanged();
    },
    onError: (error) => {
      setConfirmingLock(false);
      // A 409 explains itself in the server's words (not completed, not live, nobody qualified).
      setLockError(error instanceof Error ? error.message : t("lockError"));
    }
  });

  if (standingsQuery.isPending) return tabFallback;
  if (standingsQuery.isError) return tabError(() => standingsQuery.refetch());

  // The server refuses a lock while rounds are still open and says why; the worker never completes this stage.
  const canLock = stage.status === "live" && tournament?.status === "live";

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-prose text-caption text-muted-foreground">{t("description")}</p>

      {lockError ? (
        <Alert tone="danger">
          <AlertDescription>{lockError}</AlertDescription>
        </Alert>
      ) : null}

      <DataTable<PlayerStandingRow>
        rows={rows}
        columns={columns}
        getRowId={(row) => String(row.workspace_member_id)}
        paging="all"
        groupRows={groupByRole}
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        searchPlaceholder={t("search")}
        emptyMessage={t("empty")}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          size="sm"
          variant="outline"
          disabled={!dirty || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          {saveMutation.isPending ? <Spinner /> : null}
          {t("savePins")}
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          {canLock ? null : <p className="text-caption text-muted-foreground">{t("lockHint")}</p>}
          <Button
            size="sm"
            disabled={!canLock || lockMutation.isPending}
            onClick={() => setConfirmingLock(true)}
          >
            <Lock className="size-4" aria-hidden />
            {t("lock")}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmingLock}
        onOpenChange={setConfirmingLock}
        intent={{
          title: t("lockTitle"),
          description: t("lockDescription"),
          confirmLabel: t("lockConfirm"),
          tone: "warning"
        }}
        onConfirm={() => lockMutation.mutate()}
        pending={lockMutation.isPending}
      />
    </div>
  );
}
