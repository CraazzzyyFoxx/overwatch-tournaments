"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { notify } from "@/lib/notify";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import registrationTeamService from "@/services/registration-team.service";
import type {
  RegistrationTeam,
  RegistrationTeamExportResult
} from "@/types/registration-team.types";

/**
 * Every read and write the organizer's teams browser performs, in one place.
 *
 * The screen's writes all land on the same three caches, so the invalidation
 * belongs to the data layer rather than to each caller: a mutation added beside
 * the others cannot forget the public roster the way a hand-written
 * `invalidateQueries` in a click handler did.
 */

/** Both admin variants plus the public roster: a reject or an export changes
 *  every one of them, and the two admin flags are separate cache entries. */
export function invalidateRegistrationTeams(
  queryClient: QueryClient,
  workspaceId: number,
  tournamentId: number
) {
  for (const flag of [false, true]) {
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationTeamsAdmin(workspaceId, tournamentId, flag)
    });
  }
  void queryClient.invalidateQueries({
    queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId)
  });
  void queryClient.invalidateQueries({
    queryKey: tournamentQueryKeys.registrationTeams(workspaceId, tournamentId)
  });
}

export interface RegistrationTeamActions {
  teams: RegistrationTeam[];
  unassignedPlayers: number;
  total: number;
  isError: boolean;
  isFetching: boolean;
  error: unknown;
  refetch: () => void;
  /** The last refusal, in the organizer's language: a toast expires before it
   *  has been read, and the server's English `msg` must never reach them. */
  actionError: string | null;
  setActionError: (message: string | null) => void;
  reportError: (error: unknown) => void;
  exportResult: RegistrationTeamExportResult | null;
  /** Any write in flight. One flag, because every control on the screen is
   *  disabled by any of them. */
  busy: boolean;
  isExporting: boolean;
  isRejecting: boolean;
  reject: (input: { teamId: number; withdrawMembers: boolean; reason: string }) => void;
  exportTeams: (teamIds: number[], onSuccess?: () => void) => void;
  revokeInvite: (input: { teamId: number; inviteId: number }) => void;
  resetCap: (team: RegistrationTeam) => void;
  unlock: (team: RegistrationTeam) => void;
  setAdmission: (input: {
    teamId: number;
    admission: "pending" | "accepted" | "waitlisted";
  }) => void;
  setNotes: (input: { teamId: number; notes: string | null }) => void;
  isRenaming: boolean;
  rename: (input: { teamId: number; name: string }) => void;
  isPlacing: boolean;
  placeMember: (input: {
    teamId: number;
    registrationId: number;
    slot_code: string;
    is_substitute: boolean;
  }) => void;
  attachMember: (input: {
    teamId: number;
    battle_tag: string;
    slot_code: string;
    is_substitute: boolean;
  }) => void;
  nameDraft: Record<number, string>;
  setNameDraft: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  notesDraft: Record<number, string>;
  setNotesDraft: React.Dispatch<React.SetStateAction<Record<number, string>>>;
}

