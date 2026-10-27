"use client";

import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import type React from "react";
import type { JobAction } from "./useBalancerJob";
import { parseImportedBalancePayload } from "./balance-import";
import { sanitizeBalancerConfig } from "./balancer-config-helpers";
import {
  buildVariantFromSavedBalance,
  type BalanceVariant
} from "@/components/balancer/workspace-helpers";
import type { PlayerValidationState } from "@/components/balancer/balancer-page-helpers";
import {
  buildRegistrationUpdateFromPlayerPayload,
  RatedDimensionUnknownError
} from "@/components/balancer/registration-update-payload";
import balancerAdminService from "@/services/balancer-admin.service";
import balancerService from "@/services/balancer.service";
import type {
  AdminRegistration,
  AdminRegistrationUpdateInput,
  BalanceExportResponse,
  BalancerPlayerRecord,
  BalancerPlayerUpdateInput,
  BalanceSaveInput,
  SavedBalance
} from "@/types/balancer-admin.types";
import type { BalancerConfig, BalancerConfigResponse } from "@/types/balancer.types";
import { notify } from "@/lib/notify";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

type UseBalancerMutationsOptions = {
  tournamentId: number | null;
  workspaceId: number | null;
  queryClient: QueryClient;
  dispatchJob: React.Dispatch<JobAction>;
  setEditingPlayerId: (id: number | null) => void;
  setVariants: React.Dispatch<React.SetStateAction<BalanceVariant[]>>;
  setActiveVariantId: React.Dispatch<React.SetStateAction<string | null>>;
  excludeInvalidPlayers: boolean;
  invalidPlayerStates: PlayerValidationState[];
  readyPlayers: BalancerPlayerRecord[];
  poolPlayers: BalancerPlayerRecord[];
  selectedPreset: string;
  balancerConfigData: BalancerConfigResponse | undefined;
  draftConfig: BalancerConfig;
  isConfigDirty: boolean;
  onTournamentConfigSaved: (config: BalancerConfig) => void;
  activeVariant: BalanceVariant | null;
  /** The owner game's slot codes (role codes and the open slot) a balance file may carry; `null` while its roles load. */
  slotCodes: readonly string[] | null;
  /** The owner game's rated role dimension a player-sheet save writes its role entries in; `null` while its roles load. */
  ratedDimension: string | null;
  /**
   * Called once a balance job is created so the realtime layer can attach the
   * run-local context (skipped count, config) to the eventual `succeeded`
   * event. The variants themselves are applied by the realtime handler so the
   * initiator and every other viewer share one code path.
   */
  onJobCreated: (
    jobId: string,
    context: { skipped: number; config: BalancerConfig | undefined }
  ) => void;
};

type FlowStepStatus = "pending" | "running" | "succeeded" | "failed";
type FlowStageReporter = (stepId: string, status: FlowStepStatus) => void;

type ExportToTournamentVariables = {
  onStageChange?: FlowStageReporter;
};

type ImportBalanceVariables = {
  file: File;
  onStageChange?: FlowStageReporter;
};

type ExportToTournamentResult = {
  savedBalance: SavedBalance;
  exportResult: BalanceExportResponse;
};

async function runReportedStage<T>(
  stepId: string,
  onStageChange: FlowStageReporter | undefined,
  action: () => Promise<T>
): Promise<T> {
  onStageChange?.(stepId, "running");
  try {
    const result = await action();
    onStageChange?.(stepId, "succeeded");
    return result;
  } catch (error) {
    onStageChange?.(stepId, "failed");
    throw error;
  }
}

/**
 * Single-registration mutation responses are serialized without the per-role
 * OW-rank snapshot join (and profile-visibility check) the list endpoint
 * performs, so merge the fresh row into the cached list while preserving the
 * list-only enrichment fields instead of dropping them until the next refetch.
 */
function mergeRegistrationForCache(
  existing: AdminRegistration,
  fresh: AdminRegistration
): AdminRegistration {
  const previousOwRankByRole = new Map(
    existing.roles.map((role) => [role.role, role.ow_rank_value])
  );
  return {
    ...fresh,
    profiles_open: fresh.profiles_open ?? existing.profiles_open,
    roles: fresh.roles.map((role) => ({
      ...role,
      ow_rank_value: role.ow_rank_value ?? previousOwRankByRole.get(role.role) ?? null
    }))
  };
}

