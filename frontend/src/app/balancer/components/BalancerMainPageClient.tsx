"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Shuffle, Users } from "lucide-react";
import { cn } from "@/lib/utils";

import {
  BalancingPoolSidebar,
  type BalancingPoolSidebarHandle
} from "@/app/balancer/components/BalancingPoolSidebar";
import { PlayerEditModal } from "@/app/balancer/components/PlayerEditSheet";
import { BalancerConfigDrawer } from "@/app/balancer/components/BalancerConfigDrawer";
import { PresetRunPanel } from "@/app/balancer/components/PresetRunPanel";
import { TeamDistributionPanel } from "@/app/balancer/components/TeamDistributionPanel";
import { VariantSelector } from "@/app/balancer/components/VariantSelector";
import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { useBalancerJob } from "@/app/balancer/components/useBalancerJob";
import { useBalancerMutations } from "@/app/balancer/components/useBalancerMutations";
import {
  balancerRealtimeTopic,
  useBalancerRealtime,
} from "@/app/balancer/components/useBalancerRealtime";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { mergeStatusOptions } from "@/lib/balancer-statuses";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import balancerService from "@/services/balancer.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { BalancerRoleCode } from "@/types/balancer-admin.types";
import type { BalancerConfig } from "@/types/balancer.types";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { BalancerActionsPanel } from "./BalancerActionsPanel";
import { BalancerEditorPanel } from "./BalancerEditorPanel";
import { BalancerPresenceStack } from "./BalancerPresenceStack";
import { BalanceImageExportDialog } from "./BalanceImageExportDialog";
import {
  BalancerOperationDialog,
  createOperationSteps,
  updateOperationStepStatus,
  type BalancerOperationStep,
  type BalancerOperationStepDefinition,
  type BalancerOperationStepStatus
} from "./BalancerOperationDialog";
import {
  CUSTOM_PRESET,
  areBalancerConfigsEqual,
  findMatchingPreset,
  resolveInitialBalancerConfig,
  sanitizeBalancerConfig
} from "./balancer-config-helpers";
import {
  getCanRunBalance,
  getDefaultCollapsedTeamIds,
  getPresetOptions,
  replaceVariantPayload,
  toggleCollapsedTeamId,
  upsertSavedVariant,
  buildBalancerPageCollections
} from "./balancer-page-selectors";
import { PRESET_LABELS } from "./balancer-page-helpers";
import {
  buildTeamNamesText,
  buildVariantFromSavedBalance,
  downloadPlayersExport,
  getPlayerValidationIssues,
  type BalanceVariant
} from "./workspace-helpers";

const EXPORT_TO_TOURNAMENT_STEPS: BalancerOperationStepDefinition[] = [
  {
    id: "validate",
    label: "Validate selected balance",
    description: "Check that the selected result can be exported."
  },
  {
    id: "save",
    label: "Save selected balance",
    description: "Persist the current teams before exporting them."
  },
  {
    id: "export",
    label: "Create tournament teams",
    description: "Replace previously exported teams and create tournament rosters."
  },
  {
    id: "refresh",
    label: "Refresh tournament data",
    description: "Update cached balance, team, standings, and public tournament views."
  }
];

