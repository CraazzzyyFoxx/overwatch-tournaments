"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, RotateCcw, Search } from "lucide-react";

import UserRankHistory from "@/components/UserRankHistory";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import userService from "@/services/user.service";
import type { MinimizedUser } from "@/types/user.types";

const STATUS_STYLES: Record<string, string> = {
  ok: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
  private: "border-amber-500/20 bg-amber-500/10 text-amber-300",
  not_found: "border-amber-500/20 bg-amber-500/10 text-amber-300",
  error: "border-rose-500/20 bg-rose-500/10 text-rose-300",
  rate_limited: "border-orange-500/20 bg-orange-500/10 text-orange-300",
  disabled: "border-white/10 bg-white/5 text-white/50",
  pending: "border-sky-500/20 bg-sky-500/10 text-sky-300"
};

const STATUS_FILTERS = ["all", "ok", "private", "not_found", "error", "rate_limited"];
const SOURCE_FILTERS = ["all", "scheduled", "registration", "manual"];

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function StatusBadge({ status }: { status: string | null }) {
  return (
    <Badge
      variant="outline"
      className={STATUS_STYLES[status ?? ""] ?? "border-white/10 bg-white/5 text-white/50"}
    >
      {status ?? "never"}
    </Badge>
  );
}

function FetchLogSection() {
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
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                      {formatDate(row.created_at)}
                    </TableCell>
                    <TableCell className="font-medium">{row.battle_tag}</TableCell>
                    <TableCell>
                      <StatusBadge status={row.status} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{row.source}</TableCell>
                    <TableCell className="text-right text-sm tabular-nums">
                      {row.snapshots_written || "—"}
                    </TableCell>
                    <TableCell
                      className="max-w-[260px] truncate text-xs text-rose-300/70"
                      title={row.error ?? undefined}
                    >
                      {row.error ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PlayerSearchSection({ onSelect }: { onSelect: (user: MinimizedUser) => void }) {
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(term.trim()), 300);
    return () => clearTimeout(handle);
  }, [term]);

  const searchQuery = useQuery({
    queryKey: ["admin", "rank", "user-search", debounced],
    queryFn: () => userService.searchUsers(debounced),
    enabled: debounced.length >= 2
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Players</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search player by battle tag…"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
        </div>
        {searchQuery.isLoading && debounced.length >= 2 ? (
          <p className="text-sm text-muted-foreground">Searching…</p>
        ) : (searchQuery.data ?? []).length > 0 ? (
          <div className="divide-y divide-border rounded-md border">
            {(searchQuery.data ?? []).map((user) => (
              <button
                key={user.id}
                type="button"
                onClick={() => onSelect(user)}
                className="block w-full px-3 py-2 text-left text-sm hover:bg-muted/50"
              >
                {user.name}
              </button>
            ))}
          </div>
        ) : debounced.length >= 2 ? (
          <p className="text-sm text-muted-foreground">No players found.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function PlayerDialog({ user, onClose }: { user: MinimizedUser; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(new Set());

  const statusQuery = useQuery({
    queryKey: ["admin", "rank", "collection", user.id],
    queryFn: () => adminService.getRankCollectionStatus(user.id)
  });
  const rows = statusQuery.data ?? [];

  const triggerMutation = useMutation({
    mutationFn: (socialAccountIds: number[] | null) =>
      adminService.triggerRankCollection({ user_id: user.id, social_account_ids: socialAccountIds }),
    onSuccess: (result) => {
      notify.success(`Queued ${result.enqueued} rank fetch(es)`);
      setSelectedTagIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["admin", "rank", "collection", user.id] });
    }
  });

  const toggleTag = (id: number) =>
    setSelectedTagIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{user.name}</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          <section className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Collection status</h3>
              <div className="flex items-center gap-2">
                {selectedTagIds.size > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={triggerMutation.isPending}
                    onClick={() => triggerMutation.mutate([...selectedTagIds])}
                  >
                    Collect selected ({selectedTagIds.size})
                  </Button>
                )}
                <Button
                  size="sm"
                  disabled={triggerMutation.isPending}
                  onClick={() => triggerMutation.mutate(null)}
                >
                  {triggerMutation.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Collect all
                </Button>
              </div>
            </div>

            {statusQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No battle tags linked to this player.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead>Battle tag</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last checked</TableHead>
                    <TableHead>Fails</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.social_account_id}>
                      <TableCell>
                        <Checkbox
                          checked={selectedTagIds.has(row.social_account_id)}
                          onCheckedChange={() => toggleTag(row.social_account_id)}
                          aria-label={`Select ${row.battle_tag}`}
                        />
                      </TableCell>
                      <TableCell className="font-medium">{row.battle_tag}</TableCell>
                      <TableCell title={row.last_error ?? undefined}>
                        <StatusBadge status={row.status} />
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDate(row.last_checked_at)}
                      </TableCell>
                      <TableCell className="text-sm tabular-nums">
                        {row.consecutive_failures || "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={triggerMutation.isPending}
                          onClick={() => triggerMutation.mutate([row.social_account_id])}
                        >
                          <RefreshCw className="mr-1 h-3 w-3" />
                          Collect
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>

          <UserRankHistory userId={user.id} title="Rank history" />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ReenableDisabledButton() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => adminService.reenableDisabledRankCollection(false),
    onSuccess: (result) => {
      notify.success(`Re-enabled ${result.reenabled} disabled battle tag(s)`);
      queryClient.invalidateQueries({ queryKey: ["admin", "rank", "fetch-log"] });
    },
    onError: (error) => notify.apiError(error, { title: "Failed to re-enable" })
  });

  return (
    <Button variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
      {mutation.isPending ? (
        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
      ) : (
        <RotateCcw className="mr-1.5 h-4 w-4" />
      )}
      Re-enable disabled
    </Button>
  );
}

export default function RankCollectionAdminPage() {
  const [selectedUser, setSelectedUser] = useState<MinimizedUser | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">Rank Collection</h1>
          <p className="mt-2 text-muted-foreground">
            Live OverFast worker task history and per-player manual re-fetch.
          </p>
        </div>
        <ReenableDisabledButton />
      </div>

      <FetchLogSection />
      <PlayerSearchSection onSelect={setSelectedUser} />

      {selectedUser && <PlayerDialog user={selectedUser} onClose={() => setSelectedUser(null)} />}
    </div>
  );
}
