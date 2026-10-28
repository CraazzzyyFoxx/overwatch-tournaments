"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleCheck, CircleX, Lock, Pencil, Trash2 } from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { createKebabColumn } from "@/components/data-table";
import { PlaceBadge } from "@/components/ui/place-badge";
import TeamName from "@/components/TeamName";
import { cn } from "@/lib/utils";
import type { Stage, Standings } from "@/types/tournament.types";

import { standingScopeLabel } from "./model";

/** One row per ranked team: its place, its record, and the tiebreakers behind it. */
export function useStandingsColumns({
  canUpdate,
  canDelete,
  stageId,
  scopedStage,
  onEdit,
  onDelete
}: Readonly<{
  canUpdate: boolean;
  canDelete: boolean;
  stageId?: number;
  /** The stage `stageId` names, once loaded: its group count decides the Group column. */
  scopedStage: Stage | undefined;
  /** Stable identity required: the kebab column closes over both. */
  onEdit: (standing: Standings) => void;
  onDelete: (standing: Standings) => void;
}>): ColumnDef<Standings>[] {
  const t = useTranslations("adminTournaments.standings");
  return useMemo<ColumnDef<Standings>[]>(
    () => [
      {
        accessorKey: "position",
        header: "#",
        size: 72,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            {row.original.position >= 1 && row.original.position <= 3 ? (
              <PlaceBadge place={row.original.position} />
            ) : (
              <span className="tabular-nums">#{row.original.position}</span>
            )}
            {row.original.is_pinned ? (
              <span title={t("pinnedPlace")} className="text-muted-foreground">
                <Lock aria-hidden className="size-3.5" />
                <span className="sr-only">{t("pinnedPlace")}</span>
              </span>
            ) : null}
          </div>
        )
      },
      {
        accessorKey: "team",
        header: t("columns.team"),
        enableSorting: false,
        cell: ({ row }) => {
          const status = row.original.swiss_status;
          return (
            <div className="flex min-w-0 items-center gap-2">
              {row.original.team ? (
                <TeamName
                  team={row.original.team}
                  size="xs"
                  nameClassName={cn("font-medium", status === "eliminated" && "text-muted-foreground")}
                />
              ) : null}
              {status === "qualified" ? (
                <StatusIcon icon={CircleCheck} label={t("swissQualified")} variant="success" className="shrink-0" />
              ) : status === "eliminated" ? (
                <StatusIcon icon={CircleX} label={t("swissEliminated")} variant="muted" className="shrink-0" />
              ) : null}
            </div>
          );
        }
      },
      // Scoped to one stage, the stage itself is the pinned chip: the column only
      // earns its place when the stage has groups to tell apart.
      ...(stageId == null
        ? [
            {
              id: "scope",
              header: t("columns.stage"),
              enableSorting: false,
              cell: ({ row }) => (
                <span className="text-sm">{standingScopeLabel(row.original, t("unassigned"))}</span>
              )
            } satisfies ColumnDef<Standings>
          ]
        : (scopedStage?.items.length ?? 0) > 1
          ? [
              {
                id: "scope",
                header: t("columns.group"),
                enableSorting: false,
                cell: ({ row }) => (
                  <span className="text-sm">{row.original.stage_item?.name}</span>
                )
              } satisfies ColumnDef<Standings>
            ]
          : []),
      {
        accessorKey: "matches",
        header: t("columns.matches"),
        size: 72,
        cell: ({ row }) => <span className="tabular-nums">{row.original.matches}</span>
      },
      {
        accessorKey: "win",
        header: t("winsShort"),
        size: 64,
        cell: ({ row }) => <span className="tabular-nums text-success">{row.original.win}</span>
      },
      {
        accessorKey: "draw",
        header: t("drawsShort"),
        size: 64,
        cell: ({ row }) => <span className="tabular-nums">{row.original.draw}</span>
      },
      {
        accessorKey: "lose",
        header: t("lossesShort"),
        size: 64,
        cell: ({ row }) => <span className="tabular-nums text-danger">{row.original.lose}</span>
      },
      {
        accessorKey: "points",
        header: t("columns.points"),
        size: 80,
        cell: ({ row }) => (
          <span className="font-bold tabular-nums">{row.original.points.toFixed(1)}</span>
        )
      },
      {
        accessorKey: "buchholz",
        header: t("columns.buchholz"),
        size: 110,
        // Median and full are separate tiebreakers, and a lone number reads as
        // whichever one the organizer assumes. Show the pair, matching the
        // public table.
        cell: ({ row }) =>
          row.original.buchholz == null ? null : (
            <span className="text-sm tabular-nums" title={t("buchholzTitle")}>
              {row.original.full_buchholz == null
                ? row.original.buchholz.toFixed(2)
                : `${row.original.buchholz.toFixed(2)} / ${row.original.full_buchholz.toFixed(2)}`}
            </span>
          )
      },
      {
        accessorKey: "tb",
        header: t("columns.tiebreak"),
        size: 72,
        cell: ({ row }) =>
          row.original.tb == null ? null : (
            <span className="text-sm tabular-nums">{row.original.tb}</span>
          )
      },
      createKebabColumn<Standings>(
        (row) => [
          {
            label: t("edit"),
            icon: Pencil,
            hidden: !canUpdate,
            onSelect: () => onEdit(row)
          },
          {
            label: t("delete"),
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => onDelete(row)
          }
        ],
        { rowLabel: (row) => t("rowLabel", { name: row.team?.name ?? t("team") }) }
      )
    ],
    [t, canUpdate, canDelete, onEdit, onDelete, stageId, scopedStage]
  );
}
