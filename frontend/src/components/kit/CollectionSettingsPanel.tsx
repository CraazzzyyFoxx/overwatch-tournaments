"use client";

import { useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  useScopedSettingsForm,
  type ScopedSettingsForm
} from "@/components/kit/useScopedSettingsForm";
import { SaveBar } from "@craazzzyyfoxx/admin-kit/kit/SaveBar";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import adminService from "@/services/admin.service";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useUnsavedReporter } from "@/components/kit/SettingsContinuation";

type SettingValue = Record<string, unknown>;

interface UseCollectionSettingsOptions<T extends object> {
  /** The `settings` table key this collector's config is stored under. */
  settingKey: string;
  /**
   * Saved value (absent when the row was never written) to form. Merges the
   * shipped defaults. Module-level: its identity is the baseline's dependency,
   * and a new baseline resets the form.
   */
  read: (stored: Partial<T> | undefined) => T;
  /** Form to the value `PUT /admin/settings/{key}` stores; the form itself by default. */
  write?: (form: T) => SettingValue;
  /** Changed fields for the save bar; top-level keys that differ by default. */
  countChanges?: (form: T, baseline: T) => number;
  /** Extra query keys to invalidate on a successful save, beyond the settings list. */
  invalidateKeys?: QueryKey[];
}

export interface CollectionSettings<T> extends ScopedSettingsForm<T, SettingValue> {
  isLoading: boolean;
  isError: boolean;
}

function countChangedKeys<T extends object>(form: T, baseline: T): number {
  return (Object.keys(form) as (keyof T)[]).filter((key) => !Object.is(form[key], baseline[key]))
    .length;
}

/**
 * Data half of a background collector's settings: the saved config as the
 * baseline of the same scoped form every other admin settings section uses,
 * so the collectors get the sticky save bar, the unsaved-changes guard and the
 * toasts instead of a save button of their own.
 *
 * The backend stores each config as one JSON value, so a save writes the whole
 * value; only the change count is per field.
 */
export function useCollectionSettings<T extends object>({
  settingKey,
  read,
  write,
  countChanges = countChangedKeys,
  invalidateKeys = []
}: UseCollectionSettingsOptions<T>): CollectionSettings<T> {
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: adminQueryKeys.settings(),
    queryFn: () => adminService.getSettings()
  });

  const loaded = settingsQuery.data !== undefined;
  const stored = settingsQuery.data?.find((s) => s.key === settingKey)?.value as
    | Partial<T>
    | undefined;
  const baseline = useMemo(() => (loaded ? read(stored) : null), [loaded, stored, read]);

  const form = useScopedSettingsForm<T, SettingValue>({
    baseline,
    toPayload: (current) => (write ? write(current) : (current as SettingValue)),
    countChanges: (_value, current, base) => countChanges(current, base),
    submit: (value) => adminService.updateSetting(settingKey, { value }),
    onSaved: () => {
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.settings() });
      for (const key of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    }
  });

  return { ...form, isLoading: settingsQuery.isLoading, isError: settingsQuery.isError };
}

/**
 * UI half: the load states, the collector's own `SettingGroup`s (each its own
 * card) and the save bar — the same frame as a workspace or tournament
 * settings section.
 */
export function CollectionSettingsPanel<T>({
  settings,
  children
}: Readonly<{
  settings: CollectionSettings<T>;
  children: (form: T, patch: (values: Partial<T>) => void) => ReactNode;
}>) {
  const reportUnsaved = useUnsavedReporter();
  const t = useTranslations("collectors.settings");

  if (settings.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadErrorTitle")}
        description={t("loadErrorDescription")}
      />
    );
  }

  if (settings.isLoading || !settings.form) {
    return <Skeleton className="h-80 w-full rounded-xl" />;
  }

  return (
    <>
      {children(settings.form, settings.patch)}
      <SaveBar
        onDirtyChange={reportUnsaved}
        dirty={settings.dirty}
        summary={settings.summary}
        error={settings.error}
        saving={settings.saving}
        onDiscard={settings.discard}
        onSave={settings.save}
      />
    </>
  );
}
