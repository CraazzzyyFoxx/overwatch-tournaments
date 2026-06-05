"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Globe, Loader2, RefreshCcw, Search, UploadCloud } from "lucide-react";

import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import balancerAdminService from "@/services/balancer-admin.service";
import type { AdminGoogleSheetFeed, AdminGoogleSheetMappingPreviewResponse } from "@/types/balancer-admin.types";

function parseObjectInput(value: string): Record<string, unknown> | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON value must be an object");
  }
  return parsed as Record<string, unknown>;
}

function FeedStatus({ feed }: { feed: AdminGoogleSheetFeed | null | undefined }) {
  if (!feed) {
    return (
      <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
        No Google Sheets feed configured yet.
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{feed.last_sync_status ?? "pending"}</Badge>
        <span className="text-muted-foreground">
          Last sync: {feed.last_synced_at ? new Date(feed.last_synced_at).toLocaleString() : "never"}
        </span>
      </div>
      {feed.last_error ? <p className="mt-2 text-sm text-destructive">{feed.last_error}</p> : null}
      {feed.header_row_json?.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Headers detected: {feed.header_row_json.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

export default function BalancerRegistrationsFeedPage() {
  const tournamentId = useBalancerTournamentId();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [sheetUrl, setSheetUrl] = useState("");
  const [sheetTitle, setSheetTitle] = useState("");
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(false);
  const [autoSyncIntervalSeconds, setAutoSyncIntervalSeconds] = useState("300");
  const [mappingJson, setMappingJson] = useState("");
  const [valueMappingJson, setValueMappingJson] = useState("");
  const [mappingPreview, setMappingPreview] = useState<AdminGoogleSheetMappingPreviewResponse | null>(null);

  const feedQuery = useQuery({
    queryKey: ["balancer-admin", "sheet", tournamentId],
    queryFn: () => balancerAdminService.getTournamentSheet(tournamentId as number),
    enabled: tournamentId !== null,
  });

  useEffect(() => {
    const feed = feedQuery.data;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSheetUrl(feed?.source_url ?? "");
    setSheetTitle(feed?.title ?? "");
    setAutoSyncEnabled(feed?.auto_sync_enabled ?? false);
    setAutoSyncIntervalSeconds(String(feed?.auto_sync_interval_seconds ?? 300));
    setMappingJson(feed?.mapping_config_json ? JSON.stringify(feed.mapping_config_json, null, 2) : "");
    setValueMappingJson(feed?.value_mapping_json ? JSON.stringify(feed.value_mapping_json, null, 2) : "");
    setMappingPreview(null);
  }, [feedQuery.data]);

  const invalidateFeed = async () => {
    await queryClient.invalidateQueries({ queryKey: ["balancer-admin", "sheet", tournamentId] });
  };

  const invalidateRegistrations = async () => {
    await queryClient.invalidateQueries({ queryKey: ["balancer-admin", "registrations", tournamentId] });
  };

  const saveFeedMutation = useMutation({
    mutationFn: async () =>
      balancerAdminService.upsertTournamentSheet(tournamentId as number, {
        source_url: sheetUrl,
        title: sheetTitle || null,
        auto_sync_enabled: autoSyncEnabled,
        auto_sync_interval_seconds: Number(autoSyncIntervalSeconds) || 300,
        mapping_config_json: parseObjectInput(mappingJson),
        value_mapping_json: parseObjectInput(valueMappingJson),
      }),
    onSuccess: async () => {
      await invalidateFeed();
      toast({ title: "Google Sheets feed saved" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to save feed", description: error.message, variant: "destructive" });
    },
  });

  const syncFeedMutation = useMutation({
    mutationFn: () => balancerAdminService.syncTournamentSheet(tournamentId as number),
    onSuccess: async (result) => {
      await Promise.all([invalidateFeed(), invalidateRegistrations()]);
      toast({
        title: "Google Sheets sync complete",
        description: `${result.created} created, ${result.updated} updated, ${result.withdrawn} withdrawn`,
      });
    },
    onError: (error: Error) => {
      toast({ title: "Sync failed", description: error.message, variant: "destructive" });
    },
  });

  const suggestMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.suggestTournamentSheetMapping(tournamentId as number, {
        source_url: sheetUrl || undefined,
      }),
    onSuccess: (result) => {
      setMappingJson(JSON.stringify(result.mapping_config_json, null, 2));
      toast({ title: "Suggested mapping applied to editor" });
    },
    onError: (error: Error) => {
      toast({ title: "Suggest mapping failed", description: error.message, variant: "destructive" });
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.previewTournamentSheetMapping(tournamentId as number, {
        source_url: sheetUrl || undefined,
        mapping_config_json: parseObjectInput(mappingJson),
        value_mapping_json: parseObjectInput(valueMappingJson),
      }),
    onSuccess: (result) => {
      setMappingPreview(result);
    },
    onError: (error: Error) => {
      toast({ title: "Preview failed", description: error.message, variant: "destructive" });
    },
  });

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>Choose a tournament in the sidebar before configuring the Google Sheets feed.</AlertDescription>
      </Alert>
    );
  }

  const registrationsHref = searchParams.toString()
    ? `/balancer/registrations?${searchParams.toString()}`
    : "/balancer/registrations";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Google Sheets Feed</h1>
          <p className="text-sm text-muted-foreground">
            Configure the Google Sheets integration, mapping, and sync flow for this tournament.
          </p>
        </div>
        <Button variant="outline" asChild>
          <Link href={registrationsHref}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to registrations
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Sync Status</CardTitle>
          <CardDescription>The current state and sync history of this Google Sheet integration.</CardDescription>
        </CardHeader>
        <CardContent>
          <FeedStatus feed={feedQuery.data} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Feed Configuration</CardTitle>
          <CardDescription>Saved mapping is authoritative. Use suggest only as a starting point.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="sheet-url">Sheet URL</Label>
            <Input
              id="sheet-url"
              value={sheetUrl}
              onChange={(event) => setSheetUrl(event.target.value)}
              placeholder="https://docs.google.com/spreadsheets/..."
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="sheet-title">Title</Label>
            <Input
              id="sheet-title"
              value={sheetTitle}
              onChange={(event) => setSheetTitle(event.target.value)}
              placeholder="Optional label"
            />
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_160px]">
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <div>
                <p className="text-sm font-medium">Auto-sync</p>
                <p className="text-xs text-muted-foreground">Run periodic feed sync in the parser worker.</p>
              </div>
              <Switch checked={autoSyncEnabled} onCheckedChange={setAutoSyncEnabled} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sheet-interval">Interval (seconds)</Label>
              <Input
                id="sheet-interval"
                value={autoSyncIntervalSeconds}
                onChange={(event) => setAutoSyncIntervalSeconds(event.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="mapping-json">Mapping JSON</Label>
            <Textarea
              id="mapping-json"
              value={mappingJson}
              onChange={(event) => setMappingJson(event.target.value)}
              className="min-h-[220px] font-mono text-xs"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="value-mapping-json">Value mapping JSON</Label>
            <Textarea
              id="value-mapping-json"
              value={valueMappingJson}
              onChange={(event) => setValueMappingJson(event.target.value)}
              className="min-h-[180px] font-mono text-xs"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => suggestMutation.mutate()} disabled={suggestMutation.isPending}>
              <Search className="mr-2 h-4 w-4" />
              Suggest mapping
            </Button>
            <Button variant="outline" onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending}>
              <Globe className="mr-2 h-4 w-4" />
              Preview mapping
            </Button>
            <Button variant="outline" onClick={() => syncFeedMutation.mutate()} disabled={syncFeedMutation.isPending}>
              {syncFeedMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
              Sync now
            </Button>
            <Button onClick={() => saveFeedMutation.mutate()} disabled={saveFeedMutation.isPending || !sheetUrl.trim()}>
              {saveFeedMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <UploadCloud className="mr-2 h-4 w-4" />}
              Save feed
            </Button>
          </div>

          {mappingPreview ? (
            <div className="space-y-2 rounded-lg border p-3">
              <p className="text-sm font-medium">Preview</p>
              <Textarea readOnly value={JSON.stringify(mappingPreview, null, 2)} className="min-h-[220px] font-mono text-xs" />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
