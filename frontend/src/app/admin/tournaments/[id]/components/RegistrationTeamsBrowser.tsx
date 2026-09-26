"use client";

import { useMemo, useState } from "react";
import { FolderInput } from "lucide-react";
import { useTranslations } from "next-intl";

import { AdminDataTable } from "@/components/data-table";
import { BulkBar } from "@/components/kit/BulkBar";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import { getRegistrationTeamStatus } from "@/lib/registration/team-tone";
import { cn } from "@/lib/utils";
import type { RegistrationTeam } from "@/types/registration-team.types";

import { EXPORT_SKIP_CODES, isExportEligible, type PendingConfirm } from "./registration-teams/model";
import { PlaceMemberDialog } from "./registration-teams/PlaceMemberDialog";
import { RenameTeamDialog } from "./registration-teams/RenameTeamDialog";
import { TeamConfirmDialog } from "./registration-teams/TeamConfirmDialog";
import { TeamInspectorPanel } from "./registration-teams/TeamInspectorPanel";
import { useRegistrationTeamActions } from "./registration-teams/useRegistrationTeamActions";
import {
  useRegistrationTeamColumns,
  type TeamRowHandlers
} from "./registration-teams/useRegistrationTeamColumns";

/**
 * Organizer view of the registered teams (§8 of the team-registration design).
 *
 * The reason this screen exists is the shortfall: a captain's team enters the
 * tournament only with a full roster, so "who is still incomplete" is the one
 * question an organizer asks before formation closes — it gets a column of its
 * own rather than hiding behind a status badge.
 *
 * It is a T2 browser (DESIGN.md): `AdminDataTable` rows, `FilterBar` chips
 * that live in the URL, one always-visible kebab per row, and the row detail in
 * `Inspector` at `?id=`. Unlike the public roster it also shows the
 * invites, and it is the only place that can reject a team or materialize the
 * complete ones into `tournament.team` (the export). Both are server-authorized;
 * the actions follow the same permissions, so a caller is never offered an
 * action that will 403.
 *
 * This file is the orchestrator: the reads and writes are in
 * `registration-teams/useRegistrationTeamActions`, the row vocabulary in
 * `useRegistrationTeamColumns`, and every panel and dialog is its own sibling.
 */
