"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Cookies from "js-cookie";
import { useTranslations } from "next-intl";

import {
  fetchPlayerRankHistoryPreview,
  type PlayerRankHistoryPreview,
  type PlayerRankHistoryPreviewEntry
} from "@/components/balancer/workspace-helpers";
import { ratedDimension, registrationRoles, showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";
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
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

import {
  MULTIPLE_WORKSPACES_COOKIE,
  applyHistoryPreviewToRoleEntries,
  normalizeRoleEntries
} from "./playerEditSheet.model";

/** Until the tournament's grid resolves: the sheet stays closed on an empty grid. */
const EMPTY_GRID: DivisionGrid = { tiers: [] };

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
  discipline: string | undefined;
  /** The owner game's role dictionary: the roles a player may be given. `null` while it loads. */
  ontology: RoleOntology | null;
  /** The tournament's grid — its pin, else the workspace default — the page resolves every rank in; `null` while unresolved. */
  divisionGridVersion: DivisionGridVersion | null;
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
  discipline,
  ontology,
  divisionGridVersion,
  open,
  onSave
}: UsePlayerEditFormInput) {
  const t = useTranslations("balancerTool.playerEdit.history");
  const divisionGrid: DivisionGrid = divisionGridVersion ?? EMPTY_GRID;
  const workspaceId = useCurrentWorkspaceId();

  const { data: subRoles } = useQuery({
    queryKey: adminQueryKeys.playerSubRoles(workspaceId, discipline),
    queryFn: ({ signal }) => adminService.getPlayerSubRoles({ workspace_id: workspaceId!, discipline: discipline! }, signal),
    enabled: Boolean(workspaceId && open && discipline)
  });

  const subtypeOptions = useMemo(() => {
    const options: Record<BalancerRoleCode, Array<{ value: string; label: string }>> = {};
    for (const sr of subRoles ?? []) {
      (options[sr.role] ??= []).push({ value: sr.slug, label: sr.label });
    }
    return options;
  }, [subRoles]);

  const resolveDivision = (rankValue: number | null) =>
    resolveDivisionFromRankInGrid(divisionGrid, rankValue);
  const resolveRankFromDivision = (divisionNumber: number | null) =>
    resolveRankFromDivisionInGrid(divisionGrid, divisionNumber);
  const getDivisionName = (divisionNumber: number | null) =>
    getDivisionLabel(divisionGrid, divisionNumber);

  // Original division name: look up in the source tournament's own grid first,
  // then fall back to this tournament's grid.
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

  const [editedEntries, setRoleEntries] = useState<BalancerPlayerRoleEntry[]>(
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

  // The roles the owner game offers a registrant, in declared order; "Add role" takes the first one this player lacks.
  const selectableRoleCodes = useMemo(
    () => registrationRoles(ontology).map((role) => role.code),
    [ontology]
  );
  // A one-role game edits its sole role's rank alone, with no switch to turn it off: its entry is always declared on,
  // keeping its stored rank and sub-role, and a registration without one gets a fresh one. It leads the list, so the
  // write keeps it primary. Every other stored entry (a role the module retired, with its character preferences)
  // follows in its stored order, otherwise unchanged: a save replaces the registration's roles.
  const soleRole = showsRoles(ontology) ? null : (selectableRoleCodes[0] ?? null);
  const roleEntries = useMemo<BalancerPlayerRoleEntry[]>(() => {
    if (soleRole === null) return editedEntries;
    const stored = editedEntries.find((entry) => entry.role === soleRole);
    const sole: BalancerPlayerRoleEntry = {
      ...(stored ?? {
        role: soleRole,
        subtype: null,
        priority: 1,
        division_number: null,
        rank_value: null,
        is_active: false,
        ow_rank_value: null
      }),
      is_declared_active: true
    };
    return [sole, ...editedEntries.filter((entry) => entry !== stored)].map((entry, index) => ({
      ...entry,
      priority: index + 1
    }));
  }, [editedEntries, soleRole]);
  const addableRole =
    selectableRoleCodes.find((code) => !roleEntries.some((entry) => entry.role === code)) ?? null;

  const [historyWorkspaceValue, setHistoryWorkspaceValue] = useState<string>(() => {
    const saved = Cookies.get(MULTIPLE_WORKSPACES_COOKIE);
    return saved || "current";
  });

  const getHistoryWorkspaceIdParam = (val: string) => {
    if (val === "all") return null;
    if (val === "current") return undefined;
    return Number(val);
  };

  // Another player (or a refetched one) starts the form over. Adjusted during
  // render, so the previous player's values are never painted first.
  const [formSource, setFormSource] = useState({ player, registration });
  if (formSource.player !== player || formSource.registration !== registration) {
    setFormSource({ player, registration });
    setIsFlex(player.is_flex);
    setNotes(player.admin_notes ?? "");
    setRegistrationStatus(registration?.status ?? "approved");
    setRegistrationBalancerStatus(registration?.balancer_status ?? "not_in_balancer");
    setHistoryPreview(null);
    setHistoryPreviewRequested(false);
    setHistoryLoadError(null);
    setPinToTournament(false);
    setRoleEntries(normalizeRoleEntries(player.role_entries_json));
  }

  const readHistory = async (workspaceValue: string) => {
    // Without the game's rated dimension there is no role dictionary to read a history against.
    const dimension = ontology ? (ratedDimension(ontology)?.code ?? null) : null;
    if (discipline === undefined || dimension === null) return;
    setLoadingHistory(true);
    setHistoryLoadError(null);
    try {
      const preview = await fetchPlayerRankHistoryPreview(
        player.identity,
        divisionGridVersion,
        divisionGrid,
        getHistoryWorkspaceIdParam(workspaceValue),
        workspaceId,
        discipline,
        selectableRoleCodes,
        dimension
      );
      setHistoryPreview(preview);
    } catch (error) {
      setHistoryPreview(null);
      setHistoryLoadError(error instanceof Error ? error.message : t("loadFailed"));
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
        applyHistoryPreviewToRoleEntries(
          roleEntries,
          historyPreview,
          resolveRankFromDivision
        ).map((entry) => ({ ...entry, division_number: resolveDivision(entry.rank_value) }))
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
    if (addableRole === null) return;

    setRoleEntries([
      ...roleEntries,
      {
        role: addableRole,
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
    divisionGrid,
    roleEntries,
    /** A one-role game's only role: the one entry the sheet shows. `null` when the game names roles (or is loading). */
    soleRole,
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
    getOriginalDivisionName,
    history,
    addRole,
    addableRole,
    updateEntry,
    removeEntry,
    reorderRoles,
    handleSave,
    handleMoveToReady,
    handleClearPin
  };
}
