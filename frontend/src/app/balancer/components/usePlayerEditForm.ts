"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Cookies from "js-cookie";

import {
  fetchPlayerRankHistoryPreview,
  type PlayerRankHistoryPreview,
  type PlayerRankHistoryPreviewEntry
} from "@/components/balancer/workspace-helpers";
import { useCurrentWorkspaceId, useDivisionGrid, useDivisionGridVersion } from "@/hooks/useCurrentWorkspace";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import {
  getDivisionLabel,
  resolveDivisionFromRank as resolveDivisionFromRankInGrid,
  resolveRankFromDivision as resolveRankFromDivisionInGrid
} from "@/lib/divisions/grid";
import adminService from "@/services/admin.service";
import type {
  AdminRegistration,
  BalancerPlayerRecord,
  BalancerPlayerRoleEntry,
  BalancerPlayerUpdateInput,
  BalancerRoleCode
} from "@/types/balancer-admin.types";

import {
  MULTIPLE_WORKSPACES_COOKIE,
  ROLE_OPTIONS,
  applyHistoryPreviewToRoleEntries,
  applyHistoryToSelectedRoles,
  normalizeRoleEntries
} from "./playerEditSheet.model";

/** The "Load from history" preview and the controls that drive it. */
export interface PlayerRankHistoryState {
  /** Whether the organizer has asked for a preview at all. */
  requested: boolean;
  preview: PlayerRankHistoryPreview | null;
  loading: boolean;
  error: string | null;
  /** `current`, `all`, or a workspace id as a string. */
  workspaceValue: string;
  load: () => Promise<void>;
  changeWorkspace: (value: string) => Promise<void>;
  dismiss: () => void;
  /** Writes the previewed ranks onto the roles the player already has. */
  apply: () => void;
}

interface UsePlayerEditFormInput {
  player: BalancerPlayerRecord;
  registration: AdminRegistration | null;
  /** Ranks pre-resolved by the caller (the quick-edit flow), applied on open. */
  rankHistory: Partial<Record<BalancerRoleCode, number>> | null;
  /** Sub-roles are only worth fetching while the sheet is on screen. */
  open: boolean;
  onSave: (playerId: number, payload: BalancerPlayerUpdateInput) => void;
}

/**
 * Everything the player sheet edits: the role rows, the flags and notes, the
 * registration statuses, and the three ways those get written back.
 */
