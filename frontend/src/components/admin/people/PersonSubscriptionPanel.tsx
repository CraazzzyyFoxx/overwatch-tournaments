"use client";

import { useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";
import { useDebounce } from "use-debounce";
import { useFormatter } from "@/lib/datetime/client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useClickOutside } from "@/hooks/useClickOutside";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import userService from "@/services/user.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

import {
  PROVIDER_LABELS,
  REASON_LABELS,
  SOURCE_LABELS,
  STATE_BAR,
  STATE_LABELS,
  StateBadge,
  formatDate,
  formatRelative
} from "@/components/admin/collectors/subscription-shared";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Spinner } from "@/components/ui/spinner";

interface SelectUser {
  (userId: number, label: string): void;
}

// ─── Player search (header combobox) ─────────────────────────────────────────

/** Compact search that lives in the page header; matches drop down below the
 *  input and open the player detail on select. */
export function SubscriptionPlayerSearch({ onSelect }: Readonly<{ onSelect: SelectUser }>) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  // APG combobox: DOM focus never leaves the input, so the highlighted row is
  // tracked here and pointed at through `aria-activedescendant`.
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const [debouncedTerm] = useDebounce(term, 300);
  const debounced = debouncedTerm.trim();

  useClickOutside(containerRef, () => setOpen(false));

  const searchQuery = useQuery({
    queryKey: ["admin", "subscriptions", "user-search", debounced],
    queryFn: () => userService.searchUsers(debounced),
    enabled: debounced.length >= 2
  });
  const results = searchQuery.data ?? [];
  const showDropdown = open && debounced.length >= 2;

  // A highlight kept across a new result set would send Enter to whoever now
  // occupies that index. Cleared in the render that first sees the new data, not
  // in an effect: an effect leaves the stale row highlighted for one paint.
  const [seenResults, setSeenResults] = useState(searchQuery.data);
  if (seenResults !== searchQuery.data) {
    setSeenResults(searchQuery.data);
    setActiveIndex(-1);
  }

  const pick = (id: number, name: string) => {
    onSelect(id, name);
    setOpen(false);
    setActiveIndex(-1);
    setTerm("");
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (!showDropdown || results.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      const picked = results[activeIndex];
      if (picked) pick(picked.id, picked.name);
    }
  };

  const foundLabel = `${results.length} ${results.length === 1 ? "player" : "players"} found`;
  const resultsAnnouncement = showDropdown && !searchQuery.isLoading ? foundLabel : "";

  return (
    <div ref={containerRef} className="relative w-full sm:w-72">
      <Search
        aria-hidden
        className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        className="pl-8"
        role="combobox"
        aria-label="Search player by name"
        aria-autocomplete="list"
        aria-expanded={showDropdown}
        aria-controls={listId}
        aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        autoComplete="off"
        placeholder="Search player by name…"
        value={term}
        onChange={(event) => {
          setTerm(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {/* Stable region, updated in place: an inserted live region announces
          unreliably, and the result count is the one thing a sighted user gets
          for free here. */}
      <output className="sr-only">{resultsAnnouncement}</output>
      {showDropdown && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md">
          {searchQuery.isLoading ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">Searching…</p>
          ) : results.length > 0 ? (
            <div
              id={listId}
              role="listbox"
              aria-label="Matching players"
              className="max-h-72 divide-y divide-border overflow-y-auto"
            >
              {results.map((user, index) => (
                <button
                  key={user.id}
                  id={`${listId}-${index}`}
                  type="button"
                  role="option"
                  aria-selected={activeIndex === index}
                  // Out of the tab order on purpose: DOM focus stays in the input
                  // and `aria-activedescendant` points here, so the highlight
                  // below is this option's visible focus. Still a real button, so
                  // it is a control rather than a div that only answers a mouse.
                  tabIndex={-1}
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => pick(user.id, user.name)}
                  className={cn(
                    "block w-full cursor-pointer px-3 py-2 text-left text-sm",
                    activeIndex === index ? "bg-muted/60" : "hover:bg-muted/50"
                  )}
                >
                  {user.name}
                </button>
              ))}
            </div>
          ) : (
            <p id={listId} className="px-3 py-2 text-sm text-muted-foreground">
              No player matches “{debounced}”.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Per-player check timeline ───────────────────────────────────────────────

/**
 * That player's own slice of the check log, newest first.
 *
 * The counterpart of `RankHistory` on the rank tab: the entitlement table only
 * holds the latest verdict, so this is the only place a flap ("active on Monday,
 * inactive on Friday, active again after a re-subscribe") is visible at all.
 */
function PlayerCheckTimeline({ userId }: Readonly<{ userId: number }>) {
  const format = useFormatter();
  // Scoped server-side to the injected workspace; see `admin.service.ts`.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const query = useQuery({
    queryKey: ["admin", "subscriptions", "user-history", workspaceId, userId],
    queryFn: () => adminService.getSubscriptionCheckLog({ user_id: userId, limit: 100 })
  });
  const rows = query.data ?? [];

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Check history</h3>
      {query.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyNote>
          No checks recorded for this player yet.
        </EmptyNote>
      ) : (
        <ol className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
          {rows.map((row) => {
            const reason = row.error ?? (row.reason ? (REASON_LABELS[row.reason] ?? row.reason) : null);
            return (
              <li
                key={row.id}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md border border-border/60 bg-card/50 px-2.5 py-1.5 text-xs"
              >
                <span aria-hidden className={cn("h-2 w-2 rounded-full", STATE_BAR[row.state] ?? "bg-muted")} />
                <span className="tabular-nums text-muted-foreground">
                  {formatDate(format, row.created_at)}
                </span>
                <span className="font-medium">{PROVIDER_LABELS[row.provider] ?? row.provider}</span>
                <span>{STATE_LABELS[row.state] ?? row.state}</span>
                {row.tier_label || row.tier_rank != null ? (
                  <span className="text-muted-foreground">
                    {row.tier_label ?? `Tier ${row.tier_rank}`}
                  </span>
                ) : null}
                <span className="text-muted-foreground">
                  · {SOURCE_LABELS[row.source] ?? row.source}
                </span>
                {reason ? (
                  <span className={cn("truncate", row.error ? "text-danger" : "text-muted-foreground")}>
                    · {reason}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

// ─── Per-player entitlements ─────────────────────────────────────────────────

/**
 * One player's subscription verdicts, with the re-check controls.
 *
 * Moved out of the subscription collector screen: a person's entitlements
 * belong on their card (People › Identity), and the collector page keeps it
 * only until its own WU drops the player lookup.
 */
export function SubscriptionPlayerPanel({
  userId,
  label
}: Readonly<{ userId: number; label: string }>) {
  const format = useFormatter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statusQuery = useQuery({
    queryKey: ["admin", "subscriptions", "collection", workspaceId, userId],
    queryFn: () => adminService.getSubscriptionCollectionStatus(userId)
  });
  const rows = statusQuery.data ?? [];

  const triggerMutation = useMutation({
    mutationFn: (providers: string[] | null) =>
      adminService.triggerSubscriptionCollection({ user_id: userId, providers }),
    onSuccess: (result) => {
      notify.success(
        result.checked === 0
          ? "Nothing to check — this player is not registered in a tournament that requires a subscription"
          : result.checked === 1
            ? "Checked 1 subscription"
            : `Checked ${result.checked} subscriptions`
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not re-check the subscription — try again" })
  });

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Current entitlements</h3>
          <Button
            size="sm"
            disabled={triggerMutation.isPending}
            onClick={() => triggerMutation.mutate(null)}
          >
            {triggerMutation.isPending ? (
              <Spinner className="mr-1.5 size-3.5" />
            ) : (
              <RefreshCw aria-hidden className="mr-1.5 h-3.5 w-3.5" />
            )}
            Re-check now
          </Button>
        </div>

        {statusQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : rows.length === 0 ? (
          <EmptyNote>
            No subscription verdict stored for this player. Either they have no linked auth account,
            or nothing has ever checked them — subscriptions are only resolved for tournaments whose
            registration form requires one.
          </EmptyNote>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workspace</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Tier</TableHead>
                <TableHead>Checked</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={`${row.workspace_id}-${row.provider}`}>
                  <TableCell className="text-sm">
                    {row.workspace_name ?? row.workspace_id ?? "—"}
                  </TableCell>
                  <TableCell className="font-medium">
                    {PROVIDER_LABELS[row.provider] ?? row.provider}
                  </TableCell>
                  <TableCell title={row.source ?? undefined}>
                    <StateBadge state={row.state} />
                  </TableCell>
                  <TableCell className="text-sm tabular-nums text-muted-foreground">
                    {row.tier_label ?? (row.tier_rank != null ? `Tier ${row.tier_rank}` : "—")}
                  </TableCell>
                  <TableCell
                    className="text-sm tabular-nums text-muted-foreground"
                    title={formatDate(format, row.checked_at)}
                  >
                    {formatRelative(format, row.checked_at)}
                  </TableCell>
                  <TableCell className="max-w-40 truncate text-xs text-muted-foreground">
                    {row.reason ? (REASON_LABELS[row.reason] ?? row.reason) : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={triggerMutation.isPending}
                      onClick={() => triggerMutation.mutate([row.provider])}
                      aria-label={`Re-check ${PROVIDER_LABELS[row.provider] ?? row.provider} for ${label}`}
                    >
                      <RefreshCw aria-hidden className="mr-1 h-3 w-3" />
                      Re-check
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      <PlayerCheckTimeline userId={userId} />
    </div>
  );
}

// ─── Player detail dialog ─────────────────────────────────────────────────────

interface SubscriptionPlayerDetailProps {
  userId: number;
  label: string;
  onClose: () => void;
}

/** The dialog wrapper the subscription collector screen still opens from its lookup. */
export function SubscriptionPlayerDetail({
  userId,
  label,
  onClose
}: Readonly<SubscriptionPlayerDetailProps>) {
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
        </DialogHeader>

        <SubscriptionPlayerPanel userId={userId} label={label} />
      </DialogContent>
    </Dialog>
  );
}
