"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslations } from "next-intl";

import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  AdminRegistration,
  AdminRegistrationCreateInput,
  AdminRegistrationUpdateInput
} from "@/types/balancer-admin.types";

interface UseRegistrationMutationsInput {
  tournamentId: number | null;
  /** The registration node whose entries the screen edits; every write names it. */
  registrationNodeId: number | null;
  /** The row being edited, read at submit time by the update mutation. */
  editingRegistration: AdminRegistration | null;
  /** Dialogs the table owns and a successful write closes. */
  onCreated: () => void;
  onUpdated: () => void;
  onDeleted: () => void;
}

/**
 * Every write this screen issues, plus the cache surgery that keeps one edited
 * row in sync without re-reading the whole pool.
 */
export function useRegistrationMutations({
  tournamentId,
  registrationNodeId,
  editingRegistration,
  onCreated,
  onUpdated,
  onDeleted
}: UseRegistrationMutationsInput) {
  const queryClient = useQueryClient();
  const t = useTranslations("registrationsAdmin.mutations");
  const tActions = useTranslations("registrationsAdmin.actions");

  // Patch a single row across every cached filter variant. The PATCH endpoints
  // already return the fully-serialized registration, so we never need to
  // re-fetch the whole pool just to reflect one edit.
  const patchRegistrationInCache = useCallback(
    (row: AdminRegistration) => {
      queryClient.setQueriesData<AdminRegistration[]>(
        { queryKey: balancerQueryKeys.registrations(tournamentId, registrationNodeId) },
        (old) => (old ? old.map((r) => (r.id === row.id ? row : r)) : old)
      );
    },
    [queryClient, tournamentId, registrationNodeId]
  );

  const removeRegistrationFromCache = (registrationId: number) => {
    queryClient.setQueriesData<AdminRegistration[]>(
      { queryKey: balancerQueryKeys.registrations(tournamentId, registrationNodeId) },
      (old) => (old ? old.filter((r) => r.id !== registrationId) : old)
    );
  };

  // Fire-and-forget reconcile. NOT awaited, so the spinner/modal closes
  // immediately after the mutation itself resolves.
  const revalidateRegistrations = () => {
    void queryClient.invalidateQueries({
      queryKey: balancerQueryKeys.registrations(tournamentId, registrationNodeId)
    });
  };

  const createMutation = useMutation({
    mutationFn: (payload: AdminRegistrationCreateInput) =>
      balancerAdminService.createManualRegistration(tournamentId as number, registrationNodeId as number, payload),
    onSuccess: () => {
      onCreated();
      notify.success(t("created"));
      revalidateRegistrations();
    }
  });

  const updateMutation = useMutation({
    mutationFn: (payload: AdminRegistrationUpdateInput) => {
      if (!editingRegistration) {
        throw new Error("No registration selected");
      }
      return balancerAdminService.updateRegistration(editingRegistration.id, editingRegistration.registration_node_id, payload);
    },
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      onUpdated();
      notify.success(t("updated"));
      revalidateRegistrations();
    }
  });

  const approveMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.approveRegistration(registrationId, registrationNodeId as number),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success(t("approved"));
      revalidateRegistrations();
    }
  });

  const rejectMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.rejectRegistration(registrationId, registrationNodeId as number),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success(t("rejected"));
      revalidateRegistrations();
    }
  });

  const withdrawMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.withdrawRegistration(registrationId, registrationNodeId as number),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success(t("withdrawn"));
      revalidateRegistrations();
    }
  });

  const restoreMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.restoreRegistration(registrationId, registrationNodeId as number),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success(t("restored"));
      revalidateRegistrations();
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.deleteRegistration(registrationId, registrationNodeId as number),
    onSuccess: (_, registrationId) => {
      removeRegistrationFromCache(registrationId);
      onDeleted();
      notify.success(t("deleted"));
      revalidateRegistrations();
    }
  });

  const bulkApproveMutation = useMutation({
    mutationFn: (registrationIds: number[]) =>
      balancerAdminService.bulkApproveRegistrations(tournamentId as number, registrationNodeId as number, registrationIds),
    onSuccess: (result, registrationIds) => {
      notify.success(t("bulkApproved", { approved: result.approved, skipped: result.skipped }), {
        duration: 8000,
        action: {
          label: tActions("undo"),
          onClick: () => {
            // Only pending rows are selectable, so `pending` is the prior
            // status of every id in the batch.
            void Promise.all(
              registrationIds.map((id) =>
                balancerAdminService.updateRegistration(id, registrationNodeId as number, { status: "pending" })
              )
            )
              .then(() => {
                revalidateRegistrations();
                notify.success(t("approvalUndone"));
              })
              .catch((error: unknown) => notify.apiError(error));
          }
        }
      });
      revalidateRegistrations();
    }
  });

  const balancerInclusionMutation = useMutation({
    mutationFn: ({ registrationId, include }: { registrationId: number; include: boolean }) =>
      include
        ? balancerAdminService.includeInBalancer(registrationId, registrationNodeId as number)
        : balancerAdminService.setBalancerStatus(
            registrationId,
            registrationNodeId as number,
            "excluded",
            "manual_exclusion"
          ),
    onSuccess: (updated) => {
      patchRegistrationInCache(updated);
      notify.success(t("balancerUpdated"));
      revalidateRegistrations();
    }
  });

  const checkInMutation = useMutation({
    mutationFn: ({ registrationId, checkedIn }: { registrationId: number; checkedIn: boolean }) =>
      balancerAdminService.checkInRegistration(registrationId, registrationNodeId as number, checkedIn),
    onSuccess: (updated, variables) => {
      patchRegistrationInCache(updated);
      notify.success(variables.checkedIn ? t("checkedIn") : t("checkInRemoved"));
      revalidateRegistrations();
    }
  });

  const bulkAddToBalancerMutation = useMutation({
    // `previouslyExcluded` travels with the call because the undo needs the
    // pre-mutation inclusion state, which the refetched rows no longer carry.
    mutationFn: ({ ids }: { ids: number[]; previouslyExcluded: number[] }) =>
      balancerAdminService.bulkAddToBalancer(tournamentId as number, registrationNodeId as number, ids),
    onSuccess: (result, { previouslyExcluded }) => {
      notify.success(t("bulkAdded", { updated: result.updated, skipped: result.skipped }), {
        duration: 8000,
        action: {
          label: tActions("undo"),
          onClick: () => {
            void (previouslyExcluded.length > 0
              ? balancerAdminService.bulkSetBalancerStatus(tournamentId as number, registrationNodeId as number, {
                  registration_ids: previouslyExcluded,
                  balancer_status: "excluded",
                  exclude_reason: "manual_exclusion"
                })
              : Promise.resolve()
            )
              .then(() => {
                revalidateRegistrations();
                notify.success(t("balancerUndone"));
              })
              .catch((error: unknown) => notify.apiError(error));
          }
        }
      });
      revalidateRegistrations();
    }
  });

  return {
    patchRegistrationInCache,
    createMutation,
    updateMutation,
    approveMutation,
    rejectMutation,
    withdrawMutation,
    restoreMutation,
    deleteMutation,
    bulkApproveMutation,
    balancerInclusionMutation,
    checkInMutation,
    bulkAddToBalancerMutation
  };
}
