"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, Search } from "lucide-react";
import { useDebounce } from "use-debounce";

import RankHistory from "@/components/RankHistory";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useClickOutside } from "@/hooks/useClickOutside";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import rankService from "@/services/rank.service";
import userService from "@/services/user.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { CurrentRank } from "@/types/rank.types";

import { StatusBadge, formatDate } from "@/components/admin/collectors/rank-shared";
import { EmptyNote } from "@/components/kit/EmptyNote";

interface SelectUser {
  (userId: number, label: string): void;
}

// ─── Player search (header combobox) ─────────────────────────────────────────

/** Compact search that lives in the page header; matches drop down below the
 *  input and open the player detail on select. */
export function RankPlayerSearch({ onSelect }: Readonly<{ onSelect: SelectUser }>) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [debouncedTerm] = useDebounce(term, 300);
  const debounced = debouncedTerm.trim();

  useClickOutside(containerRef, () => setOpen(false));

  const searchQuery = useQuery({
    queryKey: ["admin", "rank", "user-search", debounced],
    queryFn: () => userService.searchUsers(debounced),
    enabled: debounced.length >= 2
  });
  const results = searchQuery.data ?? [];
  const showDropdown = open && debounced.length >= 2;

  const pick = (id: number, name: string) => {
    onSelect(id, name);
    setOpen(false);
    setTerm("");
  };

  return (
    <div ref={containerRef} className="relative w-full sm:w-72">
      <Search
        aria-hidden
        className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        className="pl-8"
        aria-label="Search player by battle tag"
        placeholder="Search player by battle tag…"
        value={term}
        onChange={(event) => {
          setTerm(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      />
      {showDropdown && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md">
          {searchQuery.isLoading ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">Searching…</p>
          ) : results.length > 0 ? (
            <div className="max-h-72 divide-y divide-border overflow-y-auto">
              {results.map((user) => (
                <button
                  key={user.id}
                  type="button"
                  onClick={() => pick(user.id, user.name)}
                  className="block w-full px-3 py-2 text-left text-sm hover:bg-muted/50"
                >
                  {user.name}
                </button>
              ))}
            </div>
          ) : (
            <p className="px-3 py-2 text-sm text-muted-foreground">
              No player matches “{debounced}”. Try the full battle tag, including the #tag.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Current ranks (native OverFast division/tier per role) ──────────────────

function rankLabel(rank: CurrentRank): string {
  if (!rank.is_ranked || !rank.division) return "Unranked";
  const division = rank.division.charAt(0).toUpperCase() + rank.division.slice(1);
  return rank.tier != null ? `${division} ${rank.tier}` : division;
}

function CurrentRanksSection({ userId }: Readonly<{ userId: number }>) {
  const query = useQuery({
    queryKey: ["admin", "rank", "current", userId],
    queryFn: () => rankService.getUserCurrentRanks(userId)
  });
  const ranks = (query.data?.ranks ?? []).filter((r) => r.is_ranked);
  if (query.isLoading || ranks.length === 0) return null;

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Current ranks</h3>
      <div className="flex flex-wrap gap-2">
        {ranks.map((rank) => (
          <span
            key={`${rank.social_account_id}-${rank.role}-${rank.platform}`}
            className="inline-flex items-center gap-1.5 rounded-md border bg-muted/40 px-2 py-1 text-xs"
            title={`${rank.battle_tag} · ${rank.platform}`}
          >
            <span className="capitalize text-muted-foreground">{rank.role}</span>
            <span className="font-medium">{rankLabel(rank)}</span>
          </span>
        ))}
      </div>
    </section>
  );
}

// ─── Per-player rank collection ──────────────────────────────────────────────

/**
 * One player's rank collection state, with the re-fetch controls.
 *
 * Moved out of the rank collector screen: a person's rank belongs on their
 * card (People › Identity), and the collector page keeps it only until its own
 * WU drops the player lookup.
 */
export function RankPlayerPanel({ userId }: Readonly<{ userId: number }>) {
  const queryClient = useQueryClient();
  // Scoped server-side to the injected workspace; see `admin.service.ts`.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(new Set());

  const statusQuery = useQuery({
    queryKey: ["admin", "rank", "collection", workspaceId, userId],
    queryFn: () => adminService.getRankCollectionStatus(userId)
  });
  const rows = statusQuery.data ?? [];

  const triggerMutation = useMutation({
    mutationFn: (socialAccountIds: number[] | null) =>
      adminService.triggerRankCollection({ user_id: userId, social_account_ids: socialAccountIds }),
    onSuccess: (result) => {
      notify.success(`Queued ${result.enqueued} rank fetch(es)`);
      setSelectedTagIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["admin", "rank"] });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not queue the rank fetch — try again" })
  });

  const toggleTag = (id: number) =>
    setSelectedTagIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-5">
      <CurrentRanksSection userId={userId} />

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
                <span className="tabular-nums">Collect selected ({selectedTagIds.size})</span>
              </Button>
            )}
            <Button
              size="sm"
              disabled={triggerMutation.isPending}
              onClick={() => triggerMutation.mutate(null)}
            >
              {triggerMutation.isPending ? (
                <Loader2 aria-hidden className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw aria-hidden className="mr-1.5 h-3.5 w-3.5" />
              )}
              Collect all
            </Button>
          </div>
        </div>

        {statusQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : rows.length === 0 ? (
          <EmptyNote>
            No battle tags linked to this player. Ask them to connect a Battle.net account before
            rank collection can run.
          </EmptyNote>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Battle tag</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last checked</TableHead>
                <TableHead>Last success</TableHead>
                <TableHead className="text-right">Failures</TableHead>
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
                  <TableCell className="text-sm tabular-nums text-muted-foreground">
                    {formatDate(row.last_checked_at)}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums text-muted-foreground">
                    {formatDate(row.last_success_at)}
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums">
                    {row.consecutive_failures || "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={triggerMutation.isPending}
                      onClick={() => triggerMutation.mutate([row.social_account_id])}
                      aria-label={`Collect rank for ${row.battle_tag}`}
                    >
                      <RefreshCw aria-hidden className="mr-1 h-3 w-3" />
                      Collect
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      <RankHistory userId={userId} title="Rank history" />
    </div>
  );
}

// ─── Player detail dialog ─────────────────────────────────────────────────────

interface RankPlayerDetailProps {
  userId: number;
  label: string;
  onClose: () => void;
}

/** The dialog wrapper the rank collector screen still opens from its lookup. */
export function RankPlayerDetail({ userId, label, onClose }: Readonly<RankPlayerDetailProps>) {
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
        </DialogHeader>

        <RankPlayerPanel userId={userId} />
      </DialogContent>
    </Dialog>
  );
}
