"use client";

import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import type React from "react";
import type { JobAction } from "./useBalancerJob";
import { sanitizeBalancerConfig } from "./balancer-config-helpers";
import {
  buildBalancerInput,
  buildVariantFromSavedBalance,
  convertBalanceResponseToInternalPayload,
  fetchPlayerRankHistory,
  type BalanceVariant
} from "./workspace-helpers";
import { createVariantLabel } from "./balancer-page-helpers";
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
import type {
  BalanceJobResult,
  BalancerConfig,
  BalancerConfigResponse
} from "@/types/balancer.types";
import type { useToast } from "@/hooks/use-toast";

type UseBalancerMutationsOptions = {
  tournamentId: number | null;
  workspaceId: number | null;
  toast: ReturnType<typeof useToast>["toast"];
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

export function useBalancerMutations({
  tournamentId,
  workspaceId,
  toast,
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
  activeVariant
}: UseBalancerMutationsOptions) {
  const addPlayerMutation = useMutation({
    mutationFn: async (application: BalancerApplication) => {
      if (!tournamentId) throw new Error("Select a tournament first");
      return balancerAdminService.setRegistrationExclusion(application.id, {
        exclude_from_balancer: false,
        exclude_reason: null
      });
    },
    onSuccess: async (registration, application) => {
      setSelectedPlayerId(registration.id);
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registrations", tournamentId]
      });
      toast({ title: "Registration included in balancer" });
      fetchPlayerRankHistory(application.battle_tag)
        .then((history) => setPendingRankHistory(history))
        .catch(() => setPendingRankHistory(null));
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to include registration",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const invalidateRegistrations = () =>
    queryClient.invalidateQueries({ queryKey: ["balancer-admin", "registrations", tournamentId] });

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

      if (Object.keys(registrationPatch).length > 0) {
        await balancerAdminService.updateRegistration(playerId, registrationPatch);
      }
      if (payload.is_in_pool === undefined) {
        return null;
      }
      return balancerAdminService.setRegistrationExclusion(playerId, {
        exclude_from_balancer: !(payload.is_in_pool ?? true),
        exclude_reason: payload.is_in_pool ? null : "manual_exclusion"
      });
    },
    onSuccess: async () => {
      setEditingPlayerId(null);
      await invalidateRegistrations();
      toast({ title: "Registration updated" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to update registration",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const removePlayerMutation = useMutation({
    mutationFn: (playerId: number) =>
      balancerAdminService.setRegistrationExclusion(playerId, {
        exclude_from_balancer: true,
        exclude_reason: "manual_exclusion"
      }),
    onSuccess: async () => {
      await invalidateRegistrations();
      setEditingPlayerId(null);
      toast({ title: "Registration excluded from balancer" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to exclude registration",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const setPlayerPoolMembershipMutation = useMutation({
    mutationFn: ({ playerId, isInPool }: { playerId: number; isInPool: boolean }) =>
      balancerAdminService.setRegistrationExclusion(playerId, {
        exclude_from_balancer: !isInPool,
        exclude_reason: isInPool ? null : "manual_exclusion"
      }),
    onSuccess: async (_, variables) => {
      await invalidateRegistrations();
      toast({
        title: variables.isInPool
          ? "Registration included in balancer"
          : "Registration excluded from balancer"
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to update pool membership",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const setBalancerStatusMutation = useMutation({
    mutationFn: ({ playerId, balancerStatus }: { playerId: number; balancerStatus: string }) =>
      balancerAdminService.setBalancerStatus(playerId, balancerStatus),
    onSuccess: async () => {
      await invalidateRegistrations();
      toast({ title: "Balancer status updated" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to update balancer status",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const bulkPoolMembershipMutation = useMutation({
    mutationFn: async ({ playerIds, isInPool }: { playerIds: number[]; isInPool: boolean }) => {
      await Promise.all(
        playerIds.map((playerId) =>
          balancerAdminService.setRegistrationExclusion(playerId, {
            exclude_from_balancer: !isInPool,
            exclude_reason: isInPool ? null : "manual_exclusion"
          })
        )
      );
      return { updated: playerIds.length, isInPool };
    },
    onSuccess: async (result) => {
      await invalidateRegistrations();
      toast({
        title: `${result.updated} registration${result.updated !== 1 ? "s" : ""} ${result.isInPool ? "included" : "excluded"}`
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Bulk pool update failed",
        description: error.message,
        variant: "destructive"
      });
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
      await Promise.all(
        playerIds.map((playerId) =>
          balancerAdminService.setBalancerStatus(playerId, balancerStatus)
        )
      );
      return { updated: playerIds.length };
    },
    onSuccess: async (result) => {
      await invalidateRegistrations();
      toast({
        title: `${result.updated} balancer status${result.updated !== 1 ? "es" : ""} updated`
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Bulk status update failed",
        description: error.message,
        variant: "destructive"
      });
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
        job: await balancerService.createBalanceJob(file, config as BalancerConfig | undefined),
        skipped,
        config: config as BalancerConfig | undefined
      };
    },
    onSuccess: ({ job, skipped, config }) => {
      dispatchJob({
        type: "update",
        status: job.status,
        message: "Balance job created",
        progress: 0
      });
      void balancerService.streamBalanceJob(job.job_id, {
        onEvent: async (event) => {
          dispatchJob({
            type: "update",
            status: event.status,
            message: event.message,
            progress: typeof event.progress?.percent === "number" ? event.progress.percent : null
          });
          if (event.status === "succeeded") {
            try {
              const result = (await balancerService.getBalanceJobResult(
                job.job_id
              )) as BalanceJobResult;
              // Pre-generate stable IDs outside the updater so that setActiveVariantId
              // and setVariants always agree on the same ID regardless of how many times
              // React invokes the updater (concurrent mode may call it multiple times).
              const timestamp = Date.now();
              const newIds = result.variants.map((_, i) => `generated-${timestamp}-${i}`);
              setVariants((current) => {
                const next = [...current];
                const generatedCount = next.filter((v) => v.source === "generated").length;
                result.variants.forEach((variant, batchIndex) => {
                  const payload = convertBalanceResponseToInternalPayload(variant);
                  next.push({
                    id: newIds[batchIndex],
                    label: createVariantLabel(generatedCount + batchIndex + 1),
                    payload,
                    source: "generated",
                    config: config ?? null,
                    skippedCount: batchIndex === 0 && skipped > 0 ? skipped : undefined
                  });
                });
                return next;
              });
              const latestId = newIds[newIds.length - 1];
              if (latestId) setActiveVariantId(latestId);
              dispatchJob({ type: "clear" });
              toast({ title: "Balance completed" });
            } catch (error) {
              const message =
                error instanceof Error ? error.message : "Failed to fetch balance result";
              dispatchJob({ type: "update", status: "failed", message, progress: null });
              toast({ title: "Balance failed", description: message, variant: "destructive" });
            }
          }
          if (event.status === "failed") {
            toast({ title: "Balance failed", description: event.message, variant: "destructive" });
          }
        },
        onError: (message) => {
          dispatchJob({ type: "update", status: "failed", message, progress: null });
        }
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to run balancer",
        description: error.message,
        variant: "destructive"
      });
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
      toast({ title: "Final balance saved" });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to save balance",
        description: error.message,
        variant: "destructive"
      });
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
      toast({
        title: "Teams exported to tournament",
        description: `${exportResult.imported_teams} teams created.`
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to export to tournament",
        description: error.message,
        variant: "destructive"
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
      toast({ title: "Teams imported", description: `${result.imported_teams} teams created.` });
    },
    onError: (error: Error) => {
      toast({
        title: "Failed to import teams",
        description: error.message,
        variant: "destructive"
      });
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