export function useBalancerMutations({
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
  balancerConfigData,
  draftConfig,
  isConfigDirty,
  onTournamentConfigSaved,
  activeVariant,
  onJobCreated,
  slotCodes,
  ratedDimension
}: UseBalancerMutationsOptions) {
  const t = useTranslations("balancerTool.page");
  const tImport = useTranslations("balancerTool.page.importErrors");
  const invalidateRegistrations = () =>
    queryClient.invalidateQueries({ queryKey: balancerQueryKeys.registrations(tournamentId) });

  /**
   * Merge a mutation response row into the cached registrations list instead
   * of blocking on a refetch of the whole (expensive) list endpoint. The
   * realtime `balancer.registrations_changed` echo still reconciles the list
   * in the background for every viewer.
   */
  const patchRegistrationInCache = (fresh: AdminRegistration) => {
    queryClient.setQueryData<AdminRegistration[]>(
      ["balancer-admin", "registrations", tournamentId],
      (current) =>
        current?.map((existing) =>
          existing.id === fresh.id ? mergeRegistrationForCache(existing, fresh) : existing
        )
    );
  };

  const updatePlayerMutation = useMutation({
    mutationFn: async ({
      playerId,
      payload
    }: {
      playerId: number;
      payload: BalancerPlayerUpdateInput;
    }) => {
      const cachedRegistrations = queryClient.getQueryData<AdminRegistration[]>([
        "balancer-admin",
        "registrations",
        tournamentId
      ]);
      const existingReg = cachedRegistrations?.find((r) => r.id === playerId);
      let registrationPatch: AdminRegistrationUpdateInput;
      try {
        registrationPatch = buildRegistrationUpdateFromPlayerPayload(
          payload,
          existingReg?.roles,
          ratedDimension
        );
      } catch (error) {
        // The global mutation toast shows the message as is, so word it for the reader.
        throw error instanceof RatedDimensionUnknownError
          ? new Error(t("errors.ratedDimensionUnknown"))
          : error;
      }
      let updated: AdminRegistration | null = null;
      if (Object.keys(registrationPatch).length > 0) {
        updated = await balancerAdminService.updateRegistration(playerId, registrationPatch);
      }
      if (payload.is_in_pool === true) {
        updated = await balancerAdminService.includeInBalancer(playerId);
      }
      return updated;
    },
    onSuccess: async (updated) => {
      setEditingPlayerId(null);
      if (updated) {
        patchRegistrationInCache(updated);
      } else {
        await invalidateRegistrations();
      }
      notify.success(t("toasts.registrationUpdated"));
    }
  });

  const setPlayerPoolMembershipMutation = useMutation({
    mutationFn: ({ playerId, isInPool }: { playerId: number; isInPool: boolean }) =>
      isInPool
        ? balancerAdminService.includeInBalancer(playerId)
        : balancerAdminService.setBalancerStatus(playerId, "excluded", "manual_exclusion"),
    onSuccess: (registration, variables) => {
      patchRegistrationInCache(registration);
      if (variables.isInPool) {
        notify.success(
          registration.balancer_status === "ready"
            ? t("toasts.registrationReady")
            : t("toasts.registrationIncomplete")
        );
      } else {
        notify.success(t("toasts.registrationExcluded"));
      }
    }
  });

  const setBalancerStatusMutation = useMutation({
    mutationFn: ({ playerId, balancerStatus }: { playerId: number; balancerStatus: string }) =>
      balancerAdminService.setBalancerStatus(playerId, balancerStatus),
    onSuccess: (registration) => {
      patchRegistrationInCache(registration);
      notify.success(t("toasts.statusUpdated"));
    }
  });

  const bulkPoolMembershipMutation = useMutation({
    mutationFn: async ({ playerIds, isInPool }: { playerIds: number[]; isInPool: boolean }) => {
      if (!tournamentId) throw new Error(t("errors.noTournament"));
      const result = isInPool
        ? await balancerAdminService.bulkAddToBalancer(tournamentId, playerIds)
        : await balancerAdminService.bulkSetBalancerStatus(tournamentId, {
            registration_ids: playerIds,
            balancer_status: "excluded",
            exclude_reason: "manual_exclusion"
          });
      return { ...result, isInPool };
    },
    onSuccess: (result) => {
      // The bulk endpoint returns counters only, so a per-row cache patch is
      // impossible; refetch the registrations list in the background instead.
      void invalidateRegistrations();
      notify.success(
        t(result.isInPool ? "toasts.bulkIncluded" : "toasts.bulkExcluded", { count: result.updated })
      );
    }
  });

  const bulkBalancerStatusMutation = useMutation({
    mutationFn: async ({
      playerIds,
      balancerStatus
    }: {
      playerIds: number[];
      balancerStatus: string;
    }) => {
      const registrations = await Promise.all(
        playerIds.map((playerId) =>
          balancerAdminService.setBalancerStatus(playerId, balancerStatus)
        )
      );
      return { updated: registrations.length, registrations };
    },
    onSuccess: (result) => {
      result.registrations.forEach(patchRegistrationInCache);
      notify.success(t("toasts.bulkStatusUpdated", { count: result.updated }));
    }
  });

  const invalidateTournamentExportQueries = async () => {
    if (!tournamentId) {
      return;
    }

    await Promise.all([
      queryClient.invalidateQueries({ queryKey: balancerQueryKeys.publicBalance(tournamentId) }),
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.tournament(tournamentId) }),
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.tournamentTeams(tournamentId) }),
      queryClient.invalidateQueries({
        queryKey: adminQueryKeys.tournamentStandings(tournamentId)
      }),
      queryClient.invalidateQueries({
        queryKey: adminQueryKeys.tournamentEncounters(tournamentId)
      }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.list() }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.standingsAll() }),
      queryClient.invalidateQueries({ queryKey: encounterQueryKeys.all() }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.standings(tournamentId) }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.encounters(tournamentId) }),
      ...(workspaceId != null
        ? [
            queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.standings(tournamentId, workspaceId) }),
            queryClient.invalidateQueries({
              queryKey: tournamentQueryKeys.encounters(tournamentId, workspaceId)
            })
          ]
        : [])
    ]);
  };

  const buildActiveBalanceSaveInput = (): BalanceSaveInput => {
    if (!tournamentId || !activeVariant) {
      throw new Error(t("errors.noBalance"));
    }

    if (activeVariant.payload.teams.length === 0) {
      throw new Error(t("errors.noTeams"));
    }

    const sanitizedDraftConfig = sanitizeBalancerConfig(draftConfig);
    const config =
      activeVariant.config ??
      (Object.keys(sanitizedDraftConfig).length > 0
        ? sanitizedDraftConfig
        : (balancerConfigData?.presets[selectedPreset] ?? balancerConfigData?.defaults)) ??
      null;

    return {
      config_json: config as Record<string, unknown> | null,
      result_json: activeVariant.payload
    };
  };

  const saveActiveBalance = async (): Promise<SavedBalance> => {
    if (!tournamentId) {
      throw new Error(t("errors.noTournament"));
    }

    return balancerAdminService.saveBalance(tournamentId, buildActiveBalanceSaveInput());
  };

  const applySavedBalanceVariant = (savedBalance: SavedBalance) => {
    const savedVariant = buildVariantFromSavedBalance(savedBalance);
    setVariants((current) => [savedVariant, ...current.filter((v) => v.source !== "saved")]);
    setActiveVariantId(savedVariant.id);
  };

  const runBalanceMutation = useMutation({
    mutationFn: async () => {
      if (!tournamentId) throw new Error(t("errors.noTournament"));
      if (!excludeInvalidPlayers && invalidPlayerStates.length > 0) {
        throw new Error(t("errors.unresolvedIssues"));
      }
      // The pool the server balances is the tournament's own, resolved by the
      // roster engine. The client only decides whether the run is allowed and
      // which config to send.
      const playersForBalance = excludeInvalidPlayers ? readyPlayers : poolPlayers;
      if (playersForBalance.length === 0) throw new Error(t("errors.noPlayers"));
      const sanitizedDraftConfig = sanitizeBalancerConfig(draftConfig);
      let config =
        Object.keys(sanitizedDraftConfig).length > 0
          ? sanitizedDraftConfig
          : (balancerConfigData?.presets[selectedPreset] ?? balancerConfigData?.defaults);
      if (config && isConfigDirty) {
        const savedConfig = await balancerAdminService.upsertTournamentConfig(tournamentId, {
          config_json: sanitizeBalancerConfig(config) as Record<string, unknown>
        });
        config = savedConfig.config_json as BalancerConfig;
        onTournamentConfigSaved(config);
      }
      const skipped = excludeInvalidPlayers ? invalidPlayerStates.length : 0;
      return {
        job: await balancerService.createTournamentBalanceJob({
          tournament_id: tournamentId,
          config_overrides: (config as BalancerConfig | undefined) ?? null
        }),
        skipped,
        config: config as BalancerConfig | undefined
      };
    },
    onSuccess: ({ job, skipped, config }) => {
      // Immediate optimistic feedback; subsequent status (running/progress/
      // succeeded/failed) and the resulting variants arrive via the realtime
      // balancer topic, so the initiator and every other viewer stay in sync
      // through a single handler (see useBalancerRealtime).
      dispatchJob({
        type: "update",
        status: job.status,
        message: t("job.created"),
        progress: 0
      });
      onJobCreated(job.job_id, { skipped, config });
    }
  });

  const saveBalanceMutation = useMutation({
    mutationFn: async () => {
      return saveActiveBalance();
    },
    onSuccess: async (savedBalance) => {
      await queryClient.invalidateQueries({
        queryKey: balancerQueryKeys.publicBalance(tournamentId)
      });
      applySavedBalanceVariant(savedBalance);
      notify.success(t("toasts.balanceSaved"));
    }
  });

  const exportToTournamentMutation = useMutation({
    mutationFn: async ({
      onStageChange
    }: ExportToTournamentVariables = {}): Promise<ExportToTournamentResult> => {
      await runReportedStage("validate", onStageChange, async () => {
        buildActiveBalanceSaveInput();
      });

      const savedBalance = await runReportedStage("save", onStageChange, saveActiveBalance);
      const exportResult = await runReportedStage("export", onStageChange, () =>
        balancerAdminService.exportBalance(savedBalance.id)
      );

      await runReportedStage("refresh", onStageChange, invalidateTournamentExportQueries);

      return { savedBalance, exportResult };
    },
    onSuccess: ({ savedBalance, exportResult }) => {
      applySavedBalanceVariant(savedBalance);
      const showResult = exportResult.advisories.length ? notify.warning : notify.success;
      showResult(t("toasts.teamsExported"), {
        description: [
          t("toasts.teamsCreated", { count: exportResult.imported_teams }),
          ...exportResult.advisories
        ].join("\n"),
        duration: exportResult.advisories.length ? Infinity : undefined,
        classNames: { description: "whitespace-pre-line" }
      });
    }
  });

  // Rank-only correction: the teams already in the tournament keep their rosters
  // (and whatever bracket references them) — only the numbers are refreshed from
  // the saved balance. Save first if the editor holds newer ranks.
  const exportRanksMutation = useMutation({
    mutationFn: async (balanceId: number) => {
      const result = await balancerAdminService.exportBalanceRanks(balanceId);
      await invalidateTournamentExportQueries();
      return result;
    },
    onSuccess: (result) => {
      notify.success(t("toasts.ranksExported"), {
        description: t("toasts.ranksUpdated", { count: result.updated_players })
      });
    },
    onError: (error) => notify.apiError(error, { title: t("toasts.ranksExportFailed") })
  });

  // Import loads the file as another variant — creating tournament teams stays an
  // explicit Save / Export to Tournament step, same as for a generated balance.
  const importBalanceMutation = useMutation({
    mutationFn: async ({ file, onStageChange }: ImportBalanceVariables) => {
      if (!tournamentId) throw new Error(t("errors.noTournament"));
      if (!slotCodes) throw new Error(t("errors.rolesLoading"));

      const payload = await runReportedStage("read", onStageChange, async () =>
        parseImportedBalancePayload(await file.text(), slotCodes, tImport)
      );

      return runReportedStage("load", onStageChange, async () => {
        const variant: BalanceVariant = {
          id: `imported-${Date.now()}`,
          label: `Imported ${file.name}`,
          labelSource: { kind: "imported", fileName: file.name },
          payload,
          source: "imported"
        };
        setVariants((current) => [...current, variant]);
        setActiveVariantId(variant.id);
        return { variant, teamCount: payload.teams.length };
      });
    },
    onSuccess: ({ teamCount }) => {
      notify.success(t("toasts.balanceImported"), {
        description: t("toasts.balanceImportedDescription", { count: teamCount })
      });
    }
  });

  return {
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
  };
}