export function usePlayerEditForm({
  player,
  registration,
  rankHistory,
  open,
  onSave
}: UsePlayerEditFormInput) {
  const divisionGrid = useDivisionGrid();
  const divisionGridVersion = useDivisionGridVersion();
  const workspaceId = useCurrentWorkspaceId();

  const { data: subRoles } = useQuery({
    queryKey: adminQueryKeys.playerSubRoles(workspaceId),
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: Boolean(workspaceId && open)
  });

  const subtypeOptions = useMemo(() => {
    const options: Record<BalancerRoleCode, Array<{ value: string; label: string }>> = {
      tank: [],
      damage: [],
      support: []
    };

    if (subRoles) {
      for (const sr of subRoles) {
        const roleKey = sr.role as BalancerRoleCode;
        if (options[roleKey]) {
          options[roleKey].push({
            value: sr.slug,
            label: sr.label
          });
        }
      }
    }
    return options;
  }, [subRoles]);

  const resolveDivision = (rankValue: number | null) =>
    resolveDivisionFromRankInGrid(divisionGrid, rankValue);
  const resolveRankFromDivision = (divisionNumber: number | null) =>
    resolveRankFromDivisionInGrid(divisionGrid, divisionNumber);
  const getDivisionName = (divisionNumber: number | null) =>
    getDivisionLabel(divisionGrid, divisionNumber);

  // Normalised division name: always look up in the workspace (target) grid.
  const getHistoryDivisionName = (divisionNumber: number | null) =>
    getDivisionLabel(divisionGrid, divisionNumber);

  // Original division name: look up in the source tournament's own grid first,
  // then fall back to the workspace grid.
  const getOriginalDivisionName = (
    divisionNumber: number | null,
    entry: PlayerRankHistoryPreviewEntry
  ) => {
    if (divisionNumber == null) return null;
    if (entry.tournament_grid_version) {
      const tierName = getDivisionLabel(entry.tournament_grid_version, divisionNumber);
      if (tierName) return tierName;
    }
    return getDivisionLabel(divisionGrid, divisionNumber);
  };

  const [roleEntries, setRoleEntries] = useState<BalancerPlayerRoleEntry[]>(
    normalizeRoleEntries(player.role_entries_json)
  );
  const [isFlex, setIsFlex] = useState(player.is_flex);
  const [notes, setNotes] = useState(player.admin_notes ?? "");
  const [registrationStatus, setRegistrationStatus] = useState(registration?.status ?? "approved");
  const [registrationBalancerStatus, setRegistrationBalancerStatus] = useState(
    registration?.balancer_status ?? "not_in_balancer"
  );
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyPreview, setHistoryPreview] = useState<PlayerRankHistoryPreview | null>(null);
  const [historyPreviewRequested, setHistoryPreviewRequested] = useState(false);
  const [historyLoadError, setHistoryLoadError] = useState<string | null>(null);
  const [pinToTournament, setPinToTournament] = useState(false);

  const [historyWorkspaceValue, setHistoryWorkspaceValue] = useState<string>(() => {
    const saved = Cookies.get(MULTIPLE_WORKSPACES_COOKIE);
    return saved || "current";
  });

  const getHistoryWorkspaceIdParam = (val: string) => {
    if (val === "all") return null;
    if (val === "current") return undefined;
    return Number(val);
  };

  useEffect(() => {
    const normalized = normalizeRoleEntries(player.role_entries_json);
    setIsFlex(player.is_flex);
    setNotes(player.admin_notes ?? "");
    setRegistrationStatus(registration?.status ?? "approved");
    setRegistrationBalancerStatus(registration?.balancer_status ?? "not_in_balancer");
    setHistoryPreview(null);
    setHistoryPreviewRequested(false);
    setHistoryLoadError(null);
    setPinToTournament(false);
    setRoleEntries(applyHistoryToSelectedRoles(normalized, rankHistory, resolveDivision));
  }, [player, registration, rankHistory, divisionGrid]);

  const readHistory = async (workspaceValue: string) => {
    setLoadingHistory(true);
    setHistoryLoadError(null);
    try {
      const preview = await fetchPlayerRankHistoryPreview(
        player.battle_tag,
        divisionGridVersion,
        divisionGrid,
        getHistoryWorkspaceIdParam(workspaceValue),
        workspaceId
      );
      setHistoryPreview(preview);
    } catch (error) {
      setHistoryPreview(null);
      setHistoryLoadError(
        error instanceof Error ? error.message : "Failed to load player history."
      );
    } finally {
      setLoadingHistory(false);
    }
  };

  const dismissHistoryPreview = () => {
    setHistoryPreviewRequested(false);
    setHistoryPreview(null);
    setHistoryLoadError(null);
  };

  const history: PlayerRankHistoryState = {
    requested: historyPreviewRequested,
    preview: historyPreview,
    loading: loadingHistory,
    error: historyLoadError,
    workspaceValue: historyWorkspaceValue,
    load: async () => {
      setHistoryPreviewRequested(true);
      await readHistory(historyWorkspaceValue);
    },
    changeWorkspace: async (value: string) => {
      setHistoryWorkspaceValue(value);
      Cookies.set(MULTIPLE_WORKSPACES_COOKIE, value, { path: "/", sameSite: "lax" });
      if (historyPreviewRequested) {
        await readHistory(value);
      }
    },
    dismiss: dismissHistoryPreview,
    apply: () => {
      setRoleEntries(
        applyHistoryPreviewToRoleEntries(roleEntries, historyPreview, resolveRankFromDivision)
      );
      dismissHistoryPreview();
    }
  };

  // Reordering IS the priority: the array position is what the balancer reads,
  // so `priority` is renumbered from the new order rather than edited directly.
  const reorderRoles = (next: BalancerPlayerRoleEntry[]) => {
    setRoleEntries(next.map((entry, index) => ({ ...entry, priority: index + 1 })));
  };

  const addRole = () => {
    const availableRole = ROLE_OPTIONS.find(
      (option) => !roleEntries.some((entry) => entry.role === option.value)
    );
    if (!availableRole) return;

    setRoleEntries([
      ...roleEntries,
      {
        role: availableRole.value,
        subtype: null,
        priority: roleEntries.length + 1,
        division_number: null,
        rank_value: null,
        // Declared on by the organizer's action, but not in play until it is
        // ranked — which is the server's call, not ours.
        is_active: false,
        is_declared_active: true,
        ow_rank_value: null
      }
    ]);
  };

  const updateEntry = (index: number, nextEntry: BalancerPlayerRoleEntry) => {
    setRoleEntries(
      normalizeRoleEntries(
        roleEntries.map((entry, currentIndex) => (currentIndex === index ? nextEntry : entry))
      )
    );
  };

  const removeEntry = (index: number) => {
    setRoleEntries(
      normalizeRoleEntries(roleEntries.filter((_, currentIndex) => currentIndex !== index))
    );
  };

  /** The fields every write sends, before the per-action extras. */
  const basePayload = (): BalancerPlayerUpdateInput => ({
    role_entries_json: normalizeRoleEntries(roleEntries),
    is_flex: isFlex,
    admin_notes: notes || null,
    registration_status:
      registration && registrationStatus !== registration.status ? registrationStatus : null
  });

  /** Only sent when it actually changed — the current value may be a
   *  server-computed "ready"/"incomplete" the backend rejects as a literal
   *  write (see AUTO_MANAGED_BALANCER_STATUSES). */
  const balancerStatusOverride = () =>
    registration && registrationBalancerStatus !== registration.balancer_status
      ? registrationBalancerStatus
      : null;

  const handleSave = () => {
    onSave(player.id, {
      ...basePayload(),
      registration_balancer_status: balancerStatusOverride(),
      ...(pinToTournament ? { pin: true } : {})
    });
  };

  // Saves every pending edit (roles, notes, registration status) exactly like
  // handleSave, then recomputes balancer_status from those roles via
  // add_to_balancer (is_in_pool: true's server-side effect -- see
  // updatePlayerMutation) instead of writing a literal override. That
  // recompute always runs last and wins, so no explicit balancer-status
  // override is sent here -- it would just be overwritten.
  const handleMoveToReady = () => {
    onSave(player.id, {
      ...basePayload(),
      is_in_pool: true,
      ...(pinToTournament ? { pin: true } : {})
    });
  };

  const handleClearPin = () => {
    onSave(player.id, {
      ...basePayload(),
      registration_balancer_status: balancerStatusOverride(),
      clear_pin: true
    });
  };

  return {
    roleEntries,
    isFlex,
    setIsFlex,
    notes,
    setNotes,
    registrationStatus,
    setRegistrationStatus,
    registrationBalancerStatus,
    setRegistrationBalancerStatus,
    pinToTournament,
    setPinToTournament,
    subtypeOptions,
    resolveDivision,
    getDivisionName,
    getHistoryDivisionName,
    getOriginalDivisionName,
    history,
    addRole,
    updateEntry,
    removeEntry,
    reorderRoles,
    handleSave,
    handleMoveToReady,
    handleClearPin
  };
}
