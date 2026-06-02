"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, Search } from "lucide-react";

import UserRankHistory from "@/components/UserRankHistory";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
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

export default function RankCollectionAdminPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [selectedUser, setSelectedUser] = useState<MinimizedUser | null>(null);
  const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(term.trim()), 300);
    return () => clearTimeout(handle);
  }, [term]);

  const searchQuery = useQuery({
    queryKey: ["admin", "rank", "user-search", debounced],
    queryFn: () => userService.searchUsers(debounced),
    enabled: debounced.length >= 2 && selectedUser === null
  });

  const statusQuery = useQuery({
    queryKey: ["admin", "rank", "collection", selectedUser?.id],
    queryFn: () => adminService.getRankCollectionStatus(selectedUser!.id),
    enabled: selectedUser !== null
  });

  const rows = statusQuery.data ?? [];

  const triggerMutation = useMutation({
    mutationFn: (battleTagIds: number[] | null) =>
      adminService.triggerRankCollection({
        user_id: selectedUser!.id,
        battle_tag_ids: battleTagIds
      }),
    onSuccess: (result) => {
      toast({ title: `Queued ${result.enqueued} rank fetch(es)` });
      setSelectedTagIds(new Set());
      queryClient.invalidateQueries({
        queryKey: ["admin", "rank", "collection", selectedUser?.id]
      });
    },
    onError: (error: Error) =>
      toast({
        title: "Failed to trigger collection",
        description: error.message,
        variant: "destructive"
      })
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

  const clearSelection = () => {
    setSelectedUser(null);
    setTerm("");
    setDebounced("");
    setSelectedTagIds(new Set());
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Rank Collection</h1>
        <p className="mt-2 text-muted-foreground">
          OverFast rank collection status per player, with manual re-fetch.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Player</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {selectedUser ? (
            <div className="flex items-center gap-3">
              <span className="font-medium">{selectedUser.name}</span>
              <Button variant="outline" size="sm" onClick={clearSelection}>
                Change
              </Button>
            </div>
          ) : (
            <>
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
                      onClick={() => setSelectedUser(user)}
                      className="block w-full px-3 py-2 text-left text-sm hover:bg-muted/50"
                    >
                      {user.name}
                    </button>
                  ))}
                </div>
              ) : debounced.length >= 2 ? (
                <p className="text-sm text-muted-foreground">No players found.</p>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      {selectedUser && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
            <CardTitle>Collection status</CardTitle>
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
          </CardHeader>
          <CardContent>
            {statusQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No battle tags linked to this player.</p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-8" />
                      <TableHead>Battle tag</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last checked</TableHead>
                      <TableHead>Last success</TableHead>
                      <TableHead>Fails</TableHead>
                      <TableHead className="text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow key={row.battle_tag_id}>
                        <TableCell>
                          <Checkbox
                            checked={selectedTagIds.has(row.battle_tag_id)}
                            onCheckedChange={() => toggleTag(row.battle_tag_id)}
                            aria-label={`Select ${row.battle_tag}`}
                          />
                        </TableCell>
                        <TableCell className="font-medium">{row.battle_tag}</TableCell>
                        <TableCell>
                          <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(row.last_checked_at)}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(row.last_success_at)}
                        </TableCell>
                        <TableCell className="text-sm tabular-nums">
                          {row.consecutive_failures || "—"}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={triggerMutation.isPending}
                            onClick={() => triggerMutation.mutate([row.battle_tag_id])}
                          >
                            <RefreshCw className="mr-1 h-3 w-3" />
                            Collect
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {rows.some((row) => row.last_error) && (
                  <div className="mt-3 space-y-1">
                    {rows
                      .filter((row) => row.last_error)
                      .map((row) => (
                        <p key={row.battle_tag_id} className="text-xs text-rose-300/70">
                          <span className="font-medium">{row.battle_tag}:</span> {row.last_error}
                        </p>
                      ))}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {selectedUser && <UserRankHistory userId={selectedUser.id} title="Rank history" />}
    </div>
  );
}
