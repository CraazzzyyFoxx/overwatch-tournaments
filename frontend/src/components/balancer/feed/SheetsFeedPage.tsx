"use client";

import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Loader2 } from "lucide-react";

import { SaveBar } from "@/components/kit/SaveBar";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  AdminGoogleSheetFeedSyncResponse,
  AdminGoogleSheetFeedUpsertInput,
  MappingPreviewResponseV2
} from "@/types/balancer-admin.types";

import { ColumnMappingTab } from "./_components/ColumnMappingTab";
import { PreviewTab } from "./_components/PreviewTab";
import { SourceSyncTab } from "./_components/SourceSyncTab";
import { ValueMappingTab } from "./_components/ValueMappingTab";
import {
  buildMappingConfigJson,
  buildValueMappingJson,
  dedupeHeaders,
  formatParsedValue,
  parsedTargetValue,
  toFieldErrors
} from "./_components/mappingConfig";
import { useMappingState } from "./_components/useMappingState";

const PREVIEW_SAMPLE_ROWS = 5;

// D25: rendered by both the hub sub-route (tournament from the path) and the
// legacy balancer route (tournament from the ?tournament query) until T14.
export default function SheetsFeedPage({ tournamentId }: Readonly<{ tournamentId: number | null }>) {
  const queryClient = useQueryClient();

  const [sourceUrl, setSourceUrl] = useState("");
  const [title, setTitle] = useState("");
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(false);
  const [autoSyncIntervalSeconds, setAutoSyncIntervalSeconds] = useState("300");
  const [syncResult, setSyncResult] = useState<AdminGoogleSheetFeedSyncResponse | null>(null);
  const [preview, setPreview] = useState<MappingPreviewResponseV2 | null>(null);
  const [activeRowIndex, setActiveRowIndex] = useState(0);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  // Headers detected on-the-fly (auto-suggest / preview) before the feed has been
  // synced — these power the column pickers for a not-yet-saved feed.
  const [detectedHeaderKeys, setDetectedHeaderKeys] = useState<string[]>([]);
  const [sourceHasChanges, setSourceHasChanges] = useState(false);
  const loadedSourceFeedIdRef = useRef<string | null>(null);

  const mapping = useMappingState();
  const { hydrate: hydrateMapping } = mapping;

  const feedQuery = useQuery({
    queryKey: ["balancer-admin", "sheet", tournamentId],
    queryFn: () => balancerAdminService.getTournamentSheet(tournamentId as number),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  const catalogQuery = useQuery({
    queryKey: ["balancer-admin", "sheet-catalog", tournamentId],
    queryFn: () =>
      balancerAdminService.getTournamentSheetMappingCatalog(tournamentId as number, true),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false
  });

  // Hydrate once per feed id (the hook guards against clobbering unsaved edits).
  useEffect(() => {
    const catalog = catalogQuery.data;
    if (!catalog || feedQuery.isLoading) {
      return;
    }
    const feed = feedQuery.data ?? null;
    // Source/sync fields mirror the feed but are simple scalars; reset them only
    // when the underlying feed object changes identity. `hydrateMapping` is
    // ref-guarded so it never clobbers unsaved edits on a background refetch.
    startTransition(() => {
      hydrateMapping(catalog, feed, String(tournamentId));
      const feedKey = `${tournamentId}:${feed ? String(feed.id) : "__none__"}`;
      if (loadedSourceFeedIdRef.current !== feedKey) {
        loadedSourceFeedIdRef.current = feedKey;
        setSourceUrl(feed?.source_url ?? "");
        setTitle(feed?.title ?? "");
        setAutoSyncEnabled(feed?.auto_sync_enabled ?? false);
        setAutoSyncIntervalSeconds(String(feed?.auto_sync_interval_seconds ?? 300));
        setSourceHasChanges(false);
      }
    });
  }, [catalogQuery.data, feedQuery.data, feedQuery.isLoading, hydrateMapping, tournamentId]);

  // Headers come from the live feed (preferred), then headers detected via
  // auto-suggest / preview, then the catalog fallback.
  const headerKeys = useMemo(() => {
    const feedHeaders = feedQuery.data?.header_row_json;
    if (feedHeaders && feedHeaders.length > 0) {
      return dedupeHeaders(feedHeaders);
    }
    if (detectedHeaderKeys.length > 0) {
      return detectedHeaderKeys;
    }
    return catalogQuery.data?.header_keys ?? [];
  }, [feedQuery.data?.header_row_json, detectedHeaderKeys, catalogQuery.data?.header_keys]);

  // Inline preview values (preview row 0) keyed by target.
  const previewByTarget = useMemo<Record<string, string>>(() => {
    const row = preview?.rows[0];
    if (!row) {
      return {};
    }
    const result: Record<string, string> = {};
    for (const target of catalogQuery.data?.targets ?? []) {
      result[target.key] = formatParsedValue(parsedTargetValue(row.parsed_fields, target.key));
    }
    return result;
  }, [catalogQuery.data?.targets, preview]);

  const buildUpsertPayload = (): AdminGoogleSheetFeedUpsertInput => ({
    source_url: sourceUrl,
    title: title || null,
    auto_sync_enabled: autoSyncEnabled,
    auto_sync_interval_seconds: Number(autoSyncIntervalSeconds) || 300,
    mapping_config_json: buildMappingConfigJson(mapping.mappingState),
    value_mapping_json: buildValueMappingJson(mapping.valueState)
  });

  const invalidateFeed = () =>
    queryClient.invalidateQueries({ queryKey: ["balancer-admin", "sheet", tournamentId] });
  const invalidateRegistrations = () =>
    queryClient.invalidateQueries({ queryKey: ["balancer-admin", "registrations", tournamentId] });

  const saveMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.upsertTournamentSheetWithValidation(
        tournamentId as number,
        buildUpsertPayload()
      ),
    meta: { suppressErrorToast: true },
    onSuccess: async (result) => {
      if (result.ok) {
        setFieldErrors({});
        setFormError(null);
        mapping.resetChanges();
        setSourceHasChanges(false);
        await invalidateFeed();
        notify.success("Google Sheets feed saved");
        return;
      }
      setFieldErrors(toFieldErrors(result.error.errors));
      setFormError(result.error.message);
      notify.error("Mapping is invalid", { description: result.error.message });
    },
    onError: (error: Error) => {
      setFormError(error.message);
    }
  });

  const syncMutation = useMutation({
    mutationFn: () => balancerAdminService.syncTournamentSheet(tournamentId as number),
    onSuccess: async (result) => {
      setSyncResult(result);
      await Promise.all([invalidateFeed(), invalidateRegistrations()]);
      notify.success("Google Sheets sync complete", {
        description: `${result.created} created, ${result.updated} updated, ${result.withdrawn} withdrawn, ${result.skipped} skipped`
      });
    }
  });

  const suggestMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.suggestTournamentSheetMapping(tournamentId as number, {
        source_url: sourceUrl || undefined
      }),
    onSuccess: (result) => {
      // Suggest returns the live headers + a starting mapping; it does NOT persist.
      // Surface the detected headers and merge the suggestion into editor state
      // (without clobbering columns the admin already chose).
      setDetectedHeaderKeys(dedupeHeaders(result.headers));
      mapping.applySuggestedMapping(result.mapping_config_json);
      notify.success("Auto-suggest applied", {
        description: "Headers detected and a starting mapping was suggested."
      });
    }
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.previewTournamentSheetMappingRows(tournamentId as number, {
        source_url: sourceUrl || undefined,
        mapping_config_json: buildMappingConfigJson(mapping.mappingState),
        value_mapping_json: buildValueMappingJson(mapping.valueState),
        sample_rows: PREVIEW_SAMPLE_ROWS
      }),
    onSuccess: (result) => {
      setPreview(result);
      setActiveRowIndex(0);
      if (result.header_keys.length > 0) {
        setDetectedHeaderKeys(result.header_keys);
      }
    }
  });

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>
          Choose a tournament in the sidebar before configuring the Google Sheets feed.
        </AlertDescription>
      </Alert>
    );
  }

  if (feedQuery.isError || catalogQuery.isError) {
    const message =
      (feedQuery.error as Error)?.message ??
      (catalogQuery.error as Error)?.message ??
      "Reload and try again.";
    return (
      <Alert variant="destructive">
        <AlertTitle>Failed to load the Google Sheets feed</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    );
  }

  if (catalogQuery.isLoading || feedQuery.isLoading || !catalogQuery.data || !mapping.isHydrated) {
    return (
      <div className="flex flex-1 items-center justify-center py-16 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        Loading mapping…
      </div>
    );
  }

  // One feed, one save: the four sections used to sit behind in-page tabs under
  // the hub's two routed tab rows, with a second <h1> and a back button the
  // sub-tab bar already provides.

  const feed = feedQuery.data ?? null;
  const catalog = catalogQuery.data;
  const feedExists = feed !== null;
  const canSave = sourceUrl.trim().length > 0;
  const canPreview = canSave || feedExists;
  const hasChanges = mapping.hasChanges || sourceHasChanges;
  const canSync = feedExists && !hasChanges;

  const changeSourceUrl = (value: string) => {
    setSourceUrl(value);
    setSourceHasChanges(true);
  };
  const changeTitle = (value: string) => {
    setTitle(value);
    setSourceHasChanges(true);
  };
  const changeAutoSyncEnabled = (value: boolean) => {
    setAutoSyncEnabled(value);
    setSourceHasChanges(true);
  };
  const changeAutoSyncIntervalSeconds = (value: string) => {
    setAutoSyncIntervalSeconds(value);
    setSourceHasChanges(true);
  };

  const discard = () => {
    mapping.discard(catalog, feed);
    setSourceUrl(feed?.source_url ?? "");
    setTitle(feed?.title ?? "");
    setAutoSyncEnabled(feed?.auto_sync_enabled ?? false);
    setAutoSyncIntervalSeconds(String(feed?.auto_sync_interval_seconds ?? 300));
    setSourceHasChanges(false);
    setFieldErrors({});
    setFormError(null);
  };

  const save = () => {
    if (!canSave) {
      setFormError("A sheet URL is required.");
      return;
    }
    saveMutation.mutate();
  };

  return (
    <div className="flex flex-col gap-4">
      {formError ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Mapping could not be saved</AlertTitle>
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      ) : null}

      <SourceSyncTab
        feed={feed}
        sourceUrl={sourceUrl}
        title={title}
        autoSyncEnabled={autoSyncEnabled}
        autoSyncIntervalSeconds={autoSyncIntervalSeconds}
        syncResult={syncResult}
        isSyncing={syncMutation.isPending}
        canSync={canSync}
        onChangeSourceUrl={changeSourceUrl}
        onChangeTitle={changeTitle}
        onChangeAutoSyncEnabled={changeAutoSyncEnabled}
        onChangeAutoSyncIntervalSeconds={changeAutoSyncIntervalSeconds}
        onSync={() => syncMutation.mutate()}
      />

      <ColumnMappingTab
        catalog={catalog}
        mappingState={mapping.mappingState}
        headerKeys={headerKeys}
        previewByTarget={previewByTarget}
        errorsByTarget={fieldErrors}
        isSuggesting={suggestMutation.isPending}
        onSuggest={() => suggestMutation.mutate()}
        onModeChange={mapping.setTargetMode}
        onColumnsChange={mapping.setTargetColumns}
        onValueChange={mapping.setTargetValue}
        onParserChange={mapping.setTargetParser}
        onIsListChange={mapping.setTargetIsList}
      />

      <ValueMappingTab
        valueState={mapping.valueState}
        valueCategories={catalog.value_categories}
        subroleCatalog={catalog.subrole_catalog ?? {}}
        onAdd={mapping.addValueRow}
        onUpdate={mapping.updateValueRow}
        onRemove={mapping.removeValueRow}
        onSeedDefaults={mapping.seedValueDefaults}
      />

      <PreviewTab
        catalog={catalog}
        mappingState={mapping.mappingState}
        preview={preview}
        activeRowIndex={activeRowIndex}
        isRefreshing={previewMutation.isPending}
        canPreview={canPreview}
        onRefresh={() => previewMutation.mutate()}
        onChangeRow={setActiveRowIndex}
      />

      {/* Same SaveBar as every settings section: present only while dirty, with
          the shared unsaved-navigation guard. A tournament with no feed yet
          becomes dirty the moment a URL is typed, which is also the first
          moment "Create feed" could succeed. */}
      <SaveBar
        dirty={hasChanges}
        saving={saveMutation.isPending}
        primaryLabel={feedExists ? "Save changes" : "Create feed"}
        summary={
          canSave
            ? feedExists
              ? "Unsaved feed changes"
              : "New Google Sheets feed"
            : "A sheet URL is required"
        }
        onDiscard={discard}
        onSave={save}
      />
    </div>
  );
}
