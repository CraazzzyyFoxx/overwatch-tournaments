"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { notify } from "@/lib/notify";
import { toRegistrationFormUpsert } from "@/lib/registration-form-upsert";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  AdminRegistrationForm,
  AdminRegistrationFormUpsert
} from "@/types/balancer-admin.types";

/** Same key the questionnaire builder uses, so the four editors share one read. */
export const registrationFormQueryKey = (tournamentId: number) =>
  ["balancer-admin", "registration-form", tournamentId] as const;

export interface RegistrationFormSection {
  /** The saved form with this section's unsaved edits applied. */
  value: AdminRegistrationFormUpsert;
  /** Read-only projections the server resolves; absent until the first save. */
  saved: AdminRegistrationForm | null;
  patch: (next: Partial<AdminRegistrationFormUpsert>) => void;
  dirty: boolean;
  summary: string;
  loading: boolean;
  saving: boolean;
  save: () => void;
  discard: () => void;
}

/**
 * Form state of one registration-form settings section.
 *
 * The counterpart of `useTournamentSettingsForm`, with one structural
 * difference that is the whole reason it exists: the tournament PATCH takes a
 * scoped diff, while `PUT registration-form` is a full replace. A section that
 * sent only its own fields would reset every field belonging to the other three
 * screens, so the save is always `saved form + this section's edits`.
 *
 * Edits are held as a patch rather than as per-field state so `dirty` is
 * literally "fields this screen changed" — no baseline comparison, and a
 * background refetch cannot silently un-dirty an edit.
 */
export function useRegistrationFormSection(tournamentId: number): RegistrationFormSection {
  const queryClient = useQueryClient();
  const [patchState, setPatchState] = useState<Partial<AdminRegistrationFormUpsert>>({});

  const query = useQuery({
    queryKey: registrationFormQueryKey(tournamentId),
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId),
    // A settings screen is a long-lived editor; a background refetch must not
    // clobber unsaved edits.
    refetchOnWindowFocus: false
  });

  // `null` rather than `undefined` while loading: the row is created lazily, so
  // "no form yet" is a normal state this hook has to be able to save from.
  const saved = query.data ?? null;

  const value = useMemo(
    () => ({ ...toRegistrationFormUpsert(saved), ...patchState }),
    [saved, patchState]
  );

  const patch = useCallback((next: Partial<AdminRegistrationFormUpsert>) => {
    setPatchState((current) => ({ ...current, ...next }));
  }, []);

  const mutation = useMutation({
    mutationFn: () => balancerAdminService.upsertRegistrationForm(tournamentId, value),
    onSuccess: async (updated) => {
      queryClient.setQueryData(registrationFormQueryKey(tournamentId), updated);
      setPatchState({});
      notify.success("Registration settings saved");
    },
    onError: () => notify.error("Could not save the registration settings")
  });

  const changed = Object.keys(patchState).length;

  return {
    value,
    saved,
    patch,
    dirty: changed > 0,
    summary: changed === 1 ? "1 changed setting" : `${changed} changed settings`,
    loading: query.isLoading,
    saving: mutation.isPending,
    save: () => mutation.mutate(),
    discard: () => setPatchState({})
  };
}
