"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, Shuffle, Users } from "lucide-react";
import type { ImperativePanelHandle } from "react-resizable-panels";

import {
  BalancingPoolSidebar,
  type BalancingPoolSidebarHandle
} from "@/app/balancer/components/BalancingPoolSidebar";
import { WorkspacePlayersSidebar } from "@/app/balancer/components/WorkspacePlayersSidebar";
import { PresetRunPanel } from "@/app/balancer/components/PresetRunPanel";
import { TeamDistributionPanel } from "@/app/balancer/components/TeamDistributionPanel";
import { VariantSelector } from "@/app/balancer/components/VariantSelector";
import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { useBalancerJob } from "@/app/balancer/components/useBalancerJob";
import { useBalancerMutations } from "@/app/balancer/components/useBalancerMutations";
import {
  balancerRealtimeTopic,
  useBalancerRealtime
} from "@/app/balancer/components/useBalancerRealtime";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { mergeStatusOptions } from "@/lib/registration/balancer-statuses";
import { ratedDimension, slotCodeOrder } from "@/lib/roster/ontology";
import { slotCodesOf } from "@/lib/roster/shape";
import { tournamentOverviewQueryOptions } from "@/lib/tournament/overview-query";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import balancerService from "@/services/balancer.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { BalancerPlayerExportFormat } from "@/types/balancer-admin.types";
import type { BalancerConfig, BalancerConfigValue } from "@/types/balancer.types";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";

import { BalancerActionsPanel } from "./BalancerActionsPanel";
import { BalancerEditorPanel } from "./BalancerEditorPanel";
import { BalancerPresenceStack } from "./BalancerPresenceStack";
import {
  createOperationSteps,
  updateOperationStepStatus,
  type BalancerOperationStep,
  type BalancerOperationStepStatus
} from "./operation-steps";
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
import {
  buildTeamNamesText,
  buildVariantFromSavedBalance,
  createSyntheticPlayerFromRegistration,
  downloadPlayersExport,
  getPlayerValidationIssues,
  type BalanceVariant
} from "@/components/balancer/workspace-helpers";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import {
  EXPORT_TO_TOURNAMENT_STEPS,
  IMPORT_JSON_STEPS,
  RAIL_WIDTH_PX,
  SIDEBAR_MIN_PX,
  getErrorMessage,
  useGroupWidth,
  useIsWideBalancerLayout
} from "./useBalancerLayout";

// Dialogs and sheets that render nothing until opened: lazy chunks, so they
// (and the image rasteriser behind the export dialog) are not first-load JS.
const PlayerEditModal = dynamic(
  () => import("@/app/balancer/components/PlayerEditSheet").then((m) => m.PlayerEditModal),
  { ssr: false }
);
const BalancerConfigDrawer = dynamic(
  () => import("@/app/balancer/components/BalancerConfigDrawer").then((m) => m.BalancerConfigDrawer),
  { ssr: false }
);
const BalanceImageExportDialog = dynamic(
  () => import("./BalanceImageExportDialog").then((m) => m.BalanceImageExportDialog),
  { ssr: false }
);
const BalancerOperationDialog = dynamic(
  () => import("./BalancerOperationDialog").then((m) => m.BalancerOperationDialog),
  { ssr: false }
);

