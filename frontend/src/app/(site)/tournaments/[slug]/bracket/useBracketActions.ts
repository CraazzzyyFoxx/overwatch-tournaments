"use client";

import { useMemo, useState } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import type { BracketSlotRef } from "@/components/bracket/BracketView";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import captainService from "@/services/captain.service";
import encounterService from "@/services/encounter.service";
import type { Encounter } from "@/types/encounter.types";
import type { PaginatedResponse } from "@/types/pagination.types";
import type { StageSummary, Tournament } from "@/types/tournament.types";

import { isStageReportable, swapSlotTeams } from "./bracketData";

const ADMIN_ROLES = new Set(["admin", "superadmin", "tournament_admin"]);

export type BracketViewer = {
  isAdmin: boolean;
  /**
   * May rewrite the bracket's STRUCTURE — drag a team into another slot, and
   * the best-of / start-time fields of the edit dialog. A referee holds
   * `match.result` only, which makes them `isAdmin` here (any non-read grant
   * does) but leaves the structure alone.
   */
  canEditStructure: boolean;
  isAuthenticated: boolean;
  /** The player ids this account is linked to — who it can report FOR. */
  captainPlayerIds: Set<number>;
};

/**
 * Who is looking at the bracket. Separate from the actions below so the page
 * resolves it once and hands it to them.
 */
export function useBracketViewer(workspaceId: number): BracketViewer {
  const { isSuperuser, isWorkspaceAdmin, hasWorkspacePermission } = usePermissions();
  const { status, user } = useAuthProfile();
  const isAuthenticated = status === "authenticated";
  const hasGlobalAdminRole = (user?.roles ?? []).some((role) => ADMIN_ROLES.has(role));
  const isAdmin =
    isAuthenticated && (isSuperuser || isWorkspaceAdmin(workspaceId) || hasGlobalAdminRole);
  const canEditStructure =
    isAuthenticated &&
    (isSuperuser || hasGlobalAdminRole || hasWorkspacePermission(workspaceId, "match.update"));
  const captainPlayerIds = useMemo(
    () => new Set((user?.linkedPlayers ?? []).map((player) => player.playerId)),
    [user?.linkedPlayers]
  );

  return { isAdmin, canEditStructure, isAuthenticated, captainPlayerIds };
}

type BracketActionsInput = {
  tournament: Tournament;
  viewer: BracketViewer;
  /** The visible stages by id, for the "can this stage still be reported?" gate. */
  stageById: ReadonlyMap<number, StageSummary>;
  /** The encounters entry the optimistic slot swap writes through. */
  encountersQueryKey: QueryKey;
  refetchEncounters: () => void;
};

/**
 * The bracket's write side: the organizer's edit and rearrange, and the
 * captain's report — plus the two dialogs they open.
 */
export function useBracketActions({
  tournament,
  viewer,
  stageById,
  encountersQueryKey,
  refetchEncounters
}: BracketActionsInput) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [editEncounter, setEditEncounter] = useState<Encounter | null>(null);
  const [reportEncounter, setReportEncounter] = useState<Encounter | null>(null);
  const { isAdmin, canEditStructure, isAuthenticated, captainPlayerIds } = viewer;

  const isEncounterCaptain = (encounter: Encounter) => {
    const homeCaptain = encounter.home_team?.captain_id;
    const awayCaptain = encounter.away_team?.captain_id;
    return (
      (homeCaptain != null && captainPlayerIds.has(homeCaptain)) ||
      (awayCaptain != null && captainPlayerIds.has(awayCaptain))
    );
  };

  const canEdit = isAdmin ? () => true : undefined;
  const canReport = isAuthenticated
    ? (encounter: Encounter) =>
        encounter.result_status !== "confirmed" &&
        isEncounterCaptain(encounter) &&
        isStageReportable(
          encounter.stage_id == null ? undefined : stageById.get(encounter.stage_id)
        )
    : undefined;
  const handleEdit = isAdmin
    ? (encounter: Encounter) => setEditEncounter(encounter)
    : undefined;
  const handleReport = isAuthenticated
    ? async (encounter: Encounter) => {
        try {
          const [fresh, role] = await Promise.all([
            encounterService.getEncounter(encounter.id),
            captainService.getMyRole(encounter.id)
          ]);
          if (fresh.result_status === "confirmed") {
            // The result was confirmed after this bracket data was cached; the
            // report action is no longer valid. Tell the captain why, then
            // refresh so the stale report action disappears.
            notify.error(t("matchReport.confirmedLockedTitle"), {
              description: t("matchReport.confirmedLockedBody")
            });
            refetchEncounters();
            return;
          }
          if (role.side === null) {
            notify.error(t("common.noAccess"), { description: t("common.notCaptain") });
            return;
          }
          setReportEncounter(fresh);
        } catch {
          notify.error(t("common.error"), { description: t("common.roleVerificationFailed") });
        }
      }
    : undefined;

  // Rearrange mode: one server call swaps two slots; the cache takes the swap
  // first so the dropped team stays put, and is restored if the server refuses
  // (a match went live between poll and drop). Structure, not result — so a
  // referee never gets the drag handles.
  const handleSwapSlots = canEditStructure
    ? async (source: BracketSlotRef<Encounter>, target: BracketSlotRef<Encounter>) => {
        const previous =
          queryClient.getQueryData<PaginatedResponse<Encounter>>(encountersQueryKey);
        if (previous) {
          queryClient.setQueryData<PaginatedResponse<Encounter>>(encountersQueryKey, {
            ...previous,
            results: swapSlotTeams(
              previous.results,
              { encounterId: source.encounter.id, slot: source.slot },
              { encounterId: target.encounter.id, slot: target.slot }
            )
          });
        }
        try {
          await adminService.swapEncounterSlot(source.encounter.id, {
            slot: source.slot,
            target_encounter_id: target.encounter.id,
            target_slot: target.slot
          });
          notify.success(t("bracket.rearrangeDone"));
        } catch (error) {
          if (previous) queryClient.setQueryData(encountersQueryKey, previous);
          notify.apiError(error, { title: t("bracket.rearrangeFailed") });
        }
        await refreshEncounterViews(queryClient, tournament.id);
      }
    : undefined;

  return {
    canEdit,
    canReport,
    handleEdit,
    handleReport,
    handleSwapSlots,
    editEncounter,
    setEditEncounter,
    reportEncounter,
    setReportEncounter
  };
}
