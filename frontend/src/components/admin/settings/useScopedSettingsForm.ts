"use client";

import { useCallback, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { notify } from "@/lib/notify";

export interface ScopedSettingsFormOptions<TForm, TPayload> {
  /**
   * The saved values this section edits, read off the server entity — `null`
   * while it loads. Memoise it: a new identity is what re-baselines the form,
   * so an unmemoised derivation would reset the user's typing every render.
   */
  baseline: TForm | null;
  /** The scoped diff this section would send right now. */
  toPayload: (form: TForm, baseline: TForm) => TPayload;
  /**
   * Fields the summary counts; defaults to the payload's keys. Only a section
   * that saves something outside the payload (a second endpoint) needs it.
   */
  countChanges?: (payload: TPayload, form: TForm, baseline: TForm) => number;
  /** Sends the diff. A section with a second endpoint sends that here too. */
  submit: (payload: TPayload, form: TForm, baseline: TForm) => Promise<unknown>;
  /** Re-reads whatever the save invalidated; runs before the toast. */
  onSaved?: () => void;
}

/** Everything a settings section needs to render and save its own fields. */
export interface ScopedSettingsForm<TForm, TPayload> {
  /** `null` only while the entity is still loading. */
  form: TForm | null;
  /** Merges a partial into the form; the only way a section mutates it. */
  patch: (values: Partial<TForm>) => void;
  dirty: boolean;
  /** "2 changed fields" for the `SaveBar` summary. */
  summary: string;
  saving: boolean;
  /** The PATCH body this section would send right now — the diff, scoped. */
  payload: TPayload | null;
  save: () => void;
  discard: () => void;
}

/**
 * Form state of one settings section, and the scoped diff it saves.
 *
 * A section owns a subset of an entity's fields: it diffs what the user typed
 * against the saved entity, reports "what changed" from that diff alone, and
 * PATCHes nothing else. Sending every field a screen holds is how renaming a
 * tournament used to record a full rewrite of its rules and scoring in the
 * audit trail (`model_dump(exclude_unset=True)` records exactly the keys a
 * PATCH sends), so the scoping is the point, not an optimisation.
 *
 * Workspace and tournament settings share this hook; each supplies its own
 * baseline, diff and endpoints.
 */
export function useScopedSettingsForm<TForm, TPayload>({
  baseline,
  toPayload,
  countChanges,
  submit,
  onSaved
}: ScopedSettingsFormOptions<TForm, TPayload>): ScopedSettingsForm<TForm, TPayload> {
  const changesBetween = (form: TForm, base: TForm) => {
    const diff = toPayload(form, base);
    return countChanges
      ? countChanges(diff, form, base)
      : Object.keys(diff as Record<string, unknown>).length;
  };

  const [state, setState] = useState<{ form: TForm; baseline: TForm } | null>(() =>
    baseline === null ? null : { form: baseline, baseline }
  );

  // Re-baseline when the entity changes under us: our own refetch after a save,
  // another admin's write arriving through an invalidation, or the entity
  // simply loading in. Done during render rather than in an effect, because an
  // effect would first commit a render whose `dirty` and `payload` compare the
  // new baseline against the old form and briefly report phantom changed
  // fields.
  if (baseline !== null && state?.baseline !== baseline) {
    setState((current) => {
      // A refetch always re-baselines, but only replaces the form while the
      // user has nothing unsaved to lose.
      if (current && changesBetween(current.form, current.baseline) > 0) {
        return { form: current.form, baseline };
      }
      return { form: baseline, baseline };
    });
  }

  const payload = state ? toPayload(state.form, state.baseline) : null;
  const changedCount = state ? changesBetween(state.form, state.baseline) : 0;

  const mutation = useMutation({
    mutationFn: async () => {
      if (!state || payload === null) return;
      await submit(payload, state.form, state.baseline);
    },
    onSuccess: () => {
      onSaved?.();
      notify.success("Settings saved");
    },
    onError: (error) => notify.apiError(error, { title: "Could not save these settings" })
  });

  const patch = useCallback(
    (values: Partial<TForm>) =>
      setState((current) =>
        current ? { ...current, form: { ...current.form, ...values } } : current
      ),
    []
  );
  const discard = useCallback(
    () => setState((current) => (current ? { ...current, form: current.baseline } : current)),
    []
  );

  return {
    form: state?.form ?? null,
    patch,
    dirty: changedCount > 0,
    summary: changedCount === 1 ? "1 changed field" : `${changedCount} changed fields`,
    saving: mutation.isPending,
    payload,
    save: () => mutation.mutate(),
    discard
  };
}
