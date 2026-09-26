"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import adminService from "@/services/admin.service";
import { adminQueryKeys } from "@/lib/admin/query-keys";

interface UseCollectionSettingsOptions<T extends object> {
  /** The `settings` table key this collector's config is stored under. */
  settingKey: string;
  /** Shipped defaults, merged under whatever the backend has saved. */
  defaults: T;
  /** Extra query keys to invalidate on a successful save, beyond `["admin", "settings"]`. */
  invalidateKeys?: QueryKey[];
}

/**
 * Data half of a background collector's settings card: fetch the saved
 * config, merge it under the domain's defaults, track an editable draft that
 * re-syncs when a refetch delivers a different saved value, and save it back.
 * Shared by every collector (rank, subscriptions, streams) whose config is
 * one `enabled` flag plus an interval/batch pair.
 */
export function useCollectionSettings<T extends object>({
  settingKey,
  defaults,
  invalidateKeys = []
}: UseCollectionSettingsOptions<T>) {
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: adminQueryKeys.settings(),
    queryFn: () => adminService.getSettings()
  });

  const setting = settingsQuery.data?.find((s) => s.key === settingKey);

  const initial = useMemo<T>(
    () => ({ ...defaults, ...((setting?.value as Partial<T>) ?? {}) }),
    [setting, defaults]
  );
  const [form, setForm] = useState(initial);
  const [prevInitial, setPrevInitial] = useState(initial);

  // Re-sync the form when a refetch delivers a different saved config, without an
  // effect: the render that sees a new `initial` also resets the draft.
  if (initial !== prevInitial) {
    setPrevInitial(initial);
    setForm(initial);
  }

  const mutation = useMutation({
    mutationFn: () =>
      adminService.updateSetting(settingKey, { value: form as unknown as Record<string, unknown> }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.settings() });
      for (const key of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    }
  });

  return { form, setForm, settingsQuery, mutation };
}

interface CollectionSettingsPanelProps {
  title: string;
  isLoading: boolean;
  loadError: boolean;
  isSaving: boolean;
  saveSuccess: boolean;
  saveError: boolean;
  onSave: () => void;
  children: ReactNode;
}

/**
 * UI half of the settings card: the loading/error states, the domain's own
 * fields as `children`, and the save button with its success/failure
 * feedback.
 */
export function CollectionSettingsPanel({
  title,
  isLoading,
  loadError,
  isSaving,
  saveSuccess,
  saveError,
  onSave,
  children
}: Readonly<CollectionSettingsPanelProps>) {
  if (isLoading) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  if (loadError) {
    return (
      <p className="text-danger">
        Couldn&apos;t load settings. Check your connection and reload the page.
      </p>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle asChild>
          <h2>{title}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {children}
        <div className="flex items-center gap-3">
          <Button onClick={onSave} disabled={isSaving}>
            {isSaving ? "Saving…" : "Save"}
          </Button>
          {saveSuccess && <span className="text-sm text-success">Saved</span>}
          {saveError && (
            <span className="text-sm text-danger">Save failed — check the values and try again.</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
