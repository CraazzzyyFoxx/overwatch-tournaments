"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { FileCheck2, FileX2, Pencil, Trash2 } from "lucide-react";

import { columnMeta, createKebabColumn } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { StatusPill } from "@/components/kit/StatusPill";
import TeamName from "@/components/TeamName";
import type { Encounter } from "@/types/encounter.types";

import { EncounterStatusCell, ScheduledAtCell, encounterScopeLabel } from "./EncounterCells";

/** The encounter row: who plays, under what, when, and what came of it. */
export function useEncounterColumns({
  canUpdate,
  canDelete,
  onEdit,
  onDelete
}: Readonly<{
  canUpdate: boolean;
  canDelete: boolean;
  /** Stable identity required: the kebab column closes over both. */
  onEdit: (encounter: Encounter) => void;
  onDelete: (encounter: Encounter) => void;
}>): ColumnDef<Encounter>[] {
  return useMemo<ColumnDef<Encounter>[]>(
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
        meta: columnMeta<Encounter>({ align: "center" }),
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
        meta: columnMeta<Encounter>({ align: "center" }),
        cell: ({ row }) =>
          row.original.has_logs ? (
            <StatusIcon icon={FileCheck2} label="Available" variant="success" />
          ) : (
            <StatusIcon icon={FileX2} label="Missing" variant="muted" />
          )
      },
      createKebabColumn<Encounter>(
        (row) => [
          { label: "Edit encounter", icon: Pencil, hidden: !canUpdate, onSelect: () => onEdit(row) },
          {
            label: "Delete encounter",
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => onDelete(row)
          }
        ],
        { rowLabel: (row) => row.name }
      )
    ],
    // `onEdit` was missing here once: the kebab's "Edit encounter" called
    // whichever closure the first render happened to build.
    [canUpdate, canDelete, onEdit, onDelete]
  );
}
