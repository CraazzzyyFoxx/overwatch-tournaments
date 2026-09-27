"use client";

import { useCallback, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  emptyEncounterForm,
  encounterCreatePayload,
  encounterFormError,
  encounterFormOf,
  encounterUpdatePayload,
  type EncounterFormMode,
  type EncounterFormState
} from "@/components/admin/EncounterForm";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Encounter } from "@/types/encounter.types";
import type { Stage } from "@/types/tournament.types";

/**
 * The create/edit form of one encounter: which row it is editing, what has been
 * typed into it, and the write it ends in.
 *
 * `initial` is kept beside `value` because the dialog's discard guard asks
 * "has this changed", and a form that compares itself to a blank template
 * prompts on a dialog nobody touched.
 */
export function useEncounterForm({
  scopeTournamentId,
  stages,
  onSaved
}: Readonly<{
  scopeTournamentId: number | null;
  stages: Stage[];
  onSaved: () => void;
}>) {
  const [mode, setMode] = useState<EncounterFormMode | null>(null);
  const [editing, setEditing] = useState<Encounter | null>(null);
  const [value, setValue] = useState<EncounterFormState>(emptyEncounterForm(null, null));
  const [initial, setInitial] = useState<EncounterFormState>(emptyEncounterForm(null, null));
  const [error, setError] = useState<string | undefined>();

  const close = () => {
    setMode(null);
    setEditing(null);
    setError(undefined);
  };

  const saveMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (payload: EncounterFormState) =>
      editing
        ? adminService.updateEncounter(editing.id, encounterUpdatePayload(payload))
        : adminService.createEncounter(encounterCreatePayload(payload, scopeTournamentId!)),
    onSuccess: () => {
      const created = editing == null;
      onSaved();
      close();
      notify.success(created ? "Encounter created" : "Encounter updated");
    },
    onError: (failure: Error) => setError(`Could not save the encounter. ${failure.message}`)
  });

  // `saveMutation` is rebuilt on every state transition; `reset` is not, so the
  // memoised `openEdit` below hangs on the callback instead of the container.
  const { reset: resetSaveMutation } = saveMutation;

  // The kebab column closes over this, so the column memo has to depend on it —
  // which means it needs an identity that only moves when its inputs do. Every
  // other name it touches is a `useState` setter (stable by contract).
  const openEdit = useCallback(
    (encounter: Encounter) => {
      const next = encounterFormOf(encounter);
      resetSaveMutation();
      setError(undefined);
      setEditing(encounter);
      setValue(next);
      setInitial(next);
      setMode("edit");
    },
    [resetSaveMutation]
  );

  return {
    mode,
    value,
    setValue,
    error,
    isSaving: saveMutation.isPending,
    isDirty: mode != null && hasUnsavedChanges(value, initial),
    close,
    openEdit,
    openCreate: () => {
      const stage = stages[0] ?? null;
      const blank = emptyEncounterForm(stage?.id ?? null, stage?.items[0]?.id ?? null);
      resetSaveMutation();
      setError(undefined);
      setEditing(null);
      setValue(blank);
      setInitial(blank);
      setMode("create");
    },
    submit: () => {
      const invalid = encounterFormError(value);
      if (invalid) {
        setError(invalid);
        return;
      }
      saveMutation.mutate(value);
    }
  };
}