const IMPORT_JSON_STEPS: BalancerOperationStepDefinition[] = [
  {
    id: "read",
    label: "Read JSON file",
    description: "Validate that the selected file contains JSON."
  },
  {
    id: "import",
    label: "Import teams",
    description: "Create tournament teams from the JSON payload."
  },
  {
    id: "refresh",
    label: "Refresh tournament data",
    description: "Update cached tournament teams and public views."
  }
];

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function BalancerMainPageClient() {
  const tournamentId = useBalancerTournamentId();
  const divisionGrid = useDivisionGrid();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  const queryClient = useQueryClient();
  const sidebarRef = useRef<BalancingPoolSidebarHandle>(null);
  const balanceEditorRef = useRef<HTMLDivElement | null>(null);
  const variantsRef = useRef<BalanceVariant[]>([]);

  const [selectedPreset, setSelectedPreset] = useState("DEFAULT");
  const [jobState, dispatchJob] = useBalancerJob();
  const [variants, setVariants] = useState<BalanceVariant[]>([]);
  const [activeVariantId, setActiveVariantId] = useState<string | null>(null);
  const [presenceUserIds, setPresenceUserIds] = useState<number[]>([]);
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [editingPlayerId, setEditingPlayerId] = useState<number | null>(null);
  const [pendingRankHistory, setPendingRankHistory] = useState<Partial<
    Record<BalancerRoleCode, number>
  > | null>(null);
  const [excludeInvalidPlayers, setExcludeInvalidPlayers] = useState(false);
  const [collapsedTeamIds, setCollapsedTeamIds] = useState<number[]>([]);
  const [isPoolSidebarCollapsed, setIsPoolSidebarCollapsed] = useState(false);
  const [isConfigDrawerOpen, setIsConfigDrawerOpen] = useState(false);
  const [isImageExportOpen, setIsImageExportOpen] = useState(false);
  const [isTournamentExportOpen, setIsTournamentExportOpen] = useState(false);
  const [tournamentExportSteps, setTournamentExportSteps] = useState<BalancerOperationStep[]>(() =>
    createOperationSteps(EXPORT_TO_TOURNAMENT_STEPS)
  );
  const [tournamentExportSummary, setTournamentExportSummary] = useState<string | null>(null);
  const [tournamentExportError, setTournamentExportError] = useState<string | null>(null);
  const [isJsonImportOpen, setIsJsonImportOpen] = useState(false);
  const [jsonImportSteps, setJsonImportSteps] = useState<BalancerOperationStep[]>(() =>
    createOperationSteps(IMPORT_JSON_STEPS)
  );
  const [jsonImportSummary, setJsonImportSummary] = useState<string | null>(null);
  const [jsonImportError, setJsonImportError] = useState<string | null>(null);
  const [lastJsonImportFile, setLastJsonImportFile] = useState<File | null>(null);
  const [draftConfig, setDraftConfig] = useState<BalancerConfig>({});
  const [savedTournamentConfig, setSavedTournamentConfig] = useState<BalancerConfig>({});

  const balancerConfigQuery = useQuery({
    queryKey: ["balancer-public", "config"],
    queryFn: () => balancerService.getConfig(),
    staleTime: Number.POSITIVE_INFINITY
  });

  const registrationsQuery = useQuery({
    queryKey: ["balancer-admin", "registrations", tournamentId],
    queryFn: () =>
      balancerAdminService.listRegistrations(tournamentId as number, {
        include_deleted: false
      }),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  const savedBalanceQuery = useQuery({
    queryKey: ["balancer-public", "balance", tournamentId],
    queryFn: () => balancerAdminService.getBalance(tournamentId as number),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  const tournamentConfigQuery = useQuery({
    queryKey: ["balancer-admin", "tournament-config", tournamentId],
    queryFn: () => balancerAdminService.getTournamentConfig(tournamentId as number),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  const customStatusesQuery = useQuery({
    queryKey: ["balancer-admin", "status-catalog", workspaceId],
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });

  const workspaceBalancerConfigQuery = useQuery({
    queryKey: ["workspace-balancer-config", workspaceId],
    queryFn: () => balancerAdminService.getWorkspaceBalancerConfig(workspaceId as number),
    enabled: workspaceId !== null
  });

  /* eslint-disable react-hooks/set-state-in-effect -- Local balancer state intentionally resets when the selected tournament or saved balance changes. */
  useEffect(() => {
    setVariants([]);
    setActiveVariantId(null);
    setSelectedPlayerId(null);
    dispatchJob({ type: "clear" });
    setEditingPlayerId(null);
    setPendingRankHistory(null);
    setExcludeInvalidPlayers(false);
    setIsPoolSidebarCollapsed(false);
    setIsConfigDrawerOpen(false);
    setIsImageExportOpen(false);
    setIsTournamentExportOpen(false);
    setIsJsonImportOpen(false);
    setTournamentExportSteps(createOperationSteps(EXPORT_TO_TOURNAMENT_STEPS));
    setJsonImportSteps(createOperationSteps(IMPORT_JSON_STEPS));
    setTournamentExportSummary(null);
    setTournamentExportError(null);
    setJsonImportSummary(null);
    setJsonImportError(null);
    setLastJsonImportFile(null);
    setDraftConfig({});
    setSavedTournamentConfig({});
  }, [tournamentId]);

  useEffect(() => {
    if (!balancerConfigQuery.data) {
      return;
    }

    const nextConfig = resolveInitialBalancerConfig(
      balancerConfigQuery.data,
      tournamentConfigQuery.data?.config_json
    );
    setDraftConfig(nextConfig);
    setSavedTournamentConfig(nextConfig);
    setSelectedPreset(
      findMatchingPreset(nextConfig, balancerConfigQuery.data.presets) ??
        (tournamentConfigQuery.data ? CUSTOM_PRESET : "DEFAULT")
    );
  }, [balancerConfigQuery.data, tournamentConfigQuery.data]);

  useEffect(() => {
    if (!savedBalanceQuery.data) {
      return;
    }

    const savedVariant = buildVariantFromSavedBalance(savedBalanceQuery.data);
    setVariants((current) => upsertSavedVariant(current, savedVariant));
    setActiveVariantId((current) => current ?? savedVariant.id);
  }, [savedBalanceQuery.data]);

  useEffect(() => {
    variantsRef.current = variants;
  }, [variants]);

  useEffect(() => {
    const activeVariant =
      variantsRef.current.find((variant) => variant.id === activeVariantId) ?? null;
    setCollapsedTeamIds(getDefaultCollapsedTeamIds(activeVariant));
  }, [activeVariantId]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const registrations = registrationsQuery.data ?? [];
  const {
    registrationsById,
    applications,
    applicationsById,
    addableApplications,
    allPlayerValidationStates,
    players,
    readyPlayers,
    poolPlayers,
    invalidPlayerStates,
    missingRankPlayerStates,
    flexPoolCount
  } = useMemo(
    () => buildBalancerPageCollections(registrations, divisionGrid),
    [divisionGrid, registrations]
  );

  const workspaceBalancerConfig = workspaceBalancerConfigQuery.data ?? null;
  const enrichedPlayerValidationStates = useMemo(
    () =>
      allPlayerValidationStates.map((state) => ({
        player: state.player,
        issues: getPlayerValidationIssues(
          state.player,
          applicationsById.get(state.player.application_id) ?? null,
          workspaceBalancerConfig,
          divisionGrid
        )
      })),
    [allPlayerValidationStates, applicationsById, workspaceBalancerConfig, divisionGrid]
  );

  const activeVariant = useMemo(
    () => variants.find((variant) => variant.id === activeVariantId) ?? null,
    [activeVariantId, variants]
  );
  const quickEditPlayer = useMemo(
    () => players.find((player) => player.id === editingPlayerId) ?? null,
    [editingPlayerId, players]
  );
  const quickEditRegistration = useMemo(
    () => (editingPlayerId !== null ? (registrationsById.get(editingPlayerId) ?? null) : null),
    [editingPlayerId, registrationsById]
  );
  const playerStatusOptions = useMemo(
    () => ({
      registration: mergeStatusOptions("registration", customStatusesQuery.data),
      balancer: mergeStatusOptions("balancer", customStatusesQuery.data)
    }),
    [customStatusesQuery.data]
  );
  const presetOptions = useMemo(
    () => getPresetOptions(balancerConfigQuery.data?.presets),
    [balancerConfigQuery.data?.presets]
  );
  const visiblePresetOptions = useMemo(
    () =>
      selectedPreset === CUSTOM_PRESET && !presetOptions.includes(CUSTOM_PRESET)
        ? [...presetOptions, CUSTOM_PRESET]
        : presetOptions,
    [presetOptions, selectedPreset]
  );
  const isConfigDirty = useMemo(
    () => !areBalancerConfigsEqual(draftConfig, savedTournamentConfig),
    [draftConfig, savedTournamentConfig]
  );
  const selectedPresetLabel =
    selectedPreset === CUSTOM_PRESET
      ? "Custom"
      : (PRESET_LABELS[selectedPreset] ??
        (balancerConfigQuery.data?.presets[selectedPreset] ? selectedPreset : "Custom"));
  const saveConfigMutation = useMutation({
    mutationFn: async () => {
      if (!tournamentId) throw new Error("Select a tournament first");
      const saved = await balancerAdminService.upsertTournamentConfig(tournamentId, {
        config_json: sanitizeBalancerConfig(draftConfig) as Record<string, unknown>
      });
      return saved.config_json as BalancerConfig;
    },
    onSuccess: async (config) => {
      setDraftConfig(config);
      setSavedTournamentConfig(config);
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "tournament-config", tournamentId]
      });
      notify.success("Balancer settings saved");
    }
  });

  const exportPlayersMutation = useMutation({
    mutationFn: async () => {
      const selectedTournamentId = tournamentId;
      if (!selectedTournamentId) throw new Error("Select a tournament first");
      const payload = await balancerAdminService.exportPlayers(selectedTournamentId);
      return { payload, tournamentId: selectedTournamentId };
    },
    onSuccess: ({ payload, tournamentId: exportedTournamentId }) => {
      const playerCount = Object.keys(payload.players).length;
      downloadPlayersExport(payload, exportedTournamentId);
      notify.success("Players exported", {
        description: `${playerCount} player${playerCount === 1 ? "" : "s"} downloaded.`
      });
    }
  });

  const handleSelectPreset = useCallback(
    (preset: string) => {
      if (preset === CUSTOM_PRESET) {
        setSelectedPreset(CUSTOM_PRESET);
        return;
      }

      const config =
        balancerConfigQuery.data?.presets[preset] ?? balancerConfigQuery.data?.defaults;
      if (!config) {
        return;
      }

      setSelectedPreset(preset);
      setDraftConfig(sanitizeBalancerConfig(config));
    },
    [balancerConfigQuery.data]
  );

  const handleConfigFieldChange = useCallback((key: keyof BalancerConfig, value: unknown) => {
    setSelectedPreset(CUSTOM_PRESET);
    setDraftConfig((current) =>
      sanitizeBalancerConfig({ ...current, [key]: value }, { preserveDraftStrings: true })
    );
  }, []);

  const handleConfigSavedFromRun = useCallback(
    (config: BalancerConfig) => {
      const sanitized = sanitizeBalancerConfig(config);
      setDraftConfig(sanitized);
      setSavedTournamentConfig(sanitized);
      void queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "tournament-config", tournamentId]
      });
    },
    [queryClient, tournamentId]
  );

  const handleResetConfig = useCallback(() => {
    const nextConfig = balancerConfigQuery.data?.defaults ?? {};
    setDraftConfig(sanitizeBalancerConfig(nextConfig));
    setSelectedPreset("DEFAULT");
  }, [balancerConfigQuery.data?.defaults]);

  const { registerLocalJob } = useBalancerRealtime({
    tournamentId,
    dispatchJob,
    setVariants,
    setActiveVariantId,
    setPresence: setPresenceUserIds
  });

  const {
    addPlayerMutation,
    updatePlayerMutation,
    removePlayerMutation,
    setPlayerPoolMembershipMutation,
    setBalancerStatusMutation,
    bulkPoolMembershipMutation,
    bulkBalancerStatusMutation,
    runBalanceMutation,
    saveBalanceMutation,
    exportToTournamentMutation,
    importTeamsMutation
  } = useBalancerMutations({
    tournamentId,
    workspaceId,
    queryClient,
    dispatchJob,
    setSelectedPlayerId,
    setPendingRankHistory,
    setEditingPlayerId,
    setVariants,
    setActiveVariantId,
    excludeInvalidPlayers,
    invalidPlayerStates,
    readyPlayers,
    poolPlayers,
    selectedPreset,
    balancerConfigData: balancerConfigQuery.data,
    draftConfig,
    isConfigDirty,
    onTournamentConfigSaved: handleConfigSavedFromRun,
    activeVariant,
    onJobCreated: registerLocalJob
  });

  const canRunBalance = useMemo(
    () =>
      getCanRunBalance({
        isRunPending: runBalanceMutation.isPending,
        poolPlayerCount: poolPlayers.length,
        invalidPlayerCount: invalidPlayerStates.length,
        readyPlayerCount: readyPlayers.length,
        excludeInvalidPlayers
      }),
    [
      excludeInvalidPlayers,
      invalidPlayerStates.length,
      poolPlayers.length,
      readyPlayers.length,
      runBalanceMutation.isPending
    ]
  );
  const handleFocusNeedsFixView = useCallback(() => {
    setIsPoolSidebarCollapsed(false);
    sidebarRef.current?.focusNeedsFixView();
  }, []);

  const handleFocusBrowseAvailable = useCallback(() => {
    setIsPoolSidebarCollapsed(false);
    sidebarRef.current?.focusBrowseAvailable();
  }, []);

  const handleOpenPlayerEditor = useCallback((playerId: number | null) => {
    setSelectedPlayerId(playerId);
    setEditingPlayerId(playerId);
  }, []);

  const handleSetPoolMembership = useCallback(
    (playerId: number, isInPool: boolean) =>
      setPlayerPoolMembershipMutation.mutateAsync({ playerId, isInPool }),
    [setPlayerPoolMembershipMutation]
  );

  const handleSetBalancerStatus = useCallback(
    (playerId: number, balancerStatus: string) =>
      setBalancerStatusMutation.mutateAsync({ playerId, balancerStatus }),
    [setBalancerStatusMutation]
  );

  const handleBulkPoolMembership = useCallback(
    (playerIds: number[], isInPool: boolean) =>
      bulkPoolMembershipMutation.mutateAsync({ playerIds, isInPool }),
    [bulkPoolMembershipMutation]
  );

  const handleBulkBalancerStatus = useCallback(
    (playerIds: number[], balancerStatus: string) =>
      bulkBalancerStatusMutation.mutateAsync({ playerIds, balancerStatus }),
    [bulkBalancerStatusMutation]
  );

  const handleBalancePayloadChange = useCallback(
    (payload: Parameters<typeof replaceVariantPayload>[2]) => {
      if (!activeVariantId) {
        return;
      }

      setVariants((current) => replaceVariantPayload(current, activeVariantId, payload));
    },
    [activeVariantId]
  );

  const handleToggleTeam = useCallback((teamId: number) => {
    setCollapsedTeamIds((current) => toggleCollapsedTeamId(current, teamId));
  }, []);

  const handleScreenshot = useCallback(() => {
    setIsImageExportOpen(true);
  }, []);

  const handleCopyNames = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(buildTeamNamesText(activeVariant?.payload ?? null));
      notify.success("Team names copied");
    } catch {
      notify.error("Clipboard unavailable");
    }
  }, [activeVariant]);

  const handleTournamentExportStageChange = useCallback(
    (stepId: string, status: BalancerOperationStepStatus) => {
      setTournamentExportSteps((current) => updateOperationStepStatus(current, stepId, status));
    },
    []
  );

  const handleJsonImportStageChange = useCallback(
    (stepId: string, status: BalancerOperationStepStatus) => {
      setJsonImportSteps((current) => updateOperationStepStatus(current, stepId, status));
    },
    []
  );

  const startTournamentExport = useCallback(() => {
    setTournamentExportSteps(createOperationSteps(EXPORT_TO_TOURNAMENT_STEPS));
    setTournamentExportSummary(null);
    setTournamentExportError(null);
    setIsTournamentExportOpen(true);
    exportToTournamentMutation.mutate(
      { onStageChange: handleTournamentExportStageChange },
      {
        onSuccess: ({ exportResult }) => {
          setTournamentExportSummary(
            `${exportResult.imported_teams} teams exported to the tournament. ${exportResult.removed_teams} previously exported teams removed.`
          );
        },
        onError: (error) => {
          setTournamentExportError(
            getErrorMessage(error, "Failed to export teams to the tournament")
          );
        }
      }
    );
  }, [exportToTournamentMutation, handleTournamentExportStageChange]);

  const startJsonImport = useCallback(
    (file: File) => {
      setLastJsonImportFile(file);
      setJsonImportSteps(createOperationSteps(IMPORT_JSON_STEPS));
      setJsonImportSummary(null);
      setJsonImportError(null);
      setIsJsonImportOpen(true);
      importTeamsMutation.mutate(
        { file, onStageChange: handleJsonImportStageChange },
        {
          onSuccess: (result) => {
            setJsonImportSummary(`${result.imported_teams} teams imported from ${file.name}.`);
          },
          onError: (error) => {
            setJsonImportError(getErrorMessage(error, "Failed to import teams from JSON"));
          }
        }
      );
    },
    [handleJsonImportStageChange, importTeamsMutation]
  );

  const quickPoolActionsPending =
    setPlayerPoolMembershipMutation.isPending ||
    setBalancerStatusMutation.isPending ||
    bulkPoolMembershipMutation.isPending ||
    bulkBalancerStatusMutation.isPending;

  const handleDeleteVariant = useCallback((id: string) => {
    setVariants((current) => {
      const next = current.filter((v) => v.id !== id);
      setActiveVariantId((currentActive) => {
        if (currentActive !== id) return currentActive;
        return next[0]?.id ?? null;
      });
      return next;
    });
  }, []);

  const variantSelector =
    variants.length > 1 ? (
      <VariantSelector
        variants={variants}
        activeVariantId={activeVariantId}
        onSelectVariant={setActiveVariantId}
        onDeleteVariant={handleDeleteVariant}
      />
    ) : undefined;

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>
          Choose a tournament in the balancer header to work with registrations and the Balancing
          Pool.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <>
      {quickEditPlayer ? (
        <PlayerEditModal
          player={quickEditPlayer}
          registration={quickEditRegistration}
          statusOptions={playerStatusOptions}
          open={editingPlayerId !== null}
          onOpenChange={(open) => {
            if (!open) {
              setEditingPlayerId(null);
              setPendingRankHistory(null);
            }
          }}
          saving={updatePlayerMutation.isPending}
          onSave={(playerId, payload) => updatePlayerMutation.mutate({ playerId, payload })}
          onRemove={(playerId) => removePlayerMutation.mutate(playerId)}
          rankHistory={pendingRankHistory}
        />
      ) : null}

      <BalancerConfigDrawer
        open={isConfigDrawerOpen}
        onOpenChange={setIsConfigDrawerOpen}
        fields={balancerConfigQuery.data?.fields ?? []}
        config={draftConfig}
        selectedPresetLabel={selectedPresetLabel}
        dirty={isConfigDirty}
        saving={saveConfigMutation.isPending}
        onChange={handleConfigFieldChange}
        onSave={() => saveConfigMutation.mutate()}
        onReset={handleResetConfig}
      />

      <BalanceImageExportDialog
        open={isImageExportOpen}
        onOpenChange={setIsImageExportOpen}
        payload={activeVariant?.payload ?? null}
        divisionGrid={divisionGrid}
        tournamentId={tournamentId}
      />

      <BalancerOperationDialog
        open={isTournamentExportOpen}
        onOpenChange={setIsTournamentExportOpen}
        title="Export to Tournament"
        description="Save the selected balance and create tournament teams from it."
        steps={tournamentExportSteps}
        isRunning={exportToTournamentMutation.isPending}
        summary={tournamentExportSummary}
        error={tournamentExportError}
        retryLabel="Retry export"
        onRetry={startTournamentExport}
      />

      <BalancerOperationDialog
        open={isJsonImportOpen}
        onOpenChange={setIsJsonImportOpen}
        title="Import JSON"
        description="Import a previously downloaded balance JSON into the selected tournament."
        steps={jsonImportSteps}
        isRunning={importTeamsMutation.isPending}
        summary={jsonImportSummary}
        error={jsonImportError}
        retryLabel="Retry import"
        onRetry={lastJsonImportFile ? () => startJsonImport(lastJsonImportFile) : undefined}
      />

      {/* Renders into the sidebar footer via a portal; returns null when nobody is viewing. */}
      <BalancerPresenceStack userIds={presenceUserIds} workspaceId={workspaceId} />

      <div className="flex min-h-0 w-full flex-1 flex-col gap-3 pb-4">
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            isPoolSidebarCollapsed
              ? "xl:grid-cols-[72px_minmax(0,1fr)]"
              : "xl:grid-cols-[460px_minmax(0,1fr)]"
          )}
        >
          <BalancingPoolSidebar
            ref={sidebarRef}
            key={tournamentId}
            collapsed={isPoolSidebarCollapsed}
            onToggleCollapsed={() => setIsPoolSidebarCollapsed((current) => !current)}
            allPlayerValidationStates={enrichedPlayerValidationStates}
            applications={applications}
            addableApplications={addableApplications}
            registrationsById={registrationsById}
            balancerStatusOptions={playerStatusOptions.balancer}
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={handleOpenPlayerEditor}
            onAddFromApplication={(application) => addPlayerMutation.mutate(application)}
            onSetPoolMembership={handleSetPoolMembership}
            onSetBalancerStatus={handleSetBalancerStatus}
            onBulkPoolMembership={handleBulkPoolMembership}
            onBulkBalancerStatus={handleBulkBalancerStatus}
            isAddingPlayer={addPlayerMutation.isPending}
            actionsDisabled={quickPoolActionsPending}
            missingRankCount={missingRankPlayerStates.length}
            workspaceId={workspaceId ?? undefined}
            workspaceBalancerConfig={workspaceBalancerConfig}
          />

          <div className="flex min-h-0 flex-col gap-3">
            <PresetRunPanel
              counters={[
                { label: "Pool", value: poolPlayers.length, icon: Users },
                { label: "Ready", value: readyPlayers.length, icon: CheckCircle2 },
                { label: "Need Fix", value: invalidPlayerStates.length, icon: AlertTriangle },
                { label: "Flex", value: flexPoolCount, icon: Shuffle }
              ]}
              presetOptions={visiblePresetOptions}
              selectedPreset={selectedPreset}
              onSelectPreset={handleSelectPreset}
              invalidPlayerCount={invalidPlayerStates.length}
              excludeInvalidPlayers={excludeInvalidPlayers}
              onExcludeInvalidPlayersChange={setExcludeInvalidPlayers}
              onOpenSettings={() => setIsConfigDrawerOpen(true)}
              settingsDirty={isConfigDirty}
              canRunBalance={canRunBalance}
              onRunBalance={() => runBalanceMutation.mutate()}
              isRunPending={runBalanceMutation.isPending}
              onImportTeams={startJsonImport}
              isImportPending={importTeamsMutation.isPending}
              onExportPlayers={() => exportPlayersMutation.mutate()}
              isExportPlayersPending={exportPlayersMutation.isPending}
              jobStatus={jobState.status}
              jobMessage={jobState.message}
              jobProgress={jobState.progress}
            />

            {activeVariant ? (
              <TeamDistributionPanel variant={activeVariant} variantSelector={variantSelector} />
            ) : null}

            <BalancerEditorPanel
              activeVariant={activeVariant}
              balanceEditorRef={balanceEditorRef}
              divisionGrid={divisionGrid}
              selectedPlayerId={selectedPlayerId}
              collapsedTeamIds={collapsedTeamIds}
              poolPlayerCount={poolPlayers.length}
              invalidPlayerCount={invalidPlayerStates.length}
              canRunBalance={canRunBalance}
              isRunPending={runBalanceMutation.isPending}
              realtimeTopic={balancerRealtimeTopic(tournamentId)}
              currentUserId={currentUserId}
              workspaceId={workspaceId}
              onChangePayload={handleBalancePayloadChange}
              onSelectPlayer={handleOpenPlayerEditor}
              onToggleTeam={handleToggleTeam}
              onBrowseAvailable={handleFocusBrowseAvailable}
              onReviewConflicts={handleFocusNeedsFixView}
              onRunBalance={() => runBalanceMutation.mutate()}
            />

            <BalancerActionsPanel
              activeVariant={activeVariant}
              canRunBalance={canRunBalance}
              isSavePending={saveBalanceMutation.isPending}
              isExportPending={exportToTournamentMutation.isPending}
              tournamentId={tournamentId}
              onRunBalance={() => runBalanceMutation.mutate()}
              onSaveBalance={() => saveBalanceMutation.mutate()}
              onExportBalance={startTournamentExport}
              onCopyNames={handleCopyNames}
              onScreenshot={handleScreenshot}
            />
          </div>
        </div>
      </div>
    </>
  );
}
