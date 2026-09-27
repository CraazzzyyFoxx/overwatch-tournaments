"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { notify } from "@/lib/notify";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationTeamService from "@/services/registration-team.service";

interface MyTeamRefresh {
  /** Re-reads every list one roster write can move. */
  invalidate: () => Promise<unknown>;
  /** Reports a failed write through the code→i18n map: the server's `msg` is
   *  English and this is a public, Russian-first surface. */
  failure: (err: unknown) => void;
}

/**
 * The refresh half of the roster card, shared by its mutations and by the
 * invite dialog's own mutation (`useMyTeamInvite`).
 */
export function useMyTeamRefresh(
  workspaceId: number,
  tournamentId: number,
  teamId: number,
): MyTeamRefresh {
  const tErrors = useTranslations("registrationTeams.errors");
  const queryClient = useQueryClient();

  return {
    /** Both keys: issuing or revoking an invite moves `cap_used`, and a history
     *  left cached would under-report the ceiling the next time it is opened. */
    invalidate: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationTeams(workspaceId, tournamentId),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, teamId),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registration(workspaceId, tournamentId),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId),
        }),
      ]),
    failure: (err: unknown) => notify.error(translateRegistrationTeamError(tErrors, err)),
  };
}

interface UseMyTeamMutationsInput extends MyTeamRefresh {
  teamId: number;
  /** Post-success UI the card owns: the dialogs a mutation closes, and the
   *  token an extended link invite hands back exactly once. */
  onExtended: (token: string | null) => void;
  onLocked: () => void;
  onCheckedIn: () => void;
  onCovered: () => void;
}

/**
 * Every write the roster card can issue except the invite itself, which lives
 * with the invite dialog's own state (`useMyTeamInvite`).
 */
export function useMyTeamMutations({
  teamId,
  invalidate,
  failure,
  onExtended,
  onLocked,
  onCheckedIn,
  onCovered,
}: UseMyTeamMutationsInput) {
  const t = useTranslations("registrationTeams");

  const revokeMutation = useMutation({
    mutationFn: (inviteId: number) => registrationTeamService.revokeInvite(inviteId),
    onSuccess: async () => {
      notify.success(t("invite.revokeSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const kickMutation = useMutation({
    mutationFn: (registrationId: number) => registrationTeamService.kick(teamId, registrationId),
    onSuccess: async () => {
      notify.success(t("member.kickSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const transferMutation = useMutation({
    mutationFn: (registrationId: number) =>
      registrationTeamService.transferCaptaincy(teamId, registrationId),
    onSuccess: async () => {
      notify.success(t("member.makeCaptainSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const leaveMutation = useMutation({
    mutationFn: () => registrationTeamService.leave(teamId),
    onSuccess: async () => {
      notify.success(t("member.leaveSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const disbandMutation = useMutation({
    mutationFn: () => registrationTeamService.disband(teamId),
    onSuccess: async () => {
      notify.success(t("disband.success"));
      await invalidate();
    },
    onError: failure,
  });

  const uploadImageMutation = useMutation({
    mutationFn: (file: File) => registrationTeamService.uploadImage(teamId, file),
    onSuccess: async () => {
      notify.success(t("myCard.logoSaved"));
      await invalidate();
    },
    onError: failure,
  });

  const deleteImageMutation = useMutation({
    mutationFn: () => registrationTeamService.deleteImage(teamId),
    onSuccess: async () => {
      notify.success(t("myCard.logoRemoved"));
      await invalidate();
    },
    onError: failure,
  });

  const renameMutation = useMutation({
    mutationFn: (name: string) => registrationTeamService.rename(teamId, name),
    onSuccess: async () => {
      notify.success(t("rename.success"));
      await invalidate();
    },
    onError: failure,
  });

  const placeMutation = useMutation({
    mutationFn: (input: {
      registrationId: number;
      slot_code: string;
      is_substitute?: boolean;
      swap_with_registration_id?: number | null;
    }) =>
      registrationTeamService.placeMember(teamId, input.registrationId, {
        slot_code: input.slot_code,
        is_substitute: input.is_substitute,
        swap_with_registration_id: input.swap_with_registration_id,
      }),
    onSuccess: async () => {
      await invalidate();
    },
    onError: failure,
  });

  const managerMutation = useMutation({
    mutationFn: (input: { registrationId: number; isManager: boolean }) =>
      registrationTeamService.setManager(teamId, input.registrationId, input.isManager),
    onSuccess: async () => {
      await invalidate();
    },
    onError: failure,
  });

  const extendMutation = useMutation({
    mutationFn: (input: { inviteId: number; rotate: boolean }) =>
      registrationTeamService.extendInvite(teamId, input.inviteId, {
        rotate_token: input.rotate,
      }),
    onSuccess: async (invite) => {
      notify.success(t("invite.extendSuccess"));
      onExtended(invite.token ?? null);
      await invalidate();
    },
    onError: failure,
  });

  const lockMutation = useMutation({
    mutationFn: () => registrationTeamService.lockRoster(teamId),
    onSuccess: async () => {
      notify.success(t("lock.success"));
      onLocked();
      await invalidate();
    },
    onError: failure,
  });

  const checkInMutation = useMutation({
    mutationFn: (excludeIds: number[]) =>
      registrationTeamService.checkInRoster(teamId, excludeIds),
    onSuccess: async () => {
      notify.success(t("checkIn.success"));
      onCheckedIn();
      await invalidate();
    },
    onError: failure,
  });

  const coverMutation = useMutation({
    mutationFn: (code: string) =>
      registrationTeamService.coverSubscription(teamId, {
        code: code.trim() || null,
      }),
    onSuccess: async () => {
      notify.success(t("cover.success"));
      onCovered();
      await invalidate();
    },
    onError: failure,
  });

  return {
    revokeMutation,
    kickMutation,
    transferMutation,
    leaveMutation,
    disbandMutation,
    uploadImageMutation,
    deleteImageMutation,
    renameMutation,
    placeMutation,
    managerMutation,
    extendMutation,
    lockMutation,
    checkInMutation,
    coverMutation,
  };
}
