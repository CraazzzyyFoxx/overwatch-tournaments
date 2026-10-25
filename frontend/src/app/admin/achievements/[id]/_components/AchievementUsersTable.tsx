"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";

import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import { DataTable } from "@/components/data-table";
import { SettingGroup } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";

import type { RuleUserRow } from "../_hooks/useAchievementDetail";

/**
 * Who has earned this achievement: sorted and paged on the server, narrowed to
 * one tournament when the rule's game has more than one to pick from. The
 * total is the table footer's; the heading does not repeat it. The query key
 * starts with `ruleUsers`, so an evaluation run refreshes it.
 */
export function AchievementUsersTable({
  workspaceId,
  ruleId,
  tournaments,
  onAddOverride,
}: Readonly<{
  workspaceId: number;
  ruleId: number;
  /** The rule's game's tournaments. */
  tournaments: Tournament[];
  onAddOverride: () => void;
}>) {
  const t = useTranslations("adminAchievements");
  const format = useFormatter();
  const [tournamentId, setTournamentId] = useState<number | undefined>(undefined);

  const columns: ColumnDef<RuleUserRow>[] = [
    {
      accessorKey: "user_name",
      header: t("common.user"),
      cell: ({ row }) => (
        <Link href={`/users/${row.original.user_id}`} className="text-primary hover:underline">
          {row.original.user_name}
        </Link>
      ),
    },
    {
      accessorKey: "count",
      header: t("common.count"),
      size: 100,
      cell: ({ row }) => <span className="tabular-nums">{row.original.count}</span>,
    },
    {
      accessorKey: "last_tournament_id",
      header: t("common.lastTournament"),
      cell: ({ row }) => {
        const id = row.original.last_tournament_id;
        if (id == null) return null;
        return (
          <Link href={`/tournaments/${id}`} className="text-primary hover:underline">
            {tournaments.find((tournament) => tournament.id === id)?.name ?? t("common.tournamentId", { id })}
          </Link>
        );
      },
    },
    {
      accessorKey: "first_qualified",
      header: t("common.firstEarned"),
      cell: ({ row }) =>
        row.original.first_qualified ? (
          <span className="text-muted-foreground">
            {format.dateTime(new Date(row.original.first_qualified), { dateStyle: "medium" })}
          </span>
        ) : null,
    },
  ];

  return (
    <SettingGroup
      id="users"
      title={t("common.users")}
      actions={
        <Button variant="outline" size="sm" onClick={onAddOverride}>
          {t("detail.manualOverride")}
        </Button>
      }
      flush
    >
      <DataTable<RuleUserRow>
        framed={false}
        queryKey={(page, _search, pageSize, sortField, sortDir) => [
          ...achievementQueryKeys.ruleUsersPage(workspaceId, ruleId, tournamentId, sortField, sortDir),
          page,
          pageSize,
        ]}
        queryFn={(page, _search, pageSize, sortField, sortDir) =>
          adminService.getAchievementRuleUsers(workspaceId, ruleId, {
            page,
            per_page: pageSize,
            tournament_id: tournamentId,
            sort: sortField ?? undefined,
            order: sortDir,
          })
        }
        initialSort={{ field: "count", dir: "desc" }}
        filterKey={String(tournamentId ?? "")}
        columns={columns}
        getRowId={(row) => String(row.user_id)}
        emptyMessage={t("detail.noUsers")}
        actions={
          tournaments.length > 1 ? (
            <div className="w-64">
              <TournamentCombobox
                tournaments={tournaments}
                value={tournamentId}
                onValueChange={setTournamentId}
                placeholder={t("detail.allTournaments")}
              />
            </div>
          ) : undefined
        }
      />
    </SettingGroup>
  );
}
