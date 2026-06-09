"use client";

import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Loader2, Save } from "lucide-react";

import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  AdminGoogleSheetFeedSyncResponse,
  AdminGoogleSheetFeedUpsertInput,
  MappingPreviewResponseV2,
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
  toFieldErrors,
} from "./_components/mappingConfig";
import { useMappingState } from "./_components/useMappingState";

const PREVIEW_SAMPLE_ROWS = 5;

export default function BalancerRegistrationsFeedPage() {
  const tournamentId = useBalancerTournamentId();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();

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
    refetchOnWindowFocus: false,
  });

  const catalogQuery = useQuery({
    queryKey: ["balancer-admin", "sheet-catalog", tournamentId],
    queryFn: () => balancerAdminService.getTournamentSheetMappingCatalog(tournamentId as number, true),
    enabled: tournamentId !== null,
    refetchOnWindowFocus: false,
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
    value_mapping_json: buildValueMappingJson(mapping.valueState),
  });

  const invalidateFeed = () =>
    queryClient.invalidateQueries({ queryKey: ["balancer-admin", "sheet", tournamentId] });
  const invalidateRegistrations = () =>
    queryClient.invalidateQueries({ queryKey: ["balancer-admin", "registrations", tournamentId] });

  const saveMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.upsertTournamentSheetWithValidation(tournamentId as number, buildUpsertPayload()),
    onSuccess: async (result) => {
      if (result.ok) {
        setFieldErrors({});
        setFormError(null);
        mapping.resetChanges();
        setSourceHasChanges(false);
        await invalidateFeed();
        toast({ title: "Google Sheets feed saved" });
        return;
      }
      setFieldErrors(toFieldErrors(result.error.errors));
      setFormError(result.error.message);
      toast({ title: "Mapping is invalid", description: result.error.message, variant: "destructive" });
    },
    onError: (error: Error) => {
      setFormError(error.message);
      toast({ title: "Failed to save feed", description: error.message, variant: "destructive" });
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => balancerAdminService.syncTournamentSheet(tournamentId as number),
    onSuccess: async (result) => {
      setSyncResult(result);
      await Promise.all([invalidateFeed(), invalidateRegistrations()]);
      toast({
        title: "Google Sheets sync complete",
        description: `${result.created} created, ${result.updated} updated, ${result.withdrawn} withdrawn, ${result.skipped} skipped`,
      });
    },
    onError: (error: Error) => {
      toast({ title: "Sync failed", description: error.message, variant: "destructive" });
    },
  });

  const suggestMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.suggestTournamentSheetMapping(tournamentId as number, {
        source_url: sourceUrl || undefined,
      }),
    onSuccess: (result) => {
      // Suggest returns the live headers + a starting mapping; it does NOT persist.
      // Surface the detected headers and merge the suggestion into editor state
      // (without clobbering columns the admin already chose).
      setDetectedHeaderKeys(dedupeHeaders(result.headers));
      mapping.applySuggestedMapping(result.mapping_config_json);
      toast({ title: "Auto-suggest applied", description: "Headers detected and a starting mapping was suggested." });
    },
    onError: (error: Error) => {
      toast({ title: "Auto-suggest failed", description: error.message, variant: "destructive" });
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.previewTournamentSheetMappingRows(tournamentId as number, {
        source_url: sourceUrl || undefined,
        mapping_config_json: buildMappingConfigJson(mapping.mappingState),
        value_mapping_json: buildValueMappingJson(mapping.valueState),
        sample_rows: PREVIEW_SAMPLE_ROWS,
      }),
    onSuccess: (result) => {
      setPreview(result);
      setActiveRowIndex(0);
      if (result.header_keys.length > 0) {
        setDetectedHeaderKeys(result.header_keys);
      }
    },
    onError: (error: Error) => {
      toast({ title: "Preview failed", description: error.message, variant: "destructive" });
    },
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
      (feedQuery.error as Error)?.message ?? (catalogQuery.error as Error)?.message ?? "Reload and try again.";
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

  const registrationsHref = searchParams.toString()
    ? `/balancer/registrations?${searchParams.toString()}`
    : "/balancer/registrations";

  const feedExists = feedQuery.data != null;
  const canSave = sourceUrl.trim().length > 0;
  const canPreview = sourceUrl.trim().length > 0 || feedExists;
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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Google Sheets Feed</h1>
            <p className="text-sm text-muted-foreground">
              Configure the source, map columns visually, translate values, and preview parsed rows.
            </p>
          </div>
          <Button variant="outline" asChild>
            <Link href={registrationsHref}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to registrations
            </Link>
          </Button>
        </div>

        {formError ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Mapping could not be saved</AlertTitle>
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        ) : null}

        <Tabs defaultValue="source" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="self-start">
            <TabsTrigger value="source">Source &amp; Sync</TabsTrigger>
            <TabsTrigger value="columns">Column Mapping</TabsTrigger>
            <TabsTrigger value="values">Value Mapping</TabsTrigger>
            <TabsTrigger value="preview">Preview</TabsTrigger>
          </TabsList>

          <TabsContent value="source">
            <SourceSyncTab
              feed={feedQuery.data}
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
          </TabsContent>

          <TabsContent value="columns">
            <ColumnMappingTab
              catalog={catalogQuery.data}
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
            />
          </TabsContent>

          <TabsContent value="values">
            <ValueMappingTab
              valueState={mapping.valueState}
              valueCategories={catalogQuery.data.value_categories}
              onAdd={mapping.addValueRow}
              onUpdate={mapping.updateValueRow}
              onRemove={mapping.removeValueRow}
              onSeedDefaults={mapping.seedValueDefaults}
            />
          </TabsContent>

          <TabsContent value="preview">
            <PreviewTab
              catalog={catalogQuery.data}
              mappingState={mapping.mappingState}
              preview={preview}
              activeRowIndex={activeRowIndex}
              isRefreshing={previewMutation.isPending}
              canPreview={canPreview}
              onRefresh={() => previewMutation.mutate()}
              onChangeRow={setActiveRowIndex}
            />
          </TabsContent>
        </Tabs>
      </div>

      <div className="flex items-center justify-end gap-3 border-t bg-background/95 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        {hasChanges ? (
          <span className="text-xs text-muted-foreground">Unsaved changes</span>
        ) : null}
        <Button
          size="lg"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !canSave || (!hasChanges && feedExists)}
        >
          {saveMutation.isPending ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <Save className="mr-2 size-4" />
          )}
          {feedExists ? "Save changes" : "Create feed"}
        </Button>
      </div>
    </div>
  );
}
