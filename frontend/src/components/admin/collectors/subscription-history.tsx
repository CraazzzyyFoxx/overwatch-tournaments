"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useFormatter } from "next-intl";

import { ClickableLogCell, ClickableLogRow } from "@/components/admin/ClickableLogRow";
import { LiveIndicator } from "@/components/admin/LiveIndicator";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SocialIcon } from "@/components/social/SocialIcon";
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
import { useWorkspaceStore } from "@/stores/workspace.store";

import {
  PROVIDER_LABELS,
  REASON_LABELS,
  SOURCE_LABELS,
  STATE_LABELS,
  StateBadge,
  formatDate
} from "./subscription-shared";
import { EmptyNote } from "@/components/kit/EmptyNote";

const STATE_FILTERS = ["all", "active", "inactive", "unknown", "error"];
const SOURCE_FILTERS = ["all", "scheduled", "registration", "check_in", "manual", "redeem"];
const PROVIDER_FILTERS = ["all", "boosty", "twitch"];

/**
 * Live subscription check history — one row per real provider call.
 *
 * This is the view the subscription domain had no data for: `entitlement` is
 * overwritten in place on every check, so before `check_log` existed there was
 * no way to see that a player flapped, when a provider went down, or why a
 * registration was refused. Rows that resolve to a player link through to that
 * person's page (F14 ·3) rather than opening a detail panel here.
 */
export function SubscriptionTaskHistory() {
  const format = useFormatter();
  const [state, setState] = useState("all");
  const [source, setSource] = useState("all");
  const [provider, setProvider] = useState("all");
  // Rows come back scoped to the workspace `apiFetch` injects — key on it so a
  // workspace switch refetches instead of showing the previous tenant's history.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const query = useQuery({
    queryKey: ["admin", "subscriptions", "check-log", workspaceId, state, source, provider],
    queryFn: () =>
      adminService.getSubscriptionCheckLog({
        state: state === "all" ? undefined : state,
        source: source === "all" ? undefined : source,
        provider: provider === "all" ? undefined : provider,
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
            <h2>Check history</h2>
          </CardTitle>
          <LiveIndicator />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={state} onValueChange={setState}>
            <SelectTrigger className="h-8 w-32 text-xs" aria-label="Filter by state">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATE_FILTERS.map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {value === "all" ? "All states" : (STATE_LABELS[value] ?? value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={provider} onValueChange={setProvider}>
            <SelectTrigger className="h-8 w-36 text-xs" aria-label="Filter by provider">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROVIDER_FILTERS.map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {value === "all" ? (
                    "All providers"
                  ) : (
                    <span className="flex items-center gap-2">
                      <SocialIcon provider={value} size={12} decorative />
                      <span>{PROVIDER_LABELS[value] ?? value}</span>
                    </span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="h-8 w-40 text-xs" aria-label="Filter by trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SOURCE_FILTERS.map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {value === "all" ? "All triggers" : (SOURCE_LABELS[value] ?? value)}
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
            No subscription checks recorded yet. A row lands here each time a provider is actually
            queried — resume collection, run &ldquo;Check all now&rdquo;, or wait for a player to
            register in a tournament that requires a subscription.
          </EmptyNote>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Player</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Tier</TableHead>
                  <TableHead>Trigger</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const href = row.user_id == null ? null : `/admin/people/${row.user_id}`;
                  const label = row.user_name ?? `auth #${row.auth_user_id ?? "?"}`;
                  const reason =
                    row.error ?? (row.reason ? (REASON_LABELS[row.reason] ?? row.reason) : null);
                  return (
                    <ClickableLogRow key={row.id} href={href}>
                      <TableCell className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                        {formatDate(format, row.created_at)}
                      </TableCell>
                      <ClickableLogCell href={href} label={label} />
                      <TableCell className="text-sm">
                        <span className="flex items-center gap-2">
                          <SocialIcon provider={row.provider} size={14} decorative />
                          <span>{PROVIDER_LABELS[row.provider] ?? row.provider}</span>
                        </span>
                      </TableCell>
                      <TableCell>
                        <StateBadge state={row.state} />
                      </TableCell>
                      <TableCell className="text-xs tabular-nums text-muted-foreground">
                        {row.tier_label ?? (row.tier_rank != null ? `Tier ${row.tier_rank}` : "—")}
                      </TableCell>
                      <TableCell
                        className="text-xs text-muted-foreground"
                        title={row.mechanism ?? undefined}
                      >
                        {SOURCE_LABELS[row.source] ?? row.source}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "max-w-64 truncate text-xs",
                          row.error ? "text-danger" : "text-muted-foreground"
                        )}
                        title={row.error ?? row.reason ?? undefined}
                      >
                        {reason ?? "—"}
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