export function BalancerMainPageClient() {
  const t = useTranslations("balancerTool.page");
  const tournamentId = useBalancerTournamentId();
  const workspaceId = useWorkspaceStore(
    (state) => state.entityWorkspaceId ?? state.currentWorkspaceId
  );
  const { canAccessPermission } = usePermissions();
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  const queryClient = useQueryClient();
  const sidebarRef = useRef<BalancingPoolSidebarHandle>(null);
  const balanceEditorRef = useRef<HTMLDivElement | null>(null);
  const variantsRef = useRef<BalanceVariant[]>([]);
  const sidebarPanelRef = useRef<ImperativePanelHandle>(null);
  const playersPanelRef = useRef<ImperativePanelHandle>(null);
  const panelGroupRef = useRef<HTMLDivElement | null>(null);
  const isWideLayout = useIsWideBalancerLayout();
  const groupWidth = useGroupWidth(panelGroupRef);
  const railPercent = Math.min(12, Math.max(2, (RAIL_WIDTH_PX / groupWidth) * 100));
  const sidebarMinPercent = Math.min(40, Math.max(12, (SIDEBAR_MIN_PX / groupWidth) * 100));

  const [selectedPreset, setSelectedPreset] = useState("DEFAULT");
  const [jobState, dispatchJob] = useBalancerJob();
  const [variants, setVariants] = useState<BalanceVariant[]>([]);
  const [activeVariantId, setActiveVariantId] = useState<string | null>(null);
  const [presenceUserIds, setPresenceUserIds] = useState<number[]>([]);
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [editingPlayerId, setEditingPlayerId] = useState<number | null>(null);
  const [excludeInvalidPlayers, setExcludeInvalidPlayers] = useState(false);
  const [collapsedTeamIds, setCollapsedTeamIds] = useState<number[]>([]);
  const [isPoolSidebarCollapsed, setIsPoolSidebarCollapsed] = useState(false);
  const [isPlayersSidebarCollapsed, setIsPlayersSidebarCollapsed] = useState(true);
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

  // `collapse()` snaps to the CURRENT `collapsedSize`, so an already-collapsed rail
  // has to be re-collapsed after the group is measured or resized. Panels the user
  // left expanded are untouched, which is what keeps `autoSaveId` meaningful.
  useEffect(() => {
    if (isPoolSidebarCollapsed) sidebarPanelRef.current?.collapse();
    if (isPlayersSidebarCollapsed) playersPanelRef.current?.collapse();
  }, [railPercent, isPoolSidebarCollapsed, isPlayersSidebarCollapsed]);

  const registrationsQuery = useQuery({
    queryKey: balancerQueryKeys.registrations(tournamentId),
    queryFn: () =>
      balancerAdminService.listRegistrations(tournamentId as number, {
        include_deleted: false
      }),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  const savedBalanceQuery = useQuery({
    queryKey: balancerQueryKeys.publicBalance(tournamentId),
    queryFn: () => balancerAdminService.getBalance(tournamentId as number),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  const tournamentConfigQuery = useQuery({
    queryKey: balancerQueryKeys.tournamentConfig(tournamentId),
    queryFn: () => balancerAdminService.getTournamentConfig(tournamentId as number),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  // Owner metadata supplies both roster shape and the player editor's grid pin.
  // Reuse the public shell's query and embedded version rather than refetching it.
  const tournamentQuery = useQuery({
    ...tournamentOverviewQueryOptions(tournamentId as number),
    enabled: tournamentId !== null
  });
  const divisionGrid = useDivisionGrid(tournamentQuery.data?.discipline);
  // The solver config of the tournament's game: its defaults and presets carry that game's role weights.
  const configDiscipline = tournamentQuery.data?.discipline ?? null;
  const balancerConfigQuery = useQuery({
    queryKey: balancerQueryKeys.publicConfig(configDiscipline),
    queryFn: ({ signal }) => balancerService.getConfig(configDiscipline as string, signal),
    enabled: configDiscipline !== null,
    staleTime: Number.POSITIVE_INFINITY
  });
  const ontology = useDisciplineMetadata(
    tournamentQuery.data?.workspace_id ?? "all",
    tournamentQuery.data?.discipline ?? null
  ).data ?? null;
  const slotLabel = useSlotLabel(ontology);
  // Whose handle answers name a player; `null` while the game's metadata loads or for a game with no identity.
  const identityProvider = ontology?.discipline.identity_provider ?? null;
  // The buckets a balance file may carry: the owner game's role codes and the open slot. `null` while they load.
  const slotCodes = ontology ? slotCodeOrder(ontology) : null;
  const roleCodes = tournamentQuery.data?.roster_shape
    ? slotCodesOf(tournamentQuery.data.roster_shape.slots)
    : null;

  const customStatusesQuery = useQuery({
    queryKey: balancerQueryKeys.statusCatalog(workspaceId),
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });

  const workspaceBalancerConfigQuery = useQuery({
    queryKey: balancerQueryKeys.workspaceConfig(workspaceId),
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
    setExcludeInvalidPlayers(false);
    setIsPoolSidebarCollapsed(false);
    sidebarPanelRef.current?.expand();
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
    allPlayerValidationStates,
    readyPlayers,
    poolPlayers,
    invalidPlayerStates,
    flexPoolCount
  } = useMemo(
    () => buildBalancerPageCollections(registrations, divisionGrid, slotLabel, identityProvider),
    [divisionGrid, registrations, slotLabel, identityProvider]
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
          divisionGrid,
          slotLabel
        )
      })),
    [allPlayerValidationStates, applicationsById, workspaceBalancerConfig, divisionGrid, slotLabel]
  );

  const activeVariant = useMemo(
    () => variants.find((variant) => variant.id === activeVariantId) ?? null,
    [activeVariantId, variants]
  );
  // The persisted balance is only "current" while the active variant is the saved
  // one and nobody has edited it since. Any editor change or a regenerated variant
  // is new work, so Save/Export become available again.
  const isBalanceSaved = activeVariant?.source === "saved" && !activeVariant.dirty;
  const isBalanceExported = isBalanceSaved && savedBalanceQuery.data?.exported_at != null;
  const quickEditRegistration = useMemo(
    () => (editingPlayerId !== null ? (registrationsById.get(editingPlayerId) ?? null) : null),
    [editingPlayerId, registrationsById]
  );
  // Edited on the registration's real per-role ranks, never the `allRoles`-flattened
  // view `players` carries for the pool table/validation/solver (see
  // `buildBalancerPageCollections`) — that max-rank flattening is a read-only
  // computation aid for flex tournaments, not ground truth to save back over
  // the player's actual ranks.
  const quickEditPlayer = useMemo(
    () =>
      quickEditRegistration
        ? createSyntheticPlayerFromRegistration(quickEditRegistration, divisionGrid, identityProvider)
        : null,
    [quickEditRegistration, divisionGrid, identityProvider]
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
  // Presets the catalog names read translated; a server preset it does not know reads as its key.
  const presetKey = `presets.${selectedPreset}` as "presets.DEFAULT";
  const selectedPresetLabel = t.has(presetKey)
    ? t(presetKey)
    : balancerConfigQuery.data?.presets[selectedPreset]
      ? selectedPreset
      : t("presets.CUSTOM");
  const saveConfigMutation = useMutation({
    mutationFn: async () => {
      if (!tournamentId) throw new Error(t("errors.noTournament"));
      const saved = await balancerAdminService.upsertTournamentConfig(tournamentId, {
        config_json: sanitizeBalancerConfig(draftConfig) as Record<string, unknown>
      });
      return saved.config_json as BalancerConfig;
    },
    onSuccess: async (config) => {
      setDraftConfig(config);
      setSavedTournamentConfig(config);
      await queryClient.invalidateQueries({
        queryKey: balancerQueryKeys.tournamentConfig(tournamentId)
      });
      notify.success(t("toasts.settingsSaved"));
    }
  });

  const exportPlayersMutation = useMutation({
    mutationFn: async ({
      format,
      includePrivate
    }: {
      format: BalancerPlayerExportFormat;
      includePrivate: boolean;
    }) => {
      const selectedTournamentId = tournamentId;
      if (!selectedTournamentId) throw new Error(t("errors.noTournament"));
      const payload = await balancerAdminService.exportPlayers(
        selectedTournamentId,
        format,
        includePrivate
      );
      return { payload, tournamentId: selectedTournamentId };
    },
    onSuccess: ({ payload, tournamentId: exportedTournamentId }) => {
      const playerCount = Object.keys(payload.players).length;
      downloadPlayersExport(payload, exportedTournamentId);
      notify.success(t("toasts.playersExported"), {
        description: t("toasts.playersExportedDescription", { count: playerCount, format: payload.format })
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

  const handleConfigFieldChange = useCallback((key: string, value: BalancerConfigValue) => {
    setSelectedPreset(CUSTOM_PRESET);
    setDraftConfig((current) => sanitizeBalancerConfig({ ...current, [key]: value }));
  }, []);

  const handleConfigSavedFromRun = useCallback(
    (config: BalancerConfig) => {
      const sanitized = sanitizeBalancerConfig(config);
      setDraftConfig(sanitized);
      setSavedTournamentConfig(sanitized);
      void queryClient.invalidateQueries({
        queryKey: balancerQueryKeys.tournamentConfig(tournamentId)
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
    updatePlayerMutation,
    setPlayerPoolMembershipMutation,
    setBalancerStatusMutation,
    bulkPoolMembershipMutation,
    bulkBalancerStatusMutation,
    runBalanceMutation,
    saveBalanceMutation,
    exportToTournamentMutation,
    exportRanksMutation,
    importBalanceMutation
  } = useBalancerMutations({
    tournamentId,
    workspaceId,
    queryClient,
    dispatchJob,
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
    onJobCreated: registerLocalJob,
    slotCodes,
    ratedDimension: ontology ? (ratedDimension(ontology)?.code ?? null) : null
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

  const handleFocusExcludedView = useCallback(() => {
    setIsPoolSidebarCollapsed(false);
    sidebarRef.current?.focusExcludedView();
  }, []);
  const handleToggleSidebarCollapsed = useCallback(() => {
    const panel = sidebarPanelRef.current;
    if (panel) {
      if (panel.isCollapsed()) {
        panel.expand();
      } else {
        panel.collapse();
      }
      return;
    }
    setIsPoolSidebarCollapsed((current) => !current);
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
      notify.success(t("toasts.namesCopied"));
    } catch {
      notify.error(t("toasts.namesCopyFailed"));
    }
  }, [activeVariant, t]);

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
            t("operation.exportSummary", {
              imported: exportResult.imported_teams,
              removed: exportResult.removed_teams
            })
          );
        },
        onError: (error) => {
          setTournamentExportError(getErrorMessage(error, t("errors.exportFailed")));
        }
      }
    );
  }, [exportToTournamentMutation, handleTournamentExportStageChange, t]);

  const savedBalanceId = savedBalanceQuery.data?.id ?? null;
  const startRanksExport = useCallback(() => {
    if (savedBalanceId === null) return;
    exportRanksMutation.mutate(savedBalanceId);
  }, [exportRanksMutation, savedBalanceId]);

  const startJsonImport = useCallback(
    (file: File) => {
      setLastJsonImportFile(file);
      setJsonImportSteps(createOperationSteps(IMPORT_JSON_STEPS));
      setJsonImportSummary(null);
      setJsonImportError(null);
      setIsJsonImportOpen(true);
      importBalanceMutation.mutate(
        { file, onStageChange: handleJsonImportStageChange },
        {
          onSuccess: (result) => {
            setJsonImportSummary(
              t("operation.importSummary", { count: result.teamCount, file: file.name })
            );
          },
          onError: (error) => {
            setJsonImportError(getErrorMessage(error, t("errors.importFailed")));
          }
        }
      );
    },
    [handleJsonImportStageChange, importBalanceMutation, t]
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
        <AlertTitle>{t("selectTournament.title")}</AlertTitle>
        <AlertDescription>{t("selectTournament.description")}</AlertDescription>
      </Alert>
    );
  }

  const sidebarElement = (
    <BalancingPoolSidebar
      ref={sidebarRef}
      key={tournamentId}
      collapsed={isWideLayout && isPoolSidebarCollapsed}
      onToggleCollapsed={isWideLayout ? handleToggleSidebarCollapsed : undefined}
      allPlayerValidationStates={enrichedPlayerValidationStates}
      ontology={ontology}
      divisionGrid={divisionGrid}
      applications={applications}
      registrationsById={registrationsById}
      balancerStatusOptions={playerStatusOptions.balancer}
      selectedPlayerId={selectedPlayerId}
      onSelectPlayer={handleOpenPlayerEditor}
      onSetPoolMembership={handleSetPoolMembership}
      onSetBalancerStatus={handleSetBalancerStatus}
      onBulkPoolMembership={handleBulkPoolMembership}
      onBulkBalancerStatus={handleBulkBalancerStatus}
      actionsDisabled={quickPoolActionsPending}
      workspaceId={workspaceId ?? undefined}
      workspaceBalancerConfig={workspaceBalancerConfig}
    />
  );

  // Stacked (below `xl`) the sidebars are full-width rows, where a collapsed rail
  // would be a viewport-wide strip of vertical text — so the rail only exists
  // beside the editor.
  const playersElement =
    workspaceId == null || !tournamentQuery.data ? null : (
      <WorkspacePlayersSidebar
        key={workspaceId}
        workspaceId={workspaceId}
        discipline={tournamentQuery.data.discipline}
        canEdit={canAccessPermission("team.update", workspaceId)}
        collapsed={isWideLayout && isPlayersSidebarCollapsed}
        onToggleCollapsed={
          isWideLayout
            ? () => {
                const panel = playersPanelRef.current;
                if (panel) {
                  if (panel.isCollapsed()) panel.expand();
                  else panel.collapse();
                  return;
                }
                setIsPlayersSidebarCollapsed((current) => !current);
              }
            : undefined
        }
      />
    );

  const balancerContentElement = (
    // `min-w-0`: same grid-item rule the two sidebars already carry. Without it
    // this column keeps its min-content width (~1350px: the team-card grid's
    // preferred three tracks) and the panel's own `overflow: hidden` clips the
    // right-hand cards, the variant strip and the actions bar the moment the
    // pool sidebar is widened.
    <div className="flex min-h-0 min-w-0 flex-col gap-3">
      <PresetRunPanel
        counters={[
          { label: t("counters.pool"), value: poolPlayers.length, icon: Users },
          { label: t("counters.ready"), value: readyPlayers.length, icon: CheckCircle2 },
          { label: t("counters.needFix"), value: invalidPlayerStates.length, icon: AlertTriangle },
          { label: t("counters.flex"), value: flexPoolCount, icon: Shuffle }
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
        onImportBalance={startJsonImport}
        isImportPending={importBalanceMutation.isPending}
        onExportPlayers={(format, includePrivate) =>
          exportPlayersMutation.mutate({ format, includePrivate })
        }
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
        ontology={ontology}
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
        onBrowseExcluded={handleFocusExcludedView}
        onReviewConflicts={handleFocusNeedsFixView}
        onRunBalance={() => runBalanceMutation.mutate()}
      />

      <BalancerActionsPanel
        activeVariant={activeVariant}
        canRunBalance={canRunBalance}
        isSavePending={saveBalanceMutation.isPending}
        isExportPending={exportToTournamentMutation.isPending}
        isBalanceSaved={isBalanceSaved}
        isBalanceExported={isBalanceExported}
        canExportRanks={savedBalanceId !== null}
        isExportRanksPending={exportRanksMutation.isPending}
        tournamentId={tournamentId}
        onRunBalance={() => runBalanceMutation.mutate()}
        onSaveBalance={() => saveBalanceMutation.mutate()}
        onExportBalance={startTournamentExport}
        onExportRanks={startRanksExport}
        onCopyNames={handleCopyNames}
        onScreenshot={handleScreenshot}
      />
    </div>
  );

  return (
    <>
      {quickEditPlayer ? (
        <PlayerEditModal
          player={quickEditPlayer}
          registration={quickEditRegistration}
          discipline={tournamentQuery.data?.discipline}
          divisionGridVersionId={tournamentQuery.data?.division_grid_version_id}
          ontology={ontology}
          divisionGridVersion={tournamentQuery.data?.division_grid_version}
          statusOptions={playerStatusOptions}
          open={editingPlayerId !== null}
          onOpenChange={(open) => {
            if (!open) {
              setEditingPlayerId(null);
            }
          }}
          saving={updatePlayerMutation.isPending}
          onSave={(playerId, payload) => updatePlayerMutation.mutate({ playerId, payload })}
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
        roleCodes={roleCodes}
        ontology={ontology}
      />

      <BalanceImageExportDialog
        open={isImageExportOpen}
        onOpenChange={setIsImageExportOpen}
        payload={activeVariant?.payload ?? null}
        divisionGrid={divisionGrid}
        ontology={ontology}
        tournamentId={tournamentId}
      />

      <BalancerOperationDialog
        open={isTournamentExportOpen}
        onOpenChange={setIsTournamentExportOpen}
        title={t("operation.exportTitle")}
        description={t("operation.exportDescription")}
        steps={tournamentExportSteps}
        isRunning={exportToTournamentMutation.isPending}
        summary={tournamentExportSummary}
        advisories={exportToTournamentMutation.data?.exportResult.advisories}
        error={tournamentExportError}
        retryLabel={t("operation.retryExport")}
        onRetry={startTournamentExport}
      />

      <BalancerOperationDialog
        open={isJsonImportOpen}
        onOpenChange={setIsJsonImportOpen}
        title={t("operation.importTitle")}
        description={t("operation.importDescription")}
        steps={jsonImportSteps}
        isRunning={importBalanceMutation.isPending}
        summary={jsonImportSummary}
        error={jsonImportError}
        retryLabel={t("operation.retryImport")}
        onRetry={lastJsonImportFile ? () => startJsonImport(lastJsonImportFile) : undefined}
      />

      {/* Renders into the tool top-bar via a portal; returns null when nobody is viewing. */}
      <BalancerPresenceStack userIds={presenceUserIds} workspaceId={workspaceId} />

      {/* The shell already insets the tool with `p-3 md:p-4`; a second bottom pad just wasted space. */}
      <div ref={panelGroupRef} className="flex min-h-0 w-full flex-1 flex-col gap-3">
        {isWideLayout ? (
          <ResizablePanelGroup
            direction="horizontal"
            autoSaveId="balancer-pool-panel-layout"
            className="min-h-0 flex-1"
          >
            <ResizablePanel
              ref={sidebarPanelRef}
              id="balancer-pool-sidebar-panel"
              defaultSize={27}
              minSize={sidebarMinPercent}
              maxSize={45}
              collapsible
              collapsedSize={railPercent}
              onCollapse={() => setIsPoolSidebarCollapsed(true)}
              onExpand={() => setIsPoolSidebarCollapsed(false)}
              className="grid min-h-0"
            >
              {sidebarElement}
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel
              id="balancer-pool-content-panel"
              minSize={40}
              className="grid min-h-0 pl-3"
            >
              {balancerContentElement}
            </ResizablePanel>
            {playersElement ? (
              <>
                <ResizableHandle withHandle />
                <ResizablePanel
                  ref={playersPanelRef}
                  id="balancer-players-sidebar-panel"
                  // `defaultSize === collapsedSize` starts the panel collapsed on a
                  // first visit and fires `onCollapse`; a mount-time `collapse()` call
                  // instead re-collapsed it on every mount, so `autoSaveId` could never
                  // restore a sidebar the user had expanded.
                  defaultSize={railPercent}
                  minSize={sidebarMinPercent}
                  maxSize={36}
                  collapsible
                  collapsedSize={railPercent}
                  onCollapse={() => setIsPlayersSidebarCollapsed(true)}
                  onExpand={() => setIsPlayersSidebarCollapsed(false)}
                  className="grid min-h-0 pl-3"
                >
                  {playersElement}
                </ResizablePanel>
              </>
            ) : null}
          </ResizablePanelGroup>
        ) : (
          <div className="grid min-h-0 flex-1 gap-3">
            {sidebarElement}
            {balancerContentElement}
            {playersElement}
          </div>
        )}
      </div>
    </>
  );
}