export function RegistrationTeamsBrowser({
  tournamentId,
  workspaceId
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
}>) {
  const t = useTranslations("registrationTeams");
  // Backend messages are English; every rejection here carries a machine code
  // and MUST go through the translator (§12.2).
  const tErr = useTranslations("registrationTeams.errors");
  const { canAccessPermission } = usePermissions();
  // `id` (the inspector) is navigation, not narrowing: it must not drop `page`
  // the way a filter change does.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });

  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [placeTarget, setPlaceTarget] = useState<RegistrationTeam | null>(null);
  const [renameTarget, setRenameTarget] = useState<RegistrationTeam | null>(null);

  const canManageTeams = canAccessPermission("team.update", workspaceId);
  const canExport = canAccessPermission("team.create", workspaceId);

  const actions = useRegistrationTeamActions({
    tournamentId,
    workspaceId,
    closeConfirm: () => setConfirm(null),
    closeRename: () => setRenameTarget(null),
    closePlace: () => setPlaceTarget(null)
  });
  const { teams, setActionError } = actions;

  const filterDefs: FilterDef[] = useMemo(
    () => [
      {
        key: "state",
        label: t("admin.filterStatus"),
        kind: "single",
        options: (["forming", "complete", "exported", "terminal"] as const).map((value) => ({
          value,
          label: t(`admin.filters.${value}`)
        }))
      },
      {
        key: "admission",
        label: t("admin.admission"),
        kind: "single",
        options: (["pending", "accepted", "waitlisted"] as const).map((value) => ({
          value,
          label: t(`admission.${value}`)
        }))
      }
    ],
    [t]
  );
  const filters = useFilters(filterDefs);
  const stateFilter = String(filters.values.state ?? "");
  const admissionFilter = String(filters.values.admission ?? "");

  // One read serves every chip: a tournament's registered teams are a few dozen
  // rows, so narrowing is local and a chip costs no request.
  const visibleTeams = useMemo(
    () =>
      teams.filter((team) => {
        if (stateFilter) {
          const status = getRegistrationTeamStatus(team);
          const matches =
            stateFilter === "terminal"
              ? status === "rejected" || status === "disbanded"
              : status === stateFilter;
          if (!matches) return false;
        }
        if (admissionFilter && (team.admission ?? "pending") !== admissionFilter) return false;
        return true;
      }),
    [teams, stateFilter, admissionFilter]
  );

  const openId = searchParams?.get("id") ?? null;
  const selectedTeam = openId
    ? (teams.find((team) => String(team.id) === openId) ?? null)
    : null;
  const selectedIndex = selectedTeam
    ? visibleTeams.findIndex((team) => team.id === selectedTeam.id)
    : -1;

  const disabled = actions.busy || actions.isFetching;
  const inlineError = actions.actionError ? (
    <Alert variant="destructive" role="alert"><AlertDescription>{actions.actionError}</AlertDescription></Alert>
  ) : null;

  // Every one of these only clears the error and names the act; the columns
  // memo closes over the object, so it keeps one identity for the mount.
  const rowHandlers = useMemo<TeamRowHandlers>(
    () => ({
      onRename: (team) => {
        setActionError(null);
        setRenameTarget(team);
      },
      onPlace: (team) => {
        setActionError(null);
        setPlaceTarget(team);
      },
      onUnlock: (team) => {
        setActionError(null);
        setConfirm({ kind: "unlock", team });
      },
      onResetCap: (team) => {
        setActionError(null);
        setConfirm({ kind: "resetCap", team });
      },
      onReExport: (team) => {
        setActionError(null);
        setConfirm({ kind: "export", teams: [team] });
      },
      onReject: (team) => {
        setActionError(null);
        setConfirm({ kind: "reject", team });
      }
    }),
    [setActionError]
  );

  const columns = useRegistrationTeamColumns({ canManageTeams, canExport, handlers: rowHandlers });

  return (
    <>
      <div
        className={cn(
          "grid min-w-0 items-start gap-4",
          selectedTeam && "lg:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]"
        )}
      >
        <div className="flex min-h-0 min-w-0 flex-col gap-3">
          {inlineError}
          {/* The export materializes registered TEAMS. A player on no team is
              invisible to it, and on a team-registration tournament neither the
              balancer nor the draft runs either — so they silently never become
              a tournament.player. Before pressing export is the only moment this
              is still cheap to fix, which is why the warning sits above the
              table rather than in the toast. */}
          {actions.unassignedPlayers > 0 && (
            <Alert>
              <AlertDescription>
                {t("admin.unassigned", { count: actions.unassignedPlayers })}
              </AlertDescription>
            </Alert>
          )}

          {actions.exportResult && (
            <Alert role="status">
              <AlertDescription className="space-y-2">
                <p>{t("admin.exportResult", { imported: actions.exportResult.imported_teams, removed: actions.exportResult.removed_teams, players: actions.exportResult.created_players, skipped: actions.exportResult.skipped.length })}</p>
                {actions.exportResult.skipped.length > 0 && (
                  <ul className="list-inside list-disc">
                    {actions.exportResult.skipped.map((item) => {
                      const code = EXPORT_SKIP_CODES.find((known) => known === item.code);
                      return <li key={item.team_id}>{item.name}: {code ? t(`admin.skipReason.${code}`) : t("admin.actionFailed")}</li>;
                    })}
                  </ul>
                )}
              </AlertDescription>
            </Alert>
          )}

          {actions.isError ? (
            <Alert variant="destructive" role="alert">
              <AlertDescription>
                {translateRegistrationTeamError(tErr, actions.error, t("admin.loadFailed"))}
                <Button type="button" variant="outline" size="sm" className="ml-2" disabled={actions.isFetching} onClick={actions.refetch}>{t("admin.retry")}</Button>
              </AlertDescription>
            </Alert>
          ) : (
            <AdminDataTable<RegistrationTeam>
              rows={visibleTeams}
              isLoading={actions.isFetching}
              columns={columns}
              getRowId={(team) => String(team.id)}
              filterKey={filters.filterKey}
              initialPageSize={25}
              paging="infinite"
              rowUnit="teams"
              cellAlign="top"
              searchPlaceholder={t("admin.search")}
              emptyMessage={t("list.empty")}
              columnsStorageKey="registration-teams-table-columns"
              inspectorId={openId}
              onRowClick={(row) => {
                setActionError(null);
                setParams({ id: String(row.original.id) });
              }}
              // Only a roster the server would actually materialize can be
              // picked: selecting one it will skip is an export that silently
              // did nothing.
              enableRowSelection={
                canExport
                  ? (row) =>
                      row.original.exported_team_id == null && isExportEligible(row.original)
                  : undefined
              }
              bulkActions={
                canExport
                  ? (selected, clear) => (
                      <BulkBar count={selected.length} unit="teams" onClear={clear}>
                        <Button
                          type="button"
                          size="sm"
                          disabled={disabled}
                          onClick={() => {
                            setActionError(null);
                            setConfirm({ kind: "export", teams: selected, clear });
                          }}
                        >
                          {actions.isExporting ? (
                            <Spinner className="mr-2" />
                          ) : (
                            <FolderInput className="mr-2 h-4 w-4" aria-hidden />
                          )}
                          {t("admin.exportSelected")}
                        </Button>
                      </BulkBar>
                    )
                  : undefined
              }
              toolbar={<FilterBar defs={filterDefs} filters={filters} />}
              actions={
                <span
                  className="shrink-0 text-xs tabular-nums text-muted-foreground"
                  title={t("list.count", { count: actions.total })}
                >
                  {actions.total}
                </span>
              }
            />
          )}
        </div>

        <Inspector
          openId={selectedTeam ? openId : null}
          onClose={() => setParams({ id: null })}
          title={selectedTeam?.name ?? ""}
          subtitle={selectedTeam ? t(`status.${getRegistrationTeamStatus(selectedTeam)}`) : undefined}
          onPrev={
            selectedIndex > 0
              ? () => setParams({ id: String(visibleTeams[selectedIndex - 1].id) })
              : undefined
          }
          onNext={
            selectedIndex >= 0 && selectedIndex < visibleTeams.length - 1
              ? () => setParams({ id: String(visibleTeams[selectedIndex + 1].id) })
              : undefined
          }
        >
          {selectedTeam ? (
            <TeamInspectorPanel
              team={selectedTeam}
              tournamentId={tournamentId}
              workspaceId={workspaceId}
              canManageTeams={canManageTeams}
              disabled={disabled}
              inlineError={inlineError}
              actions={actions}
            />
          ) : null}
        </Inspector>
      </div>

      <TeamConfirmDialog
        confirm={confirm}
        busy={actions.busy}
        rejecting={actions.isRejecting}
        inlineError={inlineError}
        onOpenChange={(open) => {
          if (open || actions.busy) return;
          setConfirm(null);
        }}
        onConfirm={(decision) => {
          if (!confirm) return;
          setActionError(null);
          if (confirm.kind === "unlock") {
            actions.unlock(confirm.team);
            return;
          }
          if (confirm.kind === "resetCap") {
            actions.resetCap(confirm.team);
            return;
          }
          if (confirm.kind === "export") {
            const teamIds = confirm.teams.map((team) => team.id);
            if (!teamIds.length) return;
            // The teams were named back before this click; one that changed
            // underneath is a different decision than the confirmed one.
            const drifted = teamIds.some((id) => {
              const current = teams.find((team) => team.id === id);
              const confirmed = confirm.teams.find((team) => team.id === id);
              return (
                !current ||
                !isExportEligible(current) ||
                current.exported_team_id !== confirmed?.exported_team_id
              );
            });
            if (drifted) {
              setActionError(t("admin.exportSelectionChanged"));
              return;
            }
            actions.exportTeams(teamIds, confirm.clear);
            return;
          }
          if (!decision) return;
          actions.reject({
            teamId: confirm.team.id,
            withdrawMembers: decision.withdrawMembers,
            reason: decision.reason
          });
        }}
      />

      <RenameTeamDialog
        team={renameTarget}
        onClose={() => setRenameTarget(null)}
        actions={actions}
      />

      <PlaceMemberDialog
        tournamentId={tournamentId}
        workspaceId={workspaceId}
        team={placeTarget}
        onClose={() => setPlaceTarget(null)}
        actions={actions}
      />
    </>
  );
}
