"use client";

import { useMemo } from "react";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";

import { AdminDataTable, adminColumnMeta } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { PageStateCard } from "@/components/ui/page-state-card";
import userService from "@/services/user.service";
import type { AchievementRarity } from "@/types/achievement.types";

/**
 * What this person has earned.
 *
 * Read-only: an achievement's rules, evaluation and overrides all belong to
 * the achievement, not to a holder, so every write lives on the achievement's
 * own page and this tab links there.
 */
export function PersonAchievementsTab({ personId }: Readonly<{ personId: number }>) {
  const achievementsQuery = useQuery({
    queryKey: ["admin", "person", personId, "achievements"],
    queryFn: () => userService.getUserAchievements(personId)
  });

  const columns = useMemo<ColumnDef<AchievementRarity>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Achievement",
        meta: adminColumnMeta<AchievementRarity>({
          sticky: true,
          searchValue: (row) => `${row.name} ${row.slug}`
        }),
        cell: ({ row }) => (
          <Link
            className="font-medium underline-offset-4 hover:underline"
            href={`/admin/achievements/${row.original.id}`}
          >
            {row.original.name}
          </Link>
        )
      },
      {
        accessorKey: "category",
        header: "Category",
        cell: ({ row }) =>
          row.original.category ? (
            <Badge variant="outline" className="font-normal capitalize">
              {row.original.category}
            </Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          )
      },
      {
        accessorKey: "count",
        header: "Times",
        size: 90,
        meta: adminColumnMeta<AchievementRarity>({ numeric: true, align: "right" }),
        cell: ({ row }) => <span className="tabular-nums">{row.original.count}</span>
      },
      {
        id: "tournaments",
        header: "Tournaments",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.tournaments.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <span className="truncate text-sm text-muted-foreground">
              {row.original.tournaments.map((tournament) => tournament.name).join(", ")}
            </span>
          )
      }
    ],
    []
  );

  if (achievementsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load achievements"
        onAction={() => void achievementsQuery.refetch()}
        actionLabel="Try again"
      />
    );
  }

  return (
    <AdminDataTable<AchievementRarity>
      rows={achievementsQuery.data ?? []}
      isLoading={achievementsQuery.isLoading}
      columns={columns}
      initialPageSize={20}
      getRowId={(row) => String(row.id)}
      searchPlaceholder="Search achievements…"
      emptyMessage="This person has not earned an achievement yet."
    />
  );
}
