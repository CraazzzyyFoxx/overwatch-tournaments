"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";

import { createKebabColumn } from "@/components/data-table";
import { StatusPill } from "@/components/kit/StatusPill";
import { GameLabel } from "@/components/workspace/GameLabel";
import { TOURNAMENT_STATUS_TONE } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.helpers";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { formatTournamentStages } from "@/lib/tournament/stages";
import { displayStatus } from "@/lib/tournament/status";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Tournament } from "@/types/tournament.types";

/** The tournament's name. */
function TournamentName({ tournament }: Readonly<{ tournament: Tournament }>) {
  return <span className="font-medium">{tournament.name}</span>;
}

/**
 * Unpublished first: a hidden tournament is a draft whatever its phase. A finished one is plain muted text: a pill
 * only for a state that wants attention, but a blank cell reads as missing data.
 */
function TournamentStatus({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("adminTournaments.list");
  const tStatus = useTranslations("common.statusBadge");
  if (tournament.is_hidden) return <StatusPill tone="neutral">{t("status.unpublished")}</StatusPill>;
  if (tournament.is_finished || tournament.status === "completed" || tournament.status === "archived") {
    return (
      <span className="text-xs text-muted-foreground">
        {tStatus(tournament.status === "archived" ? "archived" : "completed")}
      </span>
    );
  }
  const shown = displayStatus(tournament);
  return <StatusPill tone={TOURNAMENT_STATUS_TONE[shown]}>{tStatus(shown)}</StatusPill>;
}

/**
 * A tournament below `md`: its name, its game under "all games" (§6.1), its status and dates. Explicit rather than the
 * table's first three columns, which a column order saved before the game column existed would leave without the game.
 */
export function TournamentMobileCard({
  tournament,
  games
}: Readonly<{ tournament: Tournament; games?: Map<string, DisciplineDescriptor> }>) {
  const format = useFormatter();
  return (
    <div className="min-w-0 flex-1 space-y-0.5">
      <p className="truncate text-sm">
        <TournamentName tournament={tournament} />
      </p>
      {games ? (
        <GameLabel code={tournament.discipline} games={games} className="flex text-xs text-muted-foreground" />
      ) : null}
      <TournamentStatus tournament={tournament} />
      <p className="truncate text-xs tabular-nums text-muted-foreground">
        {formatDateRange(format, tournament.start_date, tournament.end_date)}
      </p>
    </div>
  );
}

/** The tournament row: what it is, whether it wants attention, when, and how it is staged. */
export function useTournamentColumns({
  canDelete,
  onDelete,
  games
}: Readonly<{
  canDelete: boolean;
  /** Stable identity required: the kebab closes over it. */
  onDelete: (tournament: Tournament) => void;
  /** Installed games by code, passed only under "all games" of a multi-game area: adds the "Игра" column (§6.1). */
  games?: Map<string, DisciplineDescriptor>;
}>): ColumnDef<Tournament>[] {
  const t = useTranslations("adminTournaments.list");
  const tDiscipline = useTranslations("common.discipline");
  const format = useFormatter();
  return useMemo<ColumnDef<Tournament>[]>(
    () => [
      {
        accessorKey: "name",
        header: t("columns.name"),
        cell: ({ row }) => <TournamentName tournament={row.original} />
      },
      ...(games
        ? [
            {
              id: "discipline",
              accessorKey: "discipline",
              header: tDiscipline("column"),
              enableSorting: false,
              cell: ({ row }) => <GameLabel code={row.original.discipline} games={games} />
            } satisfies ColumnDef<Tournament>
          ]
        : []),
      {
        accessorKey: "status",
        header: t("columns.status"),
        enableSorting: false,
        cell: ({ row }) => <TournamentStatus tournament={row.original} />
      },
      {
        accessorKey: "start_date",
        header: t("columns.dates"),
        cell: ({ row }) => (
          <span className="tabular-nums">
            {formatDateRange(format, row.original.start_date, row.original.end_date)}
          </span>
        )
      },
      {
        accessorKey: "stages",
        header: t("columns.stages"),
        enableSorting: false,
        cell: ({ row }) => {
          const stages = row.original.stages ?? [];
          if (stages.length === 0) return null;
          const stagesLabel = formatTournamentStages(stages);
          return (
            <div className="max-w-80 truncate text-muted-foreground" title={stagesLabel}>
              {stagesLabel}
            </div>
          );
        }
      },
      createKebabColumn<Tournament>(
        (tournament) => [
          { label: t("openHub"), href: `/admin/tournaments/${tournament.id}` },
          {
            label: t("delete"),
            onSelect: () => onDelete(tournament),
            destructive: true,
            hidden: !canDelete
          }
        ],
        { rowLabel: (tournament) => tournament.name }
      )
    ],
    [canDelete, format, games, onDelete, t, tDiscipline]
  );
}
