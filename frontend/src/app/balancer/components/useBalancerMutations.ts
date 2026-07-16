"use client";

import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import type React from "react";
import type { JobAction } from "./useBalancerJob";
import { sanitizeBalancerConfig } from "./balancer-config-helpers";
import {
  buildBalancerInput,
  buildRankHistoryFromAutofillPreview,
  buildVariantFromSavedBalance,
  type BalanceVariant
} from "./workspace-helpers";
import type { PlayerValidationState } from "./balancer-page-helpers";
import balancerAdminService from "@/services/balancer-admin.service";
import balancerService from "@/services/balancer.service";
import type {
  BalancerApplication,
  AdminRegistration,
  AdminRegistrationUpdateInput,
  BalanceExportResponse,
  BalancerPlayerRecord,
  BalancerPlayerUpdateInput,
  BalancerRoleCode,
  BalanceSaveInput,
  SavedBalance
} from "@/types/balancer-admin.types";
import type { BalancerConfig, BalancerConfigResponse } from "@/types/balancer.types";
import { notify } from "@/lib/notify";

type UseBalancerMutationsOptions = {
  tournamentId: number | null;
  workspaceId: number | null;
  queryClient: QueryClient;
  dispatchJob: React.Dispatch<JobAction>;
  setSelectedPlayerId: (id: number | null) => void;
  setPendingRankHistory: (history: Partial<Record<BalancerRoleCode, number>> | null) => void;
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

type ImportTeamsVariables = {
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
  balancerConfigData,
  draftConfig,
  isConfigDirty,
  onTournamentConfigSaved,
  activeVariant,
  onJobCreated
}: UseBalancerMutationsOptions) {
  const invalidateRegistrations = () =>
    queryClient.invalidateQueries({ queryKey: ["balancer-admin", "registrations", tournamentId] });

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

  const addPlayerMutation = useMutation({
    mutationFn: async (application: BalancerApplication) => {
      if (!tournamentId) throw new Error("Select a tournament first");
      return balancerAdminService.setRegistrationExclusion(application.id, {
        exclude_from_balancer: false,
        exclude_reason: null
      });
    },
    onSuccess: async (registration) => {
      setSelectedPlayerId(registration.id);
      patchRegistrationInCache(registration);
      notify.success("Registration included in balancer");
      // Autofill ranks for the just-included player using the balancer-first priority chain
      // (previous balances → analytics → OW), reusing the backend's autofill logic.
      if (tournamentId) {
        balancerAdminService
          .previewRegistrationRankAutofill(tournamentId, {
            registration_ids: [registration.id],
            mode: "balancer_first"
          })
          .then((preview) =>
            setPendingRankHistory(buildRankHistoryFromAutofillPreview(preview, registration.id))
          )
          .catch(() => setPendingRankHistory(null));
      } else {
        setPendingRankHistory(null);
      }
    }
  });

  const updatePlayerMutation = useMutation({
    mutationFn: async ({
      playerId,
      payload
    }: {
      playerId: number;
      payload: BalancerPlayerUpdateInput;
    }) => {
      const registrationPatch: AdminRegistrationUpdateInput = {};

      if (payload.role_entries_json !== undefined) {
        const cachedRegistrations = queryClient.getQueryData<AdminRegistration[]>([
          "balancer-admin",
          "registrations",
          tournamentId
        ]);
        const existingReg = cachedRegistrations?.find((r) => r.id === playerId);
        const existingRolesMap = new Map(
          existingReg?.roles?.map((r) => [r.role, r.top_heroes ?? []]) ?? []
        );

        const sortedEntries = [...(payload.role_entries_json ?? [])].sort(
          (left, right) => left.priority - right.priority
        );
        registrationPatch.roles = sortedEntries.map((entry, index) => {
          const topHeroes = existingRolesMap.get(entry.role) ?? [];
          return {
            role: entry.role,
            subrole: entry.subtype,
            priority: entry.priority,
            is_primary: payload.is_flex ? true : index === 0,
            rank_value: entry.rank_value,
            is_active: entry.is_active,
            ...(topHeroes.length > 0 ? { top_heroes: topHeroes } : {})
          };
        });
      }

      if (payload.admin_notes !== undefined) {
        registrationPatch.admin_notes = payload.admin_notes;
      }
      if (payload.registration_status != null) {
        registrationPatch.status = payload.registration_status;
      }
      if (payload.registration_balancer_status != null) {
        registrationPatch.balancer_status = payload.registration_balancer_status;
      }

      if (payload.is_in_pool !== undefined) {
        registrationPatch.exclude_from_balancer = !(payload.is_in_pool ?? true);
        registrationPatch.exclude_reason = payload.is_in_pool ? null : "manual_exclusion";
      }

      let updated: AdminRegistration | null = null;
      if (Object.keys(registrationPatch).length > 0) {
        updated = await balancerAdminService.updateRegistration(playerId, registrationPatch);
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
      notify.success("Registration updated");
    }
  });

  const removePlayerMutation = useMutation({
    mutationFn: (playerId: number) =>
      balancerAdminService.setRegistrationExclusion(playerId, {
        exclude_from_balancer: true,
        exclude_reason: "manual_exclusion"
      }),
    onSuccess: (registration) => {
      patchRegistrationInCache(registration);
      setEditingPlayerId(null);
      notify.success("Registration excluded from balancer");
    }
  });

  const setPlayerPoolMembershipMutation = useMutation({
    mutationFn: ({ playerId, isInPool }: { playerId: number; isInPool: boolean }) =>
      balancerAdminService.setRegistrationExclusion(playerId, {
        exclude_from_balancer: !isInPool,
        exclude_reason: isInPool ? null : "manual_exclusion"
      }),
    onSuccess: (registration, variables) => {
      patchRegistrationInCache(registration);
      notify.success(
        variables.isInPool
          ? "Registration included in balancer"
          : "Registration excluded from balancer"
      );
    }
  });

  const setBalancerStatusMutation = useMutation({
    mutationFn: ({ playerId, balancerStatus }: { playerId: number; balancerStatus: string }) =>
      balancerAdminService.setBalancerStatus(playerId, balancerStatus),
    onSuccess: (registration) => {
      patchRegistrationInCache(registration);
      notify.success("Balancer status updated");
    }
  });

  const bulkPoolMembershipMutation = useMutation({
    mutationFn: async ({ playerIds, isInPool }: { playerIds: number[]; isInPool: boolean }) => {
      if (!tournamentId) throw new Error("Select a tournament first");
      const result = await balancerAdminService.bulkSetExclusion(tournamentId, {
        registration_ids: playerIds,
        exclude_from_balancer: !isInPool,
        exclude_reason: isInPool ? null : "manual_exclusion"
      });
      return { ...result, isInPool };
    },
    onSuccess: (result) => {
      // The bulk endpoint returns counters only, so a per-row cache patch is
      // impossible; refetch the registrations list in the background instead.
      void invalidateRegistrations();
      notify.success(
        `${result.updated} registration${result.updated !== 1 ? "s" : ""} ${result.isInPool ? "included" : "excluded"}`
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
      notify.success(
        `${result.updated} balancer status${result.updated !== 1 ? "es" : ""} updated`
      );
    }
  });

  const invalidateTournamentExportQueries = async () => {
    if (!tournamentId) {
      return;
    }

    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["balancer-public", "balance", tournamentId] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "tournament", tournamentId] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "tournament", tournamentId, "teams"] }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "tournament", tournamentId, "standings"]
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "tournament", tournamentId, "encounters"]
      }),
      queryClient.invalidateQueries({ queryKey: ["tournaments"] }),
      queryClient.invalidateQueries({ queryKey: ["teams"] }),
      queryClient.invalidateQueries({ queryKey: ["standings"] }),
      queryClient.invalidateQueries({ queryKey: ["encounters"] }),
      queryClient.invalidateQueries({ queryKey: ["standings", tournamentId] }),
      queryClient.invalidateQueries({ queryKey: ["encounters", "tournament", tournamentId] }),
      ...(workspaceId != null
        ? [
            queryClient.invalidateQueries({ queryKey: ["standings", tournamentId, workspaceId] }),
            queryClient.invalidateQueries({
              queryKey: ["encounters", "tournament", tournamentId, workspaceId]
            })
          ]
        : [])
    ]);
  };

  const buildActiveBalanceSaveInput = (): BalanceSaveInput => {
    if (!tournamentId || !activeVariant) {
      throw new Error("No balance selected");
    }

    if (activeVariant.payload.teams.length === 0) {
      throw new Error("Selected balance does not contain teams");
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
      throw new Error("Select a tournament first");
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
      if (!tournamentId) throw new Error("Select a tournament first");
      if (!excludeInvalidPlayers && invalidPlayerStates.length > 0) {
        throw new Error("Resolve all pool player validation issues before balancing");
      }
      const playersForBalance = excludeInvalidPlayers ? readyPlayers : poolPlayers;
      if (playersForBalance.length === 0) throw new Error("No players available to balance");
      const input = buildBalancerInput(playersForBalance);
      const file = new File([JSON.stringify(input)], `balancer-${tournamentId}.json`, {
        type: "application/json"
      });
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
        job: await balancerService.createBalanceJob(
          file,
          config as BalancerConfig | undefined,
          tournamentId
        ),
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
        message: "Balance job created",
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
        queryKey: ["balancer-public", "balance", tournamentId]
      });
      applySavedBalanceVariant(savedBalance);
      notify.success("Final balance saved");
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
      notify.success("Teams exported to tournament", {
        description: `${exportResult.imported_teams} teams created.`
      });
    }
  });

  const importTeamsMutation = useMutation({
    mutationFn: async ({ file, onStageChange }: ImportTeamsVariables) => {
      if (!tournamentId) throw new Error("Select a tournament first");

      await runReportedStage("read", onStageChange, async () => {
        JSON.parse(await file.text());
      });

      const result = await runReportedStage("import", onStageChange, () =>
        balancerAdminService.importTeamsFromJson(tournamentId, file)
      );

      await runReportedStage("refresh", onStageChange, invalidateTournamentExportQueries);

      return result;
    },
    onSuccess: (result) => {
      notify.success("Teams imported", { description: `${result.imported_teams} teams created.` });
    }
  });

  return {
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
  };
}
