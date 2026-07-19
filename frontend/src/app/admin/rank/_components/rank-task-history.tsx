"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";

import { StatusBadge, formatDate } from "./rank-shared";

const STATUS_FILTERS = ["all", "ok", "private", "not_found", "error", "rate_limited"];
const SOURCE_FILTERS = ["all", "scheduled", "registration", "manual"];

interface RankTaskHistoryProps {
  onSelectUser: (userId: number, label: string) => void;
}

/** Live OverFast worker fetch log. Rows resolve to a player (when known) and are
 *  clickable through to that player's detail. */
export function RankTaskHistory({ onSelectUser }: RankTaskHistoryProps) {
  const [status, setStatus] = useState("all");
  const [source, setSource] = useState("all");

  const query = useQuery({
    queryKey: ["admin", "rank", "fetch-log", status, source],
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
        <CardTitle className="flex items-center gap-2">
          Task history
          <span className="flex items-center gap-1 text-xs font-normal text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            live
          </span>
        </CardTitle>
        <div className="flex items-center gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-8 w-[140px] text-xs">
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
            <SelectTrigger className="h-8 w-[150px] text-xs">
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
          <p className="text-sm text-muted-foreground">No fetch tasks recorded yet.</p>
        ) : (
          <div className="max-h-[420px] overflow-y-auto">
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
                  const clickable = row.user_id != null;
                  return (
                    <TableRow
                      key={row.id}
                      className={cn(clickable && "cursor-pointer hover:bg-muted/50")}
                      onClick={clickable ? () => onSelectUser(row.user_id as number, row.battle_tag) : undefined}
                    >
                      <TableCell className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                        {formatDate(row.created_at)}
                      </TableCell>
                      <TableCell className={cn("font-medium", clickable && "text-[color:var(--aqt-teal)] underline-offset-2 hover:underline")}>
                        {row.battle_tag}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={row.status} />
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{row.source}</TableCell>
                      <TableCell className="text-right text-sm tabular-nums">{row.snapshots_written || "—"}</TableCell>
                      <TableCell
                        className="max-w-[260px] truncate text-xs text-rose-300/70"
                        title={row.error ?? undefined}
                      >
                        {row.error ?? "—"}
                      </TableCell>
                    </TableRow>
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
