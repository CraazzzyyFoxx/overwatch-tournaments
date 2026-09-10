"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  ClipboardList,
  Gauge,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Scale,
  Sparkles,
  Users
} from "lucide-react";

import TeamName from "@/components/TeamName";
import { AdminCombobox, AdminComboboxCheck } from "@/components/admin/AdminCombobox";
import {
  AdminDetailTableShell,
  getAdminDetailTableStyles
} from "@/components/admin/AdminDetailTable";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { WizardShell } from "@/components/admin/kit/WizardShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type {
  ChallongeTeamMapping,
  ChallongeTeamPreviewParticipant,
  ChallongeTeamPreviewTeam
} from "@/types/admin.types";
import type { Team } from "@/types/team.types";
import { TOURNAMENT_DETAIL_PREVIEW_LIMIT } from "./tournamentWorkspace.helpers";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

interface TournamentTeamsTabProps {
  tournamentId: number;
  teams: Team[];
  stagesCount: number;
  hasChallongeSource: boolean;
  canCreateTeam: boolean;
  canUpdateTeam: boolean;
  canDeleteTeam: boolean;
  canImportTeams: boolean;
  canCreatePlayer: boolean;
  canUpdatePlayer: boolean;
  canDeletePlayer: boolean;
}

const UNMAPPED_TEAM_VALUE = "unmapped";

function getChallongeParticipantKey(participant: ChallongeTeamPreviewParticipant) {
  return `${participant.participant_id}:${participant.group_id ?? "none"}`;
}

function summarizeChallongeSyncResult(result: {
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
}) {
  return (
    <span className="tabular-nums">
      {result.created} created, {result.updated} updated, {result.unchanged} unchanged,{" "}
      {result.skipped} skipped
    </span>
  );
}

/**
 * Searchable internal-team picker for one Challonge participant.
 *
 * A plain `<Select>` listed every team in creation order with no way to type:
 * a mix roster runs to dozens of teams whose Challonge participant name
 * ("litnik team") differs from the internal one ("litnik"), which is precisely
 * the case that lands here — auto-mapping only matches on an exact normalized
 * name, so whatever it could resolve is already mapped before this dialog opens.
 *
 * Search covers the internal name, the balancer name and the numeric id, because
 * all three are what an admin actually has in hand while reading the Challonge
 * side. Own `open`/`searchValue` state per row: the shell is controlled, and one
 * row's popover must not know about another's.
 */
function ChallongeTeamPicker({
  participant,
  teams,
  value,
  onChange
}: Readonly<{
  participant: ChallongeTeamPreviewParticipant;
  teams: ChallongeTeamPreviewTeam[];
  value: string;
  onChange: (next: string) => void;
}>) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const selected = teams.find((team) => String(team.id) === value);

  const select = (next: string) => {
    onChange(next);
    setOpen(false);
    setSearchValue("");
  };

  return (
    <AdminCombobox
      open={open}
      onOpenChange={setOpen}
      label={selected ? selected.name : "Unmapped"}
      // The visible label repeats down the column, so it cannot name the control.
      triggerAriaLabel={`Internal team for ${participant.name}`}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder="Search team…"
      searchLabel={`Search internal team for ${participant.name}`}
      emptyMessage="No teams match that search. Try the balancer name or the numeric id."
      clear={
        selected
          ? {
              label: "Unmapped",
              value: "challonge-unmap-participant",
              onSelect: () => select(UNMAPPED_TEAM_VALUE)
            }
          : undefined
      }
    >
      <CommandGroup>
        {teams.map((team) => (
          <CommandItem
            key={team.id}
            value={`${team.name} ${team.balancer_name} ${team.id}`}
            onSelect={() => select(String(team.id))}
          >
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate">{team.name}</span>
              {team.balancer_name && team.balancer_name !== team.name ? (
                <span className="truncate text-xs text-muted-foreground">{team.balancer_name}</span>
              ) : null}
            </div>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">#{team.id}</span>
            <AdminComboboxCheck selected={String(team.id) === value} />
          </CommandItem>
        ))}
      </CommandGroup>
    </AdminCombobox>
  );
}

