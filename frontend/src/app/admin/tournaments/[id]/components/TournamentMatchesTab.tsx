"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CheckCircle,
  ChevronsDownUp,
  ChevronsUpDown,
  CircleAlert,
  Clock,
  FileCheck2,
  FileX2,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Upload
} from "lucide-react";
import {
  AdminDetailTableShell,
  getAdminDetailTableStyles
} from "@/components/admin/AdminDetailTable";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { EncounterScoreControls } from "@/components/admin/EncounterScoreControls";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { TeamCombobox } from "@/components/admin/TeamCombobox";
import { buildEncounterName } from "@/components/admin/encounter-name";
import { isGroupStageScoreContext } from "@/components/admin/encounter-score";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { hasUnsavedChanges } from "@/lib/form-change";
import { useToast } from "@/hooks/use-toast";
import adminService from "@/services/admin.service";
import type {
  EncounterCreateInput,
  EncounterUpdateInput,
  StandingUpdateInput
} from "@/types/admin.types";
import type { Encounter } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { Stage, Standings } from "@/types/tournament.types";
import {
  TOURNAMENT_DETAIL_PREVIEW_LIMIT,
  getEmptyEncounterForm,
  getEncounterForm,
  getEncounterScopeKey,
  getEncounterStageLabel,
  getStageScopeGroups,
  getStandingForm,
  getStandingGroups,
  getStandingScopeKey,
  getStandingScopeLabel,
  sortStandings,
  type EncounterFormState,
  type StandingFormState,
  type StandingSortKey,
  type StandingSortState
} from "./tournamentWorkspace.helpers";
import { TournamentLogUploadDialog } from "./TournamentLogUploadDialog";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";

const ENCOUNTERS_SCOPE_QUERY_PARAM = "encountersScope";
const STANDINGS_SCOPE_QUERY_PARAM = "standingsScope";

interface TournamentMatchesTabProps {
  tournamentId: number;
  teams: Team[];
  stages: Stage[];
  encounters: Encounter[];
  standings: Standings[];
  hasChallongeSource: boolean;
  canCreateEncounter: boolean;
  canUpdateEncounter: boolean;
  canDeleteEncounter: boolean;
  canSyncEncounters: boolean;
  canUpdateStanding: boolean;
  canDeleteStanding: boolean;
  canRecalculateStandings: boolean;
}

function SortIcon({ state, active }: { state: StandingSortState; active: boolean }) {
  if (!active || !state) return <ArrowUpDown className="ml-1 inline size-3.5" />;
  return state.dir === "asc" ? (
    <ArrowUp className="ml-1 inline size-3.5" />
  ) : (
    <ArrowDown className="ml-1 inline size-3.5" />
  );
}

function setScopeParam(params: URLSearchParams, key: string, value: string) {
  if (value === "all") {
    params.delete(key);
    return;
  }

  params.set(key, value);
}

