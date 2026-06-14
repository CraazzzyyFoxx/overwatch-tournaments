"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { AdminGoogleSheetFeed } from "@/types/balancer-admin.types";

function statusVariant(status: string | null | undefined): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "ok":
    case "success":
      return "default";
    case "error":
    case "failed":
      return "destructive";
    default:
      return "outline";
  }
}

interface FeedStatusCardProps {
  feed: AdminGoogleSheetFeed | null | undefined;
}

/** Lifted from the original page's `FeedStatus`, wrapped in a Card. */
export function FeedStatusCard({ feed }: FeedStatusCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sync status</CardTitle>
        <CardDescription>The current state and sync history of this Google Sheet integration.</CardDescription>
      </CardHeader>
      <CardContent>
        {!feed ? (
          <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            No Google Sheets feed configured yet.
          </div>
        ) : (
          <div className="space-y-3 rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant(feed.last_sync_status)}>
                {feed.last_sync_status ?? "pending"}
              </Badge>
              <span className="text-muted-foreground">
                Last sync: {feed.last_synced_at ? new Date(feed.last_synced_at).toLocaleString() : "never"}
              </span>
            </div>
            {feed.last_error ? <p className="text-sm text-destructive">{feed.last_error}</p> : null}
            {feed.header_row_json?.length ? (
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
                  Detected headers ({feed.header_row_json.length})
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {feed.header_row_json.map((header, index) => (
                    <Badge key={`${header}-${index}`} variant="secondary" className="font-normal">
                      {header}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                No headers detected yet — run a sync or auto-suggest to read the header row.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