export function TournamentTeamsTab({
  tournamentId,
  teams,
  stagesCount,
  hasChallongeSource,
  canCreateTeam,
  canUpdateTeam,
  canDeleteTeam,
  canImportTeams,
  canCreatePlayer,
  canUpdatePlayer,
  canDeletePlayer
}: Readonly<TournamentTeamsTabProps>) {
  const queryClient = useQueryClient();
  const tableStyles = getAdminDetailTableStyles("compact");

  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // `?challongeSync=1` exists so the Integrations card can send an admin straight
  // to the mapping table that clears its "N participants not mapped" failure —
  // otherwise the error is on one tab and its only fix on another. Read once for
  // the initial value and stripped on mount: with the param left in place a
  // refresh (or a Back into this page) would reopen a dialog nobody asked for.
  const [challongeSyncDialogOpen, setChallongeSyncDialogOpen] = useState(
    () => searchParams.get("challongeSync") === "1"
  );
  const [challongeMappingDraft, setChallongeMappingDraft] = useState<Record<string, string>>({});
  const [challongeSyncStep, setChallongeSyncStep] = useState<"map" | "confirm">("map");

  useEffect(() => {
    if (searchParams.get("challongeSync") !== "1") {
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.delete("challongeSync");
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const canManageRoster = canCreatePlayer || canUpdatePlayer || canDeletePlayer;
  const canManageTeams = canCreateTeam || canUpdateTeam || canDeleteTeam || canManageRoster;
  const teamsAdminHref = `/admin/teams?tournament=${tournamentId}`;

  const { data: challongePreview, isLoading: isChallongePreviewLoading } = useQuery({
    queryKey: ["admin", "challonge-team-sync-preview", tournamentId],
    queryFn: () => adminService.getChallongeTeamSyncPreview(tournamentId),
    enabled: challongeSyncDialogOpen && hasChallongeSource
  });

  const syncTeamsMutation = useMutation({
    mutationFn: (mappings: ChallongeTeamMapping[]) =>
      adminService.syncTeamsFromChallonge(tournamentId, { mappings }),
    onSuccess: (result) => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      setChallongeSyncDialogOpen(false);
      notify.success("Teams synced from Challonge", {
        description: summarizeChallongeSyncResult(result)
      });
    }
  });

  const challongeParticipants = useMemo(
    () => challongePreview?.participants ?? [],
    [challongePreview?.participants]
  );
  const challongeTeamOptions = useMemo(
    () => challongePreview?.teams ?? [],
    [challongePreview?.teams]
  );
  const challongeTeamsById = useMemo(
    () => new Map(challongeTeamOptions.map((team) => [team.id, team])),
    [challongeTeamOptions]
  );
  const getChallongeMappingValue = (participant: ChallongeTeamPreviewParticipant) =>
    challongeMappingDraft[getChallongeParticipantKey(participant)] ??
    (participant.mapped_team_id != null ? String(participant.mapped_team_id) : UNMAPPED_TEAM_VALUE);
  const activeUnmappedParticipants = challongeParticipants.filter(
    (participant) =>
      participant.active && getChallongeMappingValue(participant) === UNMAPPED_TEAM_VALUE
  );
  const selectedChallongeMappings = challongeParticipants.flatMap((participant) => {
    const value = getChallongeMappingValue(participant);
    if (!value || value === UNMAPPED_TEAM_VALUE) {
      return [];
    }

    const teamId = Number.parseInt(value, 10);
    if (Number.isNaN(teamId)) {
      return [];
    }

    return [
      {
        participant_id: participant.participant_id,
        group_id: participant.group_id,
        team_id: teamId
      }
    ];
  });
  const canSubmitChallongeMappings =
    !isChallongePreviewLoading &&
    challongeParticipants.length > 0 &&
    selectedChallongeMappings.length > 0 &&
    activeUnmappedParticipants.length === 0;

  // The confirm step reads back what will be written, so it needs the names
  // behind the ids the request carries.
  const onConfirmStep = challongeSyncStep === "confirm";
  const confirmedChallongeRows = challongeParticipants.flatMap((participant) => {
    const value = getChallongeMappingValue(participant);
    const team = value === UNMAPPED_TEAM_VALUE ? undefined : challongeTeamsById.get(Number(value));
    return team
      ? [
          {
            key: getChallongeParticipantKey(participant),
            participant: participant.name,
            team: team.name,
            group: participant.group_name ?? "Main"
          }
        ]
      : [];
  });

  const openChallongeSyncDialog = () => {
    syncTeamsMutation.reset();
    setChallongeMappingDraft({});
    setChallongeSyncStep("map");
    setChallongeSyncDialogOpen(true);
  };

  const closeChallongeSyncDialog = () => {
    if (syncTeamsMutation.isPending) {
      return;
    }

    setChallongeSyncDialogOpen(false);
    setChallongeMappingDraft({});
    setChallongeSyncStep("map");
  };

  const applyChallongeSuggestions = () => {
    setChallongeMappingDraft((current) => {
      const next = { ...current };
      for (const participant of challongeParticipants) {
        if (participant.suggested_team_id != null) {
          next[getChallongeParticipantKey(participant)] = String(participant.suggested_team_id);
        }
      }
      return next;
    });
  };

  const submitChallongeMappings = () => {
    if (!canSubmitChallongeMappings) {
      notify.error("Mappings incomplete", {
        description: `Map the remaining ${activeUnmappedParticipants.length} active Challonge participants before syncing.`
      });
      return;
    }

    syncTeamsMutation.mutate(selectedChallongeMappings);
  };

  const rosterPlayersCount = teams.reduce((sum, team) => sum + team.players.length, 0);
  const teamsWithRosterCount = teams.filter((team) => team.players.length > 0).length;
  const emptyRosterTeamsCount = teams.length - teamsWithRosterCount;
  const averageSr =
    teams.length > 0
      ? Math.round(teams.reduce((sum, team) => sum + team.avg_sr, 0) / teams.length)
      : 0;

  const syncTeamsButton = canImportTeams ? (
    <Button
      variant="outline"
      onClick={openChallongeSyncDialog}
      disabled={syncTeamsMutation.isPending || !hasChallongeSource}
    >
      <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
      Sync teams
    </Button>
  ) : null;

  return (
    <>
      <StatTileGrid className="mb-4">
        <StatTile
          label="Teams"
          value={teams.length}
          detail={`${stagesCount} stage${stagesCount === 1 ? "" : "s"} configured`}
          icon={Users}
        />
        <StatTile
          label="Roster records"
          value={rosterPlayersCount}
          detail={`${teamsWithRosterCount}/${teams.length} teams have players`}
          icon={ClipboardList}
        />
        <StatTile
          label="Average SR"
          value={teams.length ? averageSr : "—"}
          detail="Across loaded teams"
          icon={Gauge}
        />
        <StatTile
          label="Empty rosters"
          value={emptyRosterTeamsCount}
          detail={
            emptyRosterTeamsCount > 0
              ? "Add players before seeding stages"
              : "Every team has players"
          }
          icon={AlertTriangle}
          tone={emptyRosterTeamsCount > 0 ? "warning" : "success"}
        />
      </StatTileGrid>

      <Card className="border-border/40">
        <CardHeader className="gap-3 pb-3">
          <div className="min-w-0">
            <CardTitle asChild className="text-base font-semibold">
              <h2>Team operations</h2>
            </CardTitle>
            <CardDescription className="mt-1">
              Review tournament rosters, sync external mappings, or jump into the dedicated team
              workspace for detailed edits.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            {syncTeamsButton}
            {canImportTeams ? (
              <Button asChild variant="outline">
                {/* D30/A-O2: the sole UI entry to the balancer tool after the shell removal (v3.1). */}
                <Link href={`/balancer?tournament=${tournamentId}`}>
                  <Scale className="mr-2 h-4 w-4" aria-hidden />
                  Open balancer
                </Link>
              </Button>
            ) : null}
            {canManageTeams ? (
              <Button asChild>
                <Link href={teamsAdminHref}>
                  <Plus className="mr-2 h-4 w-4" aria-hidden />
                  Manage teams
                </Link>
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          <AdminDetailTableShell variant="compact">
            <Table>
              <TableHeader>
                <TableRow className={tableStyles.headerRow}>
                  <TableHead className={tableStyles.head}>Team</TableHead>
                  <TableHead className={tableStyles.head}>Avg SR</TableHead>
                  <TableHead className={tableStyles.head}>Total SR</TableHead>
                  <TableHead className={tableStyles.head}>Players</TableHead>
                  <TableHead className={`${tableStyles.head} text-right`}>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {teams.length ? (
                  teams.slice(0, TOURNAMENT_DETAIL_PREVIEW_LIMIT).map((team) => (
                    <TableRow key={team.id} className={tableStyles.row}>
                      <TableCell className={tableStyles.cell}>
                        <TeamName team={team} size="xs" nameClassName="font-medium" />
                      </TableCell>
                      <TableCell className={`${tableStyles.cell} tabular-nums`}>
                        {team.avg_sr.toFixed(0)}
                      </TableCell>
                      <TableCell className={`${tableStyles.cell} tabular-nums`}>
                        {team.total_sr}
                      </TableCell>
                      <TableCell className={`${tableStyles.cell} tabular-nums`}>
                        {team.players.length}
                      </TableCell>
                      <TableCell className={tableStyles.cell}>
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            asChild
                            variant="ghost"
                            size="sm"
                            aria-label={`Open team ${team.name}`}
                          >
                            <Link href={`/admin/teams/${team.id}`}>
                              <Pencil className="mr-2 h-4 w-4" aria-hidden />
                              Open team
                            </Link>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow className={tableStyles.row}>
                    <TableCell className={tableStyles.cell} colSpan={5}>
                      <EmptyNote
                        action={
                          <div className="flex flex-wrap gap-2">
                            {syncTeamsButton}
                            {canManageTeams ? (
                              <Button asChild variant="outline" size="sm">
                                <Link href={teamsAdminHref}>
                                  <Plus className="size-3.5" aria-hidden />
                                  Manage teams
                                </Link>
                              </Button>
                            ) : null}
                          </div>
                        }
                      >
                        No teams loaded for this tournament yet. Sync from Challonge or open the
                        dedicated teams workspace to create the first roster.
                      </EmptyNote>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </AdminDetailTableShell>
        </CardContent>
      </Card>

      <Dialog
        open={challongeSyncDialogOpen}
        onOpenChange={(open) => {
          if (open) {
            setChallongeSyncDialogOpen(true);
          } else {
            closeChallongeSyncDialog();
          }
        }}
      >
        <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
          <DialogHeader className="border-b border-border/60 pb-4">
            <DialogTitle>Sync Challonge teams</DialogTitle>
            <DialogDescription>
              Match each Challonge participant to the internal team used by analytics and matches.
            </DialogDescription>
          </DialogHeader>

          {/* Two steps rather than one long table with a Sync button at the
              bottom: the mapping is destructive on the internal teams, and the
              confirm step is where the admin reads back what will be written
              instead of re-scanning the picker column they just filled in. */}
          <WizardShell
            steps={[
              { key: "map", label: "Map participants", state: onConfirmStep ? "done" : "current" },
              { key: "confirm", label: "Confirm", state: onConfirmStep ? "current" : "todo" }
            ]}
            footer={{
              back: onConfirmStep ? () => setChallongeSyncStep("map") : undefined,
              next: onConfirmStep
                ? {
                    label: syncTeamsMutation.isPending ? "Syncing…" : "Sync mappings",
                    onClick: submitChallongeMappings,
                    disabled: !canSubmitChallongeMappings || syncTeamsMutation.isPending
                  }
                : {
                    label: "Continue",
                    onClick: () => setChallongeSyncStep("confirm"),
                    disabled: !canSubmitChallongeMappings
                  },
              secondary: (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={closeChallongeSyncDialog}
                  disabled={syncTeamsMutation.isPending}
                >
                  Cancel
                </Button>
              )
            }}
          >
            {onConfirmStep ? (
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  {selectedChallongeMappings.length} of {challongeParticipants.length} Challonge
                  participants will be written to the internal teams below. Repeating the sync
                  produces the same result.
                </p>
                <ul className="divide-y divide-border/60 rounded-md border border-border/60">
                  {confirmedChallongeRows.map((row) => (
                    <li
                      key={row.key}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
                    >
                      <span className="min-w-0 flex-1 truncate" title={row.participant}>
                        {row.participant}
                      </span>
                      <ArrowRight
                        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1 truncate font-medium" title={row.team}>
                        {row.team}
                      </span>
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                        {row.group}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="secondary" className="tabular-nums">
                      {challongeParticipants.length} participants
                    </Badge>
                    <Badge
                      tone={activeUnmappedParticipants.length ? "danger" : "neutral"}
                      className="tabular-nums"
                    >
                      {activeUnmappedParticipants.length} unmapped
                    </Badge>
                    <Badge variant="secondary" className="tabular-nums">
                      {selectedChallongeMappings.length} selected
                    </Badge>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={applyChallongeSuggestions}
                    disabled={
                      isChallongePreviewLoading ||
                      !challongeParticipants.some(
                        (participant) => participant.suggested_team_id != null
                      )
                    }
                  >
                    <Sparkles className="mr-2 h-4 w-4" aria-hidden />
                    Apply suggestions
                  </Button>
                </div>

                <div className="max-h-[52vh] overflow-auto rounded-md border border-border/60">
                  <Table>
                    <TableHeader>
                      <TableRow className={tableStyles.headerRow}>
                        <TableHead className={tableStyles.head}>Challonge participant</TableHead>
                        <TableHead className={tableStyles.head}>Group</TableHead>
                        <TableHead className={tableStyles.head}>Current</TableHead>
                        <TableHead className={tableStyles.head}>Suggestion</TableHead>
                        <TableHead className={tableStyles.head}>Internal team</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {isChallongePreviewLoading ? (
                        <TableRow className={tableStyles.row}>
                          <TableCell className={tableStyles.cell} colSpan={5}>
                            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                              Loading Challonge participants…
                            </div>
                          </TableCell>
                        </TableRow>
                      ) : challongeParticipants.length ? (
                        challongeParticipants.map((participant) => {
                          const participantKey = getChallongeParticipantKey(participant);
                          const currentTeam =
                            participant.mapped_team_id != null
                              ? challongeTeamsById.get(participant.mapped_team_id)
                              : undefined;
                          const suggestedTeam =
                            participant.suggested_team_id != null
                              ? challongeTeamsById.get(participant.suggested_team_id)
                              : undefined;

                          return (
                            <TableRow key={participantKey} className={tableStyles.row}>
                              <TableCell className={tableStyles.cell}>
                                <div className="min-w-0">
                                  <div className="truncate font-medium" title={participant.name}>
                                    {participant.name}
                                  </div>
                                  <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                                    #{participant.participant_id} · Challonge #
                                    {participant.challonge_id}
                                  </div>
                                </div>
                              </TableCell>
                              <TableCell className={tableStyles.cell}>
                                {participant.group_name ?? "Main"}
                              </TableCell>
                              <TableCell className={tableStyles.cell}>
                                {currentTeam ? (
                                  <span className="truncate" title={currentTeam.name}>
                                    {currentTeam.name}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground">Unmapped</span>
                                )}
                              </TableCell>
                              <TableCell className={tableStyles.cell}>
                                {suggestedTeam ? (
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 max-w-[180px] justify-start px-2"
                                    aria-label={`Map ${participant.name} to ${suggestedTeam.name}`}
                                    onClick={() =>
                                      setChallongeMappingDraft((current) => ({
                                        ...current,
                                        [participantKey]: String(suggestedTeam.id)
                                      }))
                                    }
                                  >
                                    <Sparkles className="mr-2 h-3.5 w-3.5 shrink-0" aria-hidden />
                                    <span className="truncate">{suggestedTeam.name}</span>
                                  </Button>
                                ) : (
                                  <span className="text-muted-foreground">None</span>
                                )}
                              </TableCell>
                              <TableCell className={tableStyles.cell}>
                                <ChallongeTeamPicker
                                  participant={participant}
                                  teams={challongeTeamOptions}
                                  value={getChallongeMappingValue(participant)}
                                  onChange={(next) =>
                                    setChallongeMappingDraft((current) => ({
                                      ...current,
                                      [participantKey]: next
                                    }))
                                  }
                                />
                              </TableCell>
                            </TableRow>
                          );
                        })
                      ) : (
                        <TableRow className={tableStyles.row}>
                          <TableCell className={tableStyles.cell} colSpan={5}>
                            <div className="py-4 text-sm text-muted-foreground">
                              No participants came back from Challonge. Check the Challonge link on
                              the Settings tab, then reopen this dialog.
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </WizardShell>
        </DialogContent>
      </Dialog>
    </>
  );
}