export function TournamentMatchesTab({
  tournamentId,
  teams,
  stages,
  encounters,
  standings,
  hasChallongeSource,
  canCreateEncounter,
  canUpdateEncounter,
  canDeleteEncounter,
  canSyncEncounters,
  canUpdateStanding,
  canDeleteStanding,
  canRecalculateStandings
}: TournamentMatchesTabProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const tableStyles = getAdminDetailTableStyles("compact");

  const defaultStage = stages[0] ?? null;
  const defaultStageId = defaultStage?.id ?? null;
  const defaultStageItemId = defaultStage?.items[0]?.id ?? null;
  const canCreateEncounterNow = canCreateEncounter && teams.length >= 2 && stages.length > 0;
  const canManageStandingsNow = canRecalculateStandings && encounters.length > 0;

  const [encounterDialogOpen, setEncounterDialogOpen] = useState(false);
  const [editingEncounter, setEditingEncounter] = useState<Encounter | null>(null);
  const [encounterFormData, setEncounterFormData] = useState<EncounterFormState>(
    getEmptyEncounterForm(defaultStageId, defaultStageItemId)
  );
  const [encounterFormError, setEncounterFormError] = useState<string | undefined>();
  const [encounterPendingDelete, setEncounterPendingDelete] = useState<Encounter | null>(null);

  const [editingStanding, setEditingStanding] = useState<Standings | null>(null);
  const [standingDialogOpen, setStandingDialogOpen] = useState(false);
  const [standingFormData, setStandingFormData] = useState<StandingFormState>({
    position: 0,
    points: 0,
    win: 0,
    draw: 0,
    lose: 0
  });
  const [standingPendingDelete, setStandingPendingDelete] = useState<Standings | null>(null);
  const [standingsExpanded, setStandingsExpanded] = useState(false);
  const [standingsSort, setStandingsSort] = useState<StandingSortState>(null);

  const replaceSearchParams = useCallback(
    (params: URLSearchParams) => {
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router]
  );

  const updateScopeFilter = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      setScopeParam(params, key, value);
      replaceSearchParams(params);
    },
    [replaceSearchParams, searchParams]
  );

  const resetEncounterDialog = () => {
    setEncounterDialogOpen(false);
    setEditingEncounter(null);
    setEncounterFormData(getEmptyEncounterForm(defaultStageId, defaultStageItemId));
    setEncounterFormError(undefined);
    saveEncounterMutation.reset();
  };

  const resetStandingDialog = () => {
    setStandingDialogOpen(false);
    setEditingStanding(null);
    setStandingFormData({ position: 0, points: 0, win: 0, draw: 0, lose: 0 });
    updateStandingMutation.reset();
  };

  const saveEncounterMutation = useMutation({
    mutationFn: async ({
      mode,
      encounterId,
      data
    }: {
      mode: "create" | "update";
      encounterId?: number;
      data: EncounterCreateInput | EncounterUpdateInput;
    }) => {
      if (mode === "create") {
        return adminService.createEncounter(data as EncounterCreateInput);
      }

      return adminService.updateEncounter(encounterId!, data as EncounterUpdateInput);
    },
    onSuccess: (_data, variables) => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      resetEncounterDialog();
      toast({
        title: variables.mode === "create" ? "Encounter created" : "Encounter updated"
      });
    },
    onError: (error: Error) => {
      setEncounterFormError(error.message);
    }
  });

  const deleteEncounterMutation = useMutation({
    mutationFn: (encounterId: number) => adminService.deleteEncounter(encounterId),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      setEncounterPendingDelete(null);
      toast({ title: "Encounter deleted" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    }
  });

  const syncEncountersMutation = useMutation({
    mutationFn: () => adminService.syncEncountersFromChallonge(tournamentId),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      toast({ title: "Encounters synced from Challonge" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    }
  });

  const updateStandingMutation = useMutation({
    mutationFn: ({ standingId, data }: { standingId: number; data: StandingUpdateInput }) =>
      adminService.updateStanding(standingId, data),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      resetStandingDialog();
      toast({ title: "Standing updated" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    }
  });

  const deleteStandingMutation = useMutation({
    mutationFn: (standingId: number) => adminService.deleteStanding(standingId),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      setStandingPendingDelete(null);
      toast({ title: "Standing deleted" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    }
  });

  const calculateStandingsMutation = useMutation({
    mutationFn: () => adminService.calculateStandings(tournamentId),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      toast({ title: "Standings calculated" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    }
  });

  const recalculateStandingsMutation = useMutation({
    mutationFn: async () => {
      await adminService.recalculateStandings(tournamentId);
      return adminService.calculateStandings(tournamentId);
    },
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      toast({ title: "Standings recalculated" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    }
  });

  const openCreateEncounterDialog = () => {
    setEncounterFormError(undefined);
    setEditingEncounter(null);
    setEncounterFormData(getEmptyEncounterForm(defaultStageId, defaultStageItemId));
    setEncounterDialogOpen(true);
  };

  const openEditEncounterDialog = (encounter: Encounter) => {
    setEncounterFormError(undefined);
    setEditingEncounter(encounter);
    setEncounterFormData(getEncounterForm(encounter));
    setEncounterDialogOpen(true);
  };

  const openEditStandingDialog = (standing: Standings) => {
    updateStandingMutation.reset();
    setEditingStanding(standing);
    setStandingFormData(getStandingForm(standing));
    setStandingDialogOpen(true);
  };

  const handleEncounterSubmit = (event: FormEvent) => {
    event.preventDefault();

    if (!encounterFormData.name.trim()) {
      setEncounterFormError("Encounter name is required.");
      return;
    }

    if (encounterFormData.stage_id == null) {
      setEncounterFormError("Select a stage before saving the encounter.");
      return;
    }

    if (
      encounterFormData.home_team_id != null &&
      encounterFormData.away_team_id != null &&
      encounterFormData.home_team_id === encounterFormData.away_team_id
    ) {
      setEncounterFormError("Home and away teams must be different.");
      return;
    }

    const payload = editingEncounter
      ? ({
          name: encounterFormData.name.trim(),
          stage_id: encounterFormData.stage_id,
          stage_item_id: encounterFormData.stage_item_id,
          home_team_id: encounterFormData.home_team_id,
          away_team_id: encounterFormData.away_team_id,
          round: encounterFormData.round,
          home_score: encounterFormData.home_score,
          away_score: encounterFormData.away_score,
          status: encounterFormData.status
        } satisfies EncounterUpdateInput)
      : ({
          name: encounterFormData.name.trim(),
          tournament_id: tournamentId,
          stage_id: encounterFormData.stage_id,
          stage_item_id: encounterFormData.stage_item_id,
          home_team_id: encounterFormData.home_team_id,
          away_team_id: encounterFormData.away_team_id,
          round: encounterFormData.round,
          home_score: encounterFormData.home_score,
          away_score: encounterFormData.away_score,
          status: encounterFormData.status
        } satisfies EncounterCreateInput);

    saveEncounterMutation.mutate(
      editingEncounter
        ? { mode: "update", encounterId: editingEncounter.id, data: payload }
        : { mode: "create", data: payload }
    );
  };

  const handleStandingSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!editingStanding) return;

    const payload: StandingUpdateInput = {
      position: standingFormData.position,
      points: standingFormData.points,
      win: standingFormData.win,
      draw: standingFormData.draw,
      lose: standingFormData.lose
    };

    updateStandingMutation.mutate({ standingId: editingStanding.id, data: payload });
  };

  const encounterFormInitial = editingEncounter
    ? getEncounterForm(editingEncounter)
    : getEmptyEncounterForm(defaultStageId, defaultStageItemId);
  const standingFormInitial = editingStanding
    ? getStandingForm(editingStanding)
    : { position: 0, points: 0, win: 0, draw: 0, lose: 0 };

  const isEncounterDirty =
    encounterDialogOpen && hasUnsavedChanges(encounterFormData, encounterFormInitial);
  const isStandingDirty =
    standingDialogOpen && hasUnsavedChanges(standingFormData, standingFormInitial);
  const selectedEncounterStage =
    stages.find((stage) => stage.id === encounterFormData.stage_id) ?? null;
  const selectedEncounterStageItem =
    selectedEncounterStage?.items.find((item) => item.id === encounterFormData.stage_item_id) ??
    null;
  const isEncounterGroupStage = isGroupStageScoreContext(
    selectedEncounterStage,
    selectedEncounterStageItem
  );

  const encounterGroups = useMemo(() => getStageScopeGroups(stages), [stages]);
  const standingGroups = useMemo(() => getStandingGroups(standings), [standings]);
  const rawEncounterScopeFilter = searchParams.get(ENCOUNTERS_SCOPE_QUERY_PARAM) ?? "all";
  const rawStandingsScopeFilter = searchParams.get(STANDINGS_SCOPE_QUERY_PARAM) ?? "all";
  const encounterScopeFilter =
    rawEncounterScopeFilter === "all" ||
    encounterGroups.some((group) => group.id === rawEncounterScopeFilter)
      ? rawEncounterScopeFilter
      : "all";
  const standingsGroupFilter =
    rawStandingsScopeFilter === "all" ||
    standingGroups.some((group) => group.id === rawStandingsScopeFilter)
      ? rawStandingsScopeFilter
      : "all";
  const filteredEncounters =
    encounterScopeFilter === "all"
      ? encounters
      : encounters.filter((encounter) => getEncounterScopeKey(encounter) === encounterScopeFilter);
  const visibleEncounters = filteredEncounters.slice(0, TOURNAMENT_DETAIL_PREVIEW_LIMIT);
  const completedFilteredEncounterCount = filteredEncounters.filter(
    (encounter) => encounter.status?.toUpperCase() === "COMPLETED"
  ).length;
  const filteredStandings =
    standingsGroupFilter === "all"
      ? standings
      : standings.filter((standing) => getStandingScopeKey(standing) === standingsGroupFilter);
  const sortedStandings = sortStandings(filteredStandings, standingsSort);
  const visibleStandings = standingsExpanded
    ? sortedStandings
    : sortedStandings.slice(0, TOURNAMENT_DETAIL_PREVIEW_LIMIT);
  const hasMoreStandings = sortedStandings.length > TOURNAMENT_DETAIL_PREVIEW_LIMIT;
  const completedEncounterCount = encounters.filter(
    (encounter) => encounter.status?.toUpperCase() === "COMPLETED"
  ).length;
  const missingLogCount = encounters.filter((encounter) => !encounter.has_logs).length;
  const standingsLeader = sortedStandings[0]?.team?.name ?? "No leader yet";

  useEffect(() => {
    if (
      rawEncounterScopeFilter === encounterScopeFilter &&
      rawStandingsScopeFilter === standingsGroupFilter
    ) {
      return;
    }

    const params = new URLSearchParams(searchParams.toString());
    setScopeParam(params, ENCOUNTERS_SCOPE_QUERY_PARAM, encounterScopeFilter);
    setScopeParam(params, STANDINGS_SCOPE_QUERY_PARAM, standingsGroupFilter);
    replaceSearchParams(params);
  }, [
    encounterScopeFilter,
    rawEncounterScopeFilter,
    rawStandingsScopeFilter,
    replaceSearchParams,
    searchParams,
    standingsGroupFilter
  ]);

  const toggleStandingSort = (key: StandingSortKey) => {
    setStandingsSort((current) => {
      if (!current || current.key !== key) {
        return { key, dir: "asc" };
      }

      return {
        key,
        dir: current.dir === "asc" ? "desc" : "asc"
      };
    });
  };

  return (
    <>
      <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Card className="border-border/40">
          <CardContent className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Encounters
            </p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">{encounters.length}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {completedEncounterCount} completed
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Log Coverage
            </p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">
              {encounters.length - missingLogCount}/{encounters.length || 0}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {missingLogCount} missing log{missingLogCount === 1 ? "" : "s"}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Standings
            </p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">{standings.length}</p>
            <p className="mt-1 truncate text-xs text-muted-foreground" title={standingsLeader}>
              Leader: {standingsLeader}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Sync Source
            </p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">
              {hasChallongeSource ? "Linked" : "Manual"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {hasChallongeSource ? "External match sync enabled" : "Use manual match control"}
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Card className="border-border/40">
          <CardHeader className="gap-3 pb-3">
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="text-base font-semibold">Match Control</CardTitle>
                <Badge variant="outline">{filteredEncounters.length} filtered</Badge>
                <Badge variant={completedFilteredEncounterCount ? "secondary" : "outline"}>
                  {completedFilteredEncounterCount} completed
                </Badge>
              </div>
              <CardDescription>
                Create, sync, score, and attach logs to tournament encounters.
              </CardDescription>
              <div className="hidden">
                <span>{filteredEncounters.length} encounters</span>
                <span>·</span>
                <span>{completedFilteredEncounterCount} completed</span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {canSyncEncounters ? (
                <Button
                  variant="outline"
                  onClick={() => syncEncountersMutation.mutate()}
                  disabled={syncEncountersMutation.isPending || !hasChallongeSource}
                >
                  <RefreshCw className="size-4" />
                  Sync Encounters
                </Button>
              ) : null}
              {canCreateEncounter ? (
                <Button onClick={openCreateEncounterDialog} disabled={!canCreateEncounterNow}>
                  <Plus className="size-4" />
                  Create Encounter
                </Button>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {encounterGroups.length > 1 ? (
              <div className="flex items-center gap-2">
                <Label htmlFor="encounters-scope-filter" className="text-xs text-muted-foreground">
                  Scope
                </Label>
                <Select
                  value={encounterScopeFilter}
                  onValueChange={(value) => updateScopeFilter(ENCOUNTERS_SCOPE_QUERY_PARAM, value)}
                >
                  <SelectTrigger id="encounters-scope-filter" className="h-8 w-[220px]">
                    <SelectValue placeholder="All stages" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All stages</SelectItem>
                    {encounterGroups.map((group) => (
                      <SelectItem key={group.id} value={group.id}>
                        {group.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}

            <AdminDetailTableShell variant="compact">
              <Table>
                <TableHeader>
                  <TableRow className={tableStyles.headerRow}>
                    <TableHead className={tableStyles.head}>Encounter</TableHead>
                    <TableHead className={tableStyles.head}>Stage</TableHead>
                    <TableHead className={tableStyles.head}>Round</TableHead>
                    <TableHead className={tableStyles.head}>Score</TableHead>
                    <TableHead className={tableStyles.head}>Status</TableHead>
                    <TableHead className={tableStyles.head}>Logs</TableHead>
                    <TableHead className={`${tableStyles.head} text-right`}>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleEncounters.length ? (
                    visibleEncounters.map((encounter) => (
                      <TableRow key={encounter.id} className={tableStyles.row}>
                        <TableCell className={tableStyles.cell}>
                          <div className="space-y-1">
                            <span className="font-medium">{encounter.name}</span>
                            <p className="text-sm text-muted-foreground">
                              {encounter.home_team?.name ?? "TBD"} vs{" "}
                              {encounter.away_team?.name ?? "TBD"}
                            </p>
                          </div>
                        </TableCell>
                        <TableCell className={tableStyles.cell}>
                          {getEncounterStageLabel(encounter)}
                        </TableCell>
                        <TableCell className={tableStyles.cell}>{encounter.round}</TableCell>
                        <TableCell className={tableStyles.cell}>
                          {encounter.score.home} - {encounter.score.away}
                        </TableCell>
                        <TableCell className={tableStyles.cell}>
                          {(() => {
                            const status = encounter.status?.toUpperCase() ?? "";
                            if (status === "COMPLETED") {
                              return (
                                <StatusIcon
                                  icon={CheckCircle}
                                  label="Completed"
                                  variant="success"
                                />
                              );
                            }
                            if (status === "PENDING") {
                              return <StatusIcon icon={Clock} label="Pending" variant="warning" />;
                            }

                            return (
                              <StatusIcon
                                icon={CircleAlert}
                                label={
                                  status
                                    ? `${status[0]}${status.slice(1).toLowerCase()}`
                                    : "Unknown"
                                }
                                variant="muted"
                              />
                            );
                          })()}
                        </TableCell>
                        <TableCell className={tableStyles.cell}>
                          {encounter.has_logs ? (
                            <StatusIcon icon={FileCheck2} label="Available" variant="success" />
                          ) : (
                            <StatusIcon icon={FileX2} label="Missing" variant="muted" />
                          )}
                        </TableCell>
                        <TableCell className={tableStyles.cell}>
                          <div className="flex items-center justify-end gap-2">
                            {canUpdateEncounter ? (
                              <TournamentLogUploadDialog
                                tournamentId={tournamentId}
                                encounters={encounters}
                                initialEncounterId={encounter.id}
                                onUploaded={() =>
                                  invalidateTournamentWorkspace(queryClient, tournamentId)
                                }
                                trigger={
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    aria-label={`Upload logs for ${encounter.name}`}
                                  >
                                    <Upload className="h-4 w-4" />
                                  </Button>
                                }
                              />
                            ) : null}
                            {canUpdateEncounter ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Edit ${encounter.name}`}
                                onClick={() => openEditEncounterDialog(encounter)}
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                            ) : null}
                            {canDeleteEncounter ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="text-destructive"
                                aria-label={`Delete ${encounter.name}`}
                                onClick={() => setEncounterPendingDelete(encounter)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow className={tableStyles.row}>
                      <TableCell className={tableStyles.cell} colSpan={7}>
                        <div className="flex flex-col gap-3 rounded-xl border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
                          <span>
                            No encounters available yet. Add at least two teams before creating the
                            first encounter.
                          </span>
                          <div className="flex flex-wrap gap-2">
                            {canSyncEncounters ? (
                              <Button
                                variant="outline"
                                onClick={() => syncEncountersMutation.mutate()}
                                disabled={syncEncountersMutation.isPending || !hasChallongeSource}
                              >
                                <RefreshCw className="mr-2 h-4 w-4" />
                                Sync Encounters
                              </Button>
                            ) : null}
                            {canCreateEncounter ? (
                              <Button
                                variant="outline"
                                onClick={openCreateEncounterDialog}
                                disabled={!canCreateEncounterNow}
                              >
                                <Plus className="mr-2 h-4 w-4" />
                                Create First Encounter
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </AdminDetailTableShell>
            {filteredEncounters.length > TOURNAMENT_DETAIL_PREVIEW_LIMIT ? (
              <div className="border-t border-border/30 px-3 py-2">
                <Link
                  href={`/admin/encounters?tournament=${tournamentId}`}
                  className="text-[12px] text-muted-foreground/60 transition-colors hover:text-foreground"
                >
                  Show all {filteredEncounters.length} encounters →
                </Link>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="border-border/40">
          <CardHeader className="gap-3 pb-3">
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="text-base font-semibold">Standings Control</CardTitle>
                <Badge variant="outline">{standings.length} rows</Badge>
              </div>
              <CardDescription>
                Calculate, sort, and adjust the ranking table for the selected scope.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              {hasMoreStandings ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1.5 text-xs text-muted-foreground"
                  onClick={() => setStandingsExpanded((current) => !current)}
                >
                  {standingsExpanded ? (
                    <ChevronsDownUp className="size-3.5" />
                  ) : (
                    <ChevronsUpDown className="size-3.5" />
                  )}
                  {standingsExpanded ? "Collapse" : "Expand all"}
                </Button>
              ) : null}
              {canRecalculateStandings && standings.length === 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => calculateStandingsMutation.mutate()}
                  disabled={calculateStandingsMutation.isPending || !canManageStandingsNow}
                >
                  <RefreshCw className="size-3.5" /> Calculate
                </Button>
              ) : null}
              {canRecalculateStandings && standings.length > 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => recalculateStandingsMutation.mutate()}
                  disabled={recalculateStandingsMutation.isPending || !canManageStandingsNow}
                >
                  <RefreshCw className="size-3.5" /> Recalculate
                </Button>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {standingGroups.length > 1 ? (
              <div className="flex items-center gap-2">
                <Label htmlFor="standings-scope-filter" className="text-xs text-muted-foreground">
                  Scope
                </Label>
                <Select
                  value={standingsGroupFilter}
                  onValueChange={(value) => updateScopeFilter(STANDINGS_SCOPE_QUERY_PARAM, value)}
                >
                  <SelectTrigger id="standings-scope-filter" className="h-8 w-[220px]">
                    <SelectValue placeholder="All stages" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All stages</SelectItem>
                    {standingGroups.map((group) => (
                      <SelectItem key={group.id} value={group.id}>
                        {group.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}

            <AdminDetailTableShell variant="compact">
              <Table>
                <TableHeader>
                  <TableRow className={tableStyles.headerRow}>
                    {(
                      [
                        { key: "position", label: "Pos" },
                        { key: "team", label: "Team" },
                        { key: "scope", label: "Scope" },
                        { key: "points", label: "Points" },
                        { key: "win", label: "W" },
                        { key: "draw", label: "D" },
                        { key: "lose", label: "L" }
                      ] as Array<{ key: StandingSortKey; label: string }>
                    ).map((column) => (
                      <TableHead
                        key={column.key}
                        className={`${tableStyles.head} cursor-pointer select-none`}
                        onClick={() => toggleStandingSort(column.key)}
                      >
                        {column.label}
                        <SortIcon
                          state={standingsSort}
                          active={standingsSort?.key === column.key}
                        />
                      </TableHead>
                    ))}
                    <TableHead className={`${tableStyles.head} text-right`}>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleStandings.length ? (
                    visibleStandings.map((standing) => (
                      <TableRow key={standing.id} className={tableStyles.row}>
                        <TableCell className={tableStyles.cell}>{standing.position}</TableCell>
                        <TableCell className={`${tableStyles.cell} font-medium`}>
                          {standing.team?.name ?? "Unknown team"}
                        </TableCell>
                        <TableCell className={tableStyles.cell}>
                          {getStandingScopeLabel(standing)}
                        </TableCell>
                        <TableCell className={tableStyles.cell}>{standing.points}</TableCell>
                        <TableCell className={tableStyles.cell}>{standing.win}</TableCell>
                        <TableCell className={tableStyles.cell}>{standing.draw}</TableCell>
                        <TableCell className={tableStyles.cell}>{standing.lose}</TableCell>
                        <TableCell className={tableStyles.cell}>
                          <div className="flex items-center justify-end gap-2">
                            {canUpdateStanding ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Edit standing for ${standing.team?.name ?? "team"}`}
                                onClick={() => openEditStandingDialog(standing)}
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                            ) : null}
                            {canDeleteStanding ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="text-destructive"
                                aria-label={`Delete standing for ${standing.team?.name ?? "team"}`}
                                onClick={() => setStandingPendingDelete(standing)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow className={tableStyles.row}>
                      <TableCell className={tableStyles.cell} colSpan={8}>
                        <div className="flex flex-col gap-3 rounded-xl border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
                          <span>
                            No standings available yet. Complete encounters first, then calculate
                            standings.
                          </span>
                          {canRecalculateStandings ? (
                            <Button
                              variant="outline"
                              onClick={() => calculateStandingsMutation.mutate()}
                              disabled={
                                calculateStandingsMutation.isPending || !canManageStandingsNow
                              }
                            >
                              <RefreshCw className="mr-2 h-4 w-4" />
                              Calculate Standings
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </AdminDetailTableShell>
          </CardContent>
        </Card>
      </div>

      <EntityFormDialog
        open={encounterDialogOpen}
        onOpenChange={(open) => {
          setEncounterDialogOpen(open);
          if (!open) {
            resetEncounterDialog();
          }
        }}
        title={editingEncounter ? "Edit Encounter" : "Create Encounter"}
        description="Create or update tournament encounters without leaving the workspace."
        onSubmit={handleEncounterSubmit}
        isSubmitting={saveEncounterMutation.isPending}
        submittingLabel={editingEncounter ? "Updating encounter..." : "Creating encounter..."}
        errorMessage={encounterFormError}
        isDirty={isEncounterDirty}
      >
        <div className="space-y-4">
          <div>
            <Label htmlFor="workspace-encounter-name">Encounter Name</Label>
            <Input
              id="workspace-encounter-name"
              value={encounterFormData.name}
              onChange={(event) =>
                setEncounterFormData((current) => ({ ...current, name: event.target.value }))
              }
            />
          </div>

          <div>
            <Label htmlFor="workspace-encounter-stage">Stage</Label>
            <Select
              value={encounterFormData.stage_id?.toString() ?? ""}
              onValueChange={(value) => {
                const stage = stages.find((entry) => entry.id === Number(value)) ?? null;
                setEncounterFormData((current) => ({
                  ...current,
                  stage_id: stage?.id ?? null,
                  stage_item_id: stage?.items[0]?.id ?? null
                }));
              }}
            >
              <SelectTrigger id="workspace-encounter-stage">
                <SelectValue placeholder="Select stage" />
              </SelectTrigger>
              <SelectContent>
                {stages.map((stage) => (
                  <SelectItem key={stage.id} value={stage.id.toString()}>
                    {stage.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label htmlFor="workspace-encounter-stage-item">Stage Item</Label>
            <Select
              value={encounterFormData.stage_item_id?.toString() ?? "none"}
              onValueChange={(value) =>
                setEncounterFormData((current) => {
                  const nextStageItemId = value === "none" ? null : Number(value);
                  const nextStageId =
                    nextStageItemId != null
                      ? (stages.find((stage) =>
                          stage.items.some((item) => item.id === nextStageItemId)
                        )?.id ?? current.stage_id)
                      : current.stage_id;

                  return {
                    ...current,
                    stage_id: nextStageId,
                    stage_item_id: nextStageItemId
                  };
                })
              }
            >
              <SelectTrigger id="workspace-encounter-stage-item">
                <SelectValue placeholder="Select stage item" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No stage item</SelectItem>
                {stages
                  .filter((stage) => stage.id === encounterFormData.stage_id)
                  .flatMap((stage) => stage.items)
                  .map((item) => (
                    <SelectItem key={item.id} value={item.id.toString()}>
                      {item.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <Label htmlFor="workspace-encounter-home">Home Team</Label>
              <TeamCombobox
                id="workspace-encounter-home"
                teams={teams}
                value={encounterFormData.home_team_id}
                placeholder="Select home team"
                onSelect={(team) =>
                  setEncounterFormData((current) => {
                    const homeTeamId = team?.id ?? null;
                    return {
                      ...current,
                      name: buildEncounterName(teams, homeTeamId, current.away_team_id),
                      home_team_id: homeTeamId
                    };
                  })
                }
              />
            </div>

            <div>
              <Label htmlFor="workspace-encounter-away">Away Team</Label>
              <TeamCombobox
                id="workspace-encounter-away"
                teams={teams}
                value={encounterFormData.away_team_id}
                placeholder="Select away team"
                onSelect={(team) =>
                  setEncounterFormData((current) => {
                    const awayTeamId = team?.id ?? null;
                    return {
                      ...current,
                      name: buildEncounterName(teams, current.home_team_id, awayTeamId),
                      away_team_id: awayTeamId
                    };
                  })
                }
              />
            </div>
          </div>

          <div>
            <Label htmlFor="workspace-encounter-round">Round</Label>
            <Input
              id="workspace-encounter-round"
              type="number"
              value={encounterFormData.round}
              onChange={(event) =>
                setEncounterFormData((current) => ({
                  ...current,
                  round: event.target.value ? Number(event.target.value) : 1
                }))
              }
            />
          </div>

          <EncounterScoreControls
            idPrefix="workspace-encounter"
            homeScore={encounterFormData.home_score}
            awayScore={encounterFormData.away_score}
            presetLabel={isEncounterGroupStage ? "Group stage presets" : "Result presets"}
            showGroupStageHint={isEncounterGroupStage}
            onScoreChange={(score) =>
              setEncounterFormData((current) => ({
                ...current,
                home_score: score.homeScore,
                away_score: score.awayScore
              }))
            }
            onPresetSelect={(score) =>
              setEncounterFormData((current) => ({
                ...current,
                home_score: score.homeScore,
                away_score: score.awayScore,
                status: "completed"
              }))
            }
          />

          <div>
            <Label htmlFor="workspace-encounter-status">Status</Label>
            <Select
              value={encounterFormData.status}
              onValueChange={(value) =>
                setEncounterFormData((current) => ({ ...current, status: value }))
              }
            >
              <SelectTrigger id="workspace-encounter-status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="open">Open</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </EntityFormDialog>

      <EntityFormDialog
        open={standingDialogOpen}
        onOpenChange={(open) => {
          setStandingDialogOpen(open);
          if (!open) {
            resetStandingDialog();
          }
        }}
        title="Edit Standing"
        description="Adjust a stored standings row manually."
        onSubmit={handleStandingSubmit}
        isSubmitting={updateStandingMutation.isPending}
        submittingLabel="Updating standing..."
        errorMessage={
          updateStandingMutation.isError ? updateStandingMutation.error.message : undefined
        }
        isDirty={isStandingDirty}
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <Label htmlFor="workspace-standing-position">Position</Label>
            <Input
              id="workspace-standing-position"
              type="number"
              min="1"
              value={standingFormData.position}
              onChange={(event) =>
                setStandingFormData((current) => ({
                  ...current,
                  position: event.target.value ? Number(event.target.value) : 0
                }))
              }
            />
          </div>
          <div>
            <Label htmlFor="workspace-standing-points">Points</Label>
            <Input
              id="workspace-standing-points"
              type="number"
              step="0.1"
              value={standingFormData.points}
              onChange={(event) =>
                setStandingFormData((current) => ({
                  ...current,
                  points: event.target.value ? Number(event.target.value) : 0
                }))
              }
            />
          </div>
          <div>
            <Label htmlFor="workspace-standing-win">Wins</Label>
            <Input
              id="workspace-standing-win"
              type="number"
              min="0"
              value={standingFormData.win}
              onChange={(event) =>
                setStandingFormData((current) => ({
                  ...current,
                  win: event.target.value ? Number(event.target.value) : 0
                }))
              }
            />
          </div>
          <div>
            <Label htmlFor="workspace-standing-draw">Draws</Label>
            <Input
              id="workspace-standing-draw"
              type="number"
              min="0"
              value={standingFormData.draw}
              onChange={(event) =>
                setStandingFormData((current) => ({
                  ...current,
                  draw: event.target.value ? Number(event.target.value) : 0
                }))
              }
            />
          </div>
          <div>
            <Label htmlFor="workspace-standing-lose">Losses</Label>
            <Input
              id="workspace-standing-lose"
              type="number"
              min="0"
              value={standingFormData.lose}
              onChange={(event) =>
                setStandingFormData((current) => ({
                  ...current,
                  lose: event.target.value ? Number(event.target.value) : 0
                }))
              }
            />
          </div>
        </div>
      </EntityFormDialog>

      <DeleteConfirmDialog
        open={!!encounterPendingDelete}
        onOpenChange={(open) => {
          if (!open) {
            setEncounterPendingDelete(null);
          }
        }}
        onConfirm={() => {
          if (encounterPendingDelete) {
            deleteEncounterMutation.mutate(encounterPendingDelete.id);
          }
        }}
        title="Delete Encounter"
        description={`Delete "${encounterPendingDelete?.name ?? "this encounter"}"? This action cannot be undone.`}
        cascadeInfo={["All matches in this encounter", "Attached match statistics and logs"]}
        isDeleting={deleteEncounterMutation.isPending}
      />

      <DeleteConfirmDialog
        open={!!standingPendingDelete}
        onOpenChange={(open) => {
          if (!open) {
            setStandingPendingDelete(null);
          }
        }}
        onConfirm={() => {
          if (standingPendingDelete) {
            deleteStandingMutation.mutate(standingPendingDelete.id);
          }
        }}
        title="Delete Standing"
        description={`Delete the standings row for "${standingPendingDelete?.team?.name ?? "this team"}"?`}
        isDeleting={deleteStandingMutation.isPending}
      />
    </>
  );
}
