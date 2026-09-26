"use client";

import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import encounterService from "@/services/encounter.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { notify } from "@/lib/notify";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { EncounterSavedView } from "@/types/encounter.types";

import type { EncounterFilterState } from "./encounters.helpers";

export interface SavedViewCallbacks {
  /** Run after a successful save — closes the naming dialog. */
  onSaved: () => void;
  /** Run after a successful delete — dismisses the confirmation. */
  onDeleted: () => void;
}

export interface EncounterSavedViews {
  views: EncounterSavedView[] | undefined;
  savePending: boolean;
  deletePending: boolean;
  /**
   * Opens the sign-in modal (returning here afterwards) and answers `false`
   * when the viewer has no account to save a view onto.
   */
  requireAuth: () => boolean;
  save: (name: string, filters: EncounterFilterState) => void;
  remove: (id: number) => void;
}

/** The viewer's own saved filter sets, plus the writes that maintain them. */
export function useEncounterSavedViews({
  onSaved,
  onDeleted
}: SavedViewCallbacks): EncounterSavedViews {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const listKey = encounterQueryKeys.savedViews(currentWorkspaceId, user?.username);

  const savedViewsQuery = useQuery({
    queryKey: listKey,
    queryFn: () => encounterService.getSavedViews(currentWorkspaceId),
    enabled: Boolean(user && currentWorkspaceId != null),
    placeholderData: (previous) => previous,
    retry: false,
    staleTime: 60_000
  });

  const saveViewMutation = useMutation({
    mutationFn: ({ name, filters }: { name: string; filters: EncounterFilterState }) =>
      encounterService.saveView(name, filters, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      onSaved();
      notify.success(t("encounters.savedView.saved"));
    }
  });

  const deleteViewMutation = useMutation({
    mutationFn: ({ id }: { id: number }) => encounterService.deleteView(id, currentWorkspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      onDeleted();
      notify.success(t("encounters.savedView.deleted"));
    }
  });

  return {
    views: savedViewsQuery.data,
    savePending: saveViewMutation.isPending,
    deletePending: deleteViewMutation.isPending,
    requireAuth: () => {
      if (user) return true;
      openAuthModal(getCurrentPathForAuthRedirect(window.location));
      return false;
    },
    save: (name, filters) => saveViewMutation.mutate({ name, filters }),
    remove: (id) => deleteViewMutation.mutate({ id })
  };
}