export function useRegistrationTeamActions({
  tournamentId,
  workspaceId,
  closeConfirm,
  closeRename,
  closePlace
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
  /** A confirmed action that succeeded has nothing left to ask. */
  closeConfirm: () => void;
  closeRename: () => void;
  closePlace: () => void;
}>): RegistrationTeamActions {
  const t = useTranslations("registrationTeams");
  // Backend messages are English; every rejection here carries a machine code
  // and MUST go through the translator (§12.2).
  const tErr = useTranslations("registrationTeams.errors");
  const queryClient = useQueryClient();

  const [actionError, setActionError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<RegistrationTeamExportResult | null>(null);
  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({});
  const [nameDraft, setNameDraft] = useState<Record<number, string>>({});

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationTeamsAdmin(workspaceId, tournamentId, true),
    queryFn: () => registrationTeamService.listAdmin(tournamentId, { includeTerminal: true })
  });

  const invalidateTeams = () => {
    setActionError(null);
    invalidateRegistrationTeams(queryClient, workspaceId, tournamentId);
  };

  const reportError = (error: unknown) =>
    setActionError(translateRegistrationTeamError(tErr, error, t("admin.actionFailed")));

  const rejectMutation = useMutation({
    mutationFn: (input: { teamId: number; withdrawMembers: boolean; reason: string }) =>
      registrationTeamService.reject(tournamentId, input.teamId, {
        withdrawMembers: input.withdrawMembers,
        reason: input.reason
      }),
    onSuccess: () => {
      invalidateTeams();
      closeConfirm();
      notify.success(t("admin.rejectSuccess"));
    },
    onError: reportError
  });

  const exportMutation = useMutation({
    mutationFn: (teamIds: number[]) =>
      registrationTeamService.exportRegistered(tournamentId, teamIds),
    onSuccess: (result) => {
      invalidateTeams();
      // The export writes `tournament.team` rows, which the bracket and the
      // public pages read.
      invalidateTournamentWorkspace(queryClient, tournamentId, workspaceId);

      setExportResult(result);
      closeConfirm();
      const names = result.skipped.map((item) => item.name).join(", ");
      const description = names ? t("admin.exportSkipped", { names }) : undefined;

      if (result.imported_teams === 0) {
        notify.info(t("admin.exportNothing"), { description });
        return;
      }
      notify.success(t("admin.exportSuccess", { count: result.imported_teams }), { description });
    },
    onError: reportError
  });

  /** A withdrawn invite leaves the live chips AND lands in the ledger as
   *  `revoked_by_organizer`; a cap reset moves the ledger's floor. Both reads go. */
  const invalidateTeamInvites = (teamId: number) => {
    invalidateTeams();
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, teamId)
    });
  };

  const revokeInviteMutation = useMutation({
    mutationFn: (input: { teamId: number; inviteId: number }) =>
      registrationTeamService.revokeInviteAdmin(tournamentId, input.inviteId),
    onSuccess: (_result, input) => {
      invalidateTeamInvites(input.teamId);
      notify.success(t("admin.revokeInviteSuccess"));
    },
    onError: reportError
  });

  /**
   * The escape hatch for the total invite cap, which counts every invite the
   * team ever created — so an invite/revoke cycle burns the ceiling on invites
   * nobody can see any more, and the refusal it produces used to name an
   * organizer intervention that no endpoint provided. This is that intervention.
   */
  const resetCapMutation = useMutation({
    mutationFn: (team: RegistrationTeam) =>
      registrationTeamService.resetInviteCap(tournamentId, team.id),
    onSuccess: (_result, team) => {
      invalidateTeamInvites(team.id);
      closeConfirm();
      notify.success(t("admin.resetCapSuccess", { team: team.name }));
    },
    onError: reportError
  });

  const unlockMutation = useMutation({
    mutationFn: (team: RegistrationTeam) =>
      registrationTeamService.unlockRoster(tournamentId, team.id),
    onSuccess: () => {
      invalidateTeams();
      closeConfirm();
      notify.success(t("admin.unlockSuccess"));
    },
    onError: reportError
  });

  const admissionMutation = useMutation({
    mutationFn: (input: { teamId: number; admission: "pending" | "accepted" | "waitlisted" }) =>
      registrationTeamService.setAdmission(tournamentId, input.teamId, input.admission),
    onSuccess: () => {
      invalidateTeams();
      notify.success(t("admin.admissionSuccess"));
    },
    onError: reportError
  });

  const notesMutation = useMutation({
    mutationFn: (input: { teamId: number; notes: string | null }) =>
      registrationTeamService.setNotes(tournamentId, input.teamId, input.notes),
    onSuccess: () => {
      invalidateTeams();
      notify.success(t("admin.notesSuccess"));
    },
    onError: reportError
  });

  const renameMutation = useMutation({
    mutationFn: (input: { teamId: number; name: string }) =>
      registrationTeamService.renameAdmin(tournamentId, input.teamId, input.name),
    onSuccess: (_result, input) => {
      invalidateTeams();
      closeRename();
      setNameDraft((current) => {
        const next = { ...current };
        delete next[input.teamId];
        return next;
      });
      notify.success(t("rename.success"));
    },
    onError: reportError
  });

  /** The placed player is not a free agent any more. */
  const invalidatePlaced = () => {
    invalidateTeams();
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId)
    });
    closePlace();
    notify.success(t("admin.placeSuccess"));
  };

  const placeAdminMutation = useMutation({
    mutationFn: (input: {
      teamId: number;
      registrationId: number;
      slot_code: string;
      is_substitute: boolean;
    }) =>
      registrationTeamService.placeMemberAdmin(tournamentId, input.teamId, input.registrationId, {
        slot_code: input.slot_code,
        is_substitute: input.is_substitute
      }),
    onSuccess: invalidatePlaced,
    onError: reportError
  });

  /** The same act for someone this tournament has never seen: the organizer
   *  types the BattleTag instead of picking a registrant. */
  const attachAdminMutation = useMutation({
    mutationFn: (input: {
      teamId: number;
      battle_tag: string;
      slot_code: string;
      is_substitute: boolean;
    }) =>
      registrationTeamService.attachMemberAdmin(tournamentId, input.teamId, {
        battle_tag: input.battle_tag,
        slot_code: input.slot_code,
        is_substitute: input.is_substitute
      }),
    onSuccess: invalidatePlaced,
    onError: reportError
  });

  return {
    teams: teamsQuery.data?.items ?? [],
    unassignedPlayers: teamsQuery.data?.unassigned_players ?? 0,
    total: teamsQuery.data?.total ?? 0,
    isError: teamsQuery.isError,
    isFetching: teamsQuery.isFetching,
    error: teamsQuery.error,
    refetch: () => void teamsQuery.refetch(),
    actionError,
    setActionError,
    reportError,
    exportResult,
    busy:
      rejectMutation.isPending ||
      exportMutation.isPending ||
      revokeInviteMutation.isPending ||
      resetCapMutation.isPending ||
      unlockMutation.isPending ||
      admissionMutation.isPending ||
      notesMutation.isPending ||
      renameMutation.isPending ||
      placeAdminMutation.isPending ||
      attachAdminMutation.isPending,
    isExporting: exportMutation.isPending,
    isRejecting: rejectMutation.isPending,
    reject: rejectMutation.mutate,
    exportTeams: (teamIds, onSuccess) => exportMutation.mutate(teamIds, { onSuccess }),
    revokeInvite: revokeInviteMutation.mutate,
    resetCap: resetCapMutation.mutate,
    unlock: unlockMutation.mutate,
    setAdmission: admissionMutation.mutate,
    setNotes: notesMutation.mutate,
    isRenaming: renameMutation.isPending,
    rename: renameMutation.mutate,
    isPlacing: placeAdminMutation.isPending || attachAdminMutation.isPending,
    placeMember: placeAdminMutation.mutate,
    attachMember: attachAdminMutation.mutate,
    nameDraft,
    setNameDraft,
    notesDraft,
    setNotesDraft
  };
}
