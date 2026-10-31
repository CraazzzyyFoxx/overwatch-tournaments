"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { Trash2 } from "lucide-react";

import TeamName from "@/components/TeamName";
import { createKebabColumn } from "@/components/data-table";
import type { Team } from "@/types/team.types";

/** The roster row: the team, its strength, its size and the tournament it plays in. */
export function useTeamColumns({
  canDelete,
  onDelete
}: Readonly<{
  canDelete: boolean;
  /** Stable identity required: the kebab column closes over it. */
  onDelete: (team: Team) => void;
}>): ColumnDef<Team>[] {
  const t = useTranslations("adminPeople.teams");
  return useMemo<ColumnDef<Team>[]>(
    () => [
      {
        accessorKey: "name",
        header: t("name"),
        cell: ({ row }) => (
          <Link href={`/admin/teams/${row.original.id}`} className="block min-w-0 underline-offset-2 hover:underline">
            <TeamName team={row.original} size="xs" nameClassName="font-medium" />
          </Link>
        )
      },
      {
        accessorKey: "avg_sr",
        header: t("avgSr"),
        cell: ({ row }) => <div className="tabular-nums">{row.original.avg_sr.toFixed(0)}</div>
      },
      {
        accessorKey: "total_sr",
        header: t("labels.totalSr"),
        cell: ({ row }) => <div className="tabular-nums">{row.original.total_sr}</div>
      },
      {
        accessorKey: "players",
        header: t("players"),
        enableSorting: false,
        cell: ({ row }) => <div className="tabular-nums">{row.original.players?.length ?? 0}</div>
      },
      {
        accessorKey: "tournament",
        header: t("labels.tournament"),
        enableSorting: false,
        cell: ({ row }) =>
          row.original.tournament ? (
            <div className="text-sm text-muted-foreground">{row.original.tournament.name}</div>
          ) : null
      },
      createKebabColumn<Team>(
        (row) => [
          { label: t("open"), href: `/admin/teams/${row.id}` },
          {
            label: t("delete"),
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => onDelete(row)
          }
        ],
        { rowLabel: (row) => row.name }
      )
    ],
    [canDelete, onDelete, t]
  );
}
