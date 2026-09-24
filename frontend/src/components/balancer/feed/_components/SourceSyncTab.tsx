"use client";

import { ChevronRight, RefreshCcw } from "lucide-react";
import { useFormatter } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS, type Tone } from "@/components/kit/tone";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  AdminGoogleSheetFeed,
  AdminGoogleSheetFeedSyncResponse,
} from "@/types/balancer-admin.types";
import { Spinner } from "@/components/ui/spinner";

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

function statusTone(status: string | null | undefined): Tone {
  switch (status) {
    case "ok":
    case "success":
      return "success";
    case "error":
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}

/**
 * Source, sync status and the last sync outcome — one card. The three used to
 * be stacked cards each stretching its inputs across the whole hub width; the
 * status is a header fact, not a section.
 */
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
}: Readonly<SourceSyncTabProps>) {
  const format = useFormatter();
  const headers = feed?.header_row_json ?? [];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle>Source</CardTitle>
          <CardDescription>Where registrations are read from and how often the worker re-syncs.</CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {feed ? (
            <>
              <StatusPill tone={statusTone(feed.last_sync_status)} dot>
                {feed.last_sync_status ?? "pending"}
              </StatusPill>
              <span className="text-xs text-muted-foreground">
                Last sync{" "}
                {feed.last_synced_at
                  ? format.dateTime(new Date(feed.last_synced_at), {
                      dateStyle: "medium",
                      timeStyle: "short"
                    })
                  : "never"}
              </span>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">No feed yet</span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={onSync}
            disabled={isSyncing || !canSync}
            title={canSync ? undefined : "Save the feed and any pending changes before syncing."}
          >
            {isSyncing ? (
              <Spinner className="mr-2" />
            ) : (
              <RefreshCcw className="mr-2 size-4" />
            )}
            Sync now
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
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
        </div>

        <div className="flex flex-wrap items-center gap-4 rounded-lg border px-3 py-2">
          <Switch
            id="sheet-auto-sync"
            checked={autoSyncEnabled}
            onCheckedChange={onChangeAutoSyncEnabled}
          />
          <div className="min-w-0 flex-1">
            <Label htmlFor="sheet-auto-sync" className="text-sm font-medium">
              Auto-sync
            </Label>
            <p className="text-xs text-muted-foreground">Run periodic feed sync in the parser worker.</p>
          </div>
          <Label htmlFor="sheet-interval" className="flex items-center gap-2 text-sm font-normal text-muted-foreground">
            every
            <Input
              id="sheet-interval"
              inputMode="numeric"
              value={autoSyncIntervalSeconds}
              onChange={(event) => onChangeAutoSyncIntervalSeconds(event.target.value)}
              disabled={!autoSyncEnabled}
              className="h-8 w-20 text-right tabular-nums"
            />
            seconds
          </Label>
        </div>

        {feed?.last_error ? <p className="text-sm text-danger">{feed.last_error}</p> : null}

        {headers.length > 0 ? (
          <details className="group">
            <summary className={`${EYEBROW_CLASS} inline-flex cursor-pointer list-none items-center gap-1 rounded focus-visible:outline-2 focus-visible:outline-offset-2`}>
              <ChevronRight className="size-3 transition-transform group-open:rotate-90" aria-hidden />
              {headers.length} detected header{headers.length === 1 ? "" : "s"}
            </summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {headers.map((header, index) => (
                <Badge key={`${header}-${index}`} variant="secondary" className="font-normal">
                  {header}
                </Badge>
              ))}
            </div>
          </details>
        ) : null}

        {syncResult ? (
          <div className="space-y-3 border-t pt-4">
            <dl className="flex flex-wrap gap-x-6 gap-y-2">
              {[
                { label: "Created", value: syncResult.created },
                { label: "Updated", value: syncResult.updated },
                { label: "Withdrawn", value: syncResult.withdrawn },
                { label: "Skipped", value: syncResult.skipped },
                { label: "Total", value: syncResult.total },
              ].map((stat) => (
                <div key={stat.label} className="flex items-baseline gap-1.5">
                  <dt className={EYEBROW_CLASS}>{stat.label}</dt>
                  <dd className="text-lg font-semibold tabular-nums">{stat.value}</dd>
                </div>
              ))}
            </dl>
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
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
