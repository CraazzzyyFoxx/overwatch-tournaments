"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { DataTable, type TableCommand } from "@/components/data-table";
import type { Team } from "@/types/team.types";
import { useChallongeTeamSync } from "./teams-tab/ChallongeTeamSync";
import { useTeamColumns } from "./teams-tab/useTeamColumns";

interface TournamentTeamsTabProps {
  tournamentId: number;
  teams: Team[];
  hasChallongeSource: boolean;
  /** `team.create`: the Challonge sync and the balancer both write teams. */
  canImportTeams: boolean;
  /** Any team or player write: the teams workspace is where rosters are edited. */
  canManageTeams: boolean;
}

/** Teams › Roster (T2): the tournament's teams; a row opens the team page. */
export function TournamentTeamsTab({
  tournamentId,
  teams,
  hasChallongeSource,
  canImportTeams,
  canManageTeams
}: Readonly<TournamentTeamsTabProps>) {
  const t = useTranslations("adminTournament.teams");
  const router = useRouter();
  const columns = useTeamColumns();
  const challongeSync = useChallongeTeamSync({ tournamentId, hasChallongeSource, canImportTeams });

  const commands: TableCommand[] = [
    challongeSync.command,
    {
      // D30/A-O2: the sole UI entry to the balancer tool after the shell removal (v3.1).
      id: "open-balancer",
      label: t("openBalancer"),
      href: `/balancer?tournament=${tournamentId}`,
      hidden: !canImportTeams
    },
    {
      id: "manage",
      label: t("manage"),
      href: `/admin/teams?tournament=${tournamentId}`,
      primary: true,
      hidden: !canManageTeams
    }
  ];

  return (
    <>
      <DataTable
        rows={teams}
        columns={columns}
        getRowId={(team) => String(team.id)}
        searchPlaceholder={t("searchTeamsPlayers")}
        rowUnit={t("rowUnit")}
        onRowClick={(row) => router.push(`/admin/teams/${row.original.id}`)}
        emptyMessage={t("empty")}
        commands={commands}
      />
      {challongeSync.dialog}
    </>
  );
}
