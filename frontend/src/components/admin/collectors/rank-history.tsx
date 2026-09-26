"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useFormatter } from "@/lib/datetime/client";

import { ClickableLogCell, ClickableLogRow } from "@/components/admin/ClickableLogRow";
import { LiveIndicator } from "@/components/admin/LiveIndicator";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

import { StatusBadge, formatDate } from "./rank-shared";
import { EmptyNote } from "@/components/kit/EmptyNote";

const STATUS_FILTERS = ["all", "ok", "private", "not_found", "error", "rate_limited"];
const SOURCE_FILTERS = ["all", "scheduled", "registration", "manual"];

/**
 * Live OverFast worker fetch log.
 *
 * Rows that resolve to a known player link through to that person's page:
 * per-player inspection is People's job now (F14 ·3), so this screen stays
 * about the worker and hands the drill-down off instead of growing a second
 * detail surface below the fold.
 */
export function RankTaskHistory() {
  const format = useFormatter();
  const [status, setStatus] = useState("all");
  const [source, setSource] = useState("all");
  // Rows come back scoped to the workspace `apiFetch` injects — key on it so a
  // workspace switch refetches instead of showing the previous tenant's history.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const query = useQuery({
    queryKey: ["admin", "rank", "fetch-log", workspaceId, status, source],
    queryFn: () =>
      adminService.getRankFetchLog({
        status: status === "all" ? undefined : status,
        source: source === "all" ? undefined : source,
        limit: 50
      }),
    refetchInterval: 3000
  });
  const rows = query.data ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div className="flex items-center gap-2">
          <CardTitle asChild>
            <h2>Task history</h2>
          </CardTitle>
          <LiveIndicator />
        </div>
        <div className="flex items-center gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-8 w-36 text-xs" aria-label="Filter by status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {value === "all" ? "All statuses" : value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="h-8 w-40 text-xs" aria-label="Filter by source">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SOURCE_FILTERS.map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {value === "all" ? "All sources" : value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : rows.length === 0 ? (
          <EmptyNote>
            No fetch tasks recorded yet. The worker logs a row here each time it queries OverFast —
            resume collection or collect a single player to see activity.
          </EmptyNote>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Battle tag</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Snapshots</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const href = row.user_id == null ? null : `/admin/people/${row.user_id}`;
                  return (
                    <ClickableLogRow key={row.id} href={href}>
                      <TableCell className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                        {formatDate(format, row.created_at)}
                      </TableCell>
                      <ClickableLogCell href={href} label={row.battle_tag} />
                      <TableCell>
                        <StatusBadge status={row.status} />
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{row.source}</TableCell>
                      <TableCell className="text-right text-sm tabular-nums">
                        {row.snapshots_written || "—"}
                      </TableCell>
                      <TableCell
                        className="max-w-64 truncate text-xs text-danger"
                        title={row.error ?? undefined}
                      >
                        {row.error ?? "—"}
                      </TableCell>
                    </ClickableLogRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
