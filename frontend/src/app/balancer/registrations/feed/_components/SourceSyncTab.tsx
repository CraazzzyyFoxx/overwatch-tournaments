"use client";

import { Loader2, RefreshCcw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  AdminGoogleSheetFeed,
  AdminGoogleSheetFeedSyncResponse,
} from "@/types/balancer-admin.types";

import { FeedStatusCard } from "./FeedStatusCard";

interface SourceSyncTabProps {
  feed: AdminGoogleSheetFeed | null | undefined;
  sourceUrl: string;
  title: string;
  autoSyncEnabled: boolean;
  autoSyncIntervalSeconds: string;
  syncResult: AdminGoogleSheetFeedSyncResponse | null;
  isSyncing: boolean;
  canSync: boolean;
  onChangeSourceUrl: (value: string) => void;
  onChangeTitle: (value: string) => void;
  onChangeAutoSyncEnabled: (value: boolean) => void;
  onChangeAutoSyncIntervalSeconds: (value: string) => void;
  onSync: () => void;
}

export function SourceSyncTab({
  feed,
  sourceUrl,
  title,
  autoSyncEnabled,
  autoSyncIntervalSeconds,
  syncResult,
  isSyncing,
  canSync,
  onChangeSourceUrl,
  onChangeTitle,
  onChangeAutoSyncEnabled,
  onChangeAutoSyncIntervalSeconds,
  onSync,
}: SourceSyncTabProps) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Source</CardTitle>
          <CardDescription>Where registrations are read from and how often the worker re-syncs.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="sheet-url">Sheet URL</Label>
            <Input
              id="sheet-url"
              value={sourceUrl}
              onChange={(event) => onChangeSourceUrl(event.target.value)}
              placeholder="https://docs.google.com/spreadsheets/..."
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="sheet-title">Title</Label>
            <Input
              id="sheet-title"
              value={title}
              onChange={(event) => onChangeTitle(event.target.value)}
              placeholder="Optional label"
            />
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_180px]">
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <div>
                <p className="text-sm font-medium">Auto-sync</p>
                <p className="text-xs text-muted-foreground">Run periodic feed sync in the parser worker.</p>
              </div>
              <Switch checked={autoSyncEnabled} onCheckedChange={onChangeAutoSyncEnabled} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sheet-interval">Interval (seconds)</Label>
              <Input
                id="sheet-interval"
                inputMode="numeric"
                value={autoSyncIntervalSeconds}
                onChange={(event) => onChangeAutoSyncIntervalSeconds(event.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={onSync} disabled={isSyncing || !canSync}>
              {isSyncing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCcw className="mr-2 h-4 w-4" />
              )}
              Sync now
            </Button>
            {!canSync ? (
              <span className="text-xs text-muted-foreground">
                Save the feed and any pending changes before syncing.
              </span>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <FeedStatusCard feed={feed} />

      {syncResult ? (
        <Card>
          <CardHeader>
            <CardTitle>Last sync result</CardTitle>
            <CardDescription>Outcome of the most recent manual sync.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                { label: "Created", value: syncResult.created },
                { label: "Updated", value: syncResult.updated },
                { label: "Withdrawn", value: syncResult.withdrawn },
                { label: "Skipped", value: syncResult.skipped },
                { label: "Total", value: syncResult.total },
              ].map((stat) => (
                <div key={stat.label} className="rounded-lg border px-3 py-2 text-center">
                  <p className="text-lg font-semibold tabular-nums">{stat.value}</p>
                  <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{stat.label}</p>
                </div>
              ))}
            </div>
            {syncResult.errors.length > 0 ? (
              <Alert variant="destructive">
                <AlertTitle>
                  {syncResult.errors.length} row error{syncResult.errors.length === 1 ? "" : "s"}
                </AlertTitle>
                <AlertDescription>
                  <ul className="mt-1 space-y-1">
                    {syncResult.errors.map((error, index) => (
                      <li key={`${error.target ?? "row"}-${index}`} className="text-xs">
                        {error.row_index != null ? <span className="font-medium">Row {error.row_index}: </span> : null}
                        {error.target ? <span className="font-mono">{error.target}</span> : null}
                        {error.column ? <span className="text-muted-foreground"> ({error.column})</span> : null}
                        {error.target || error.column ? " — " : ""}
                        {error.message}
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
