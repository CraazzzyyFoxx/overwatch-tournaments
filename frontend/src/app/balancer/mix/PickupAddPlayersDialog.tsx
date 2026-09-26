"use client";

import { Search } from "lucide-react";

import { CAPTION_CLASS, CARD_TITLE_CLASS, EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { DataPagination } from "@/components/ui/data-pagination";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ROLES, ROLE_LABELS } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { CustomGamePlayer } from "@/services/custom-game.service";

import { MixLineupAside } from "./_components/MixLineupAside";
import { RosterFilterBar } from "./_components/RosterFilterBar";
import { RosterRowItem } from "./_components/RosterRowItem";
import { useRosterPicker } from "./_hooks/useRosterPicker";

type PickupAddPlayersDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  /** Workspace right: whether a new BattleTag can be added to the roster. */
  canEdit: boolean;
  /**
   * Whether the rank pickers write. Only the host's book decides this mix, and
   * the endpoint writes the caller's own, so anyone else editing here produced a
   * 200 that changed nothing on screen.
   */
  canEditRanks: boolean;
  /** Mix right: whether membership can change at all (a closed mix is read-only). */
  canWrite: boolean;
  /** Whose rank book this mix resolves against, so the list shows the numbers it will use. */
  hostUserId: number | null;
  /** The mix lineup, so the right column can show supply without a second query. */
  rows: CustomGamePlayer[];
  onTogglePlayer: (memberId: number) => void;
};

/**
 * Filling a mix, as one screen instead of two.
 *
 * The roster used to open as a single-column overlay that reused the tournament
 * balancer's sidebar, which meant a host adding twelve people had to close it to
 * check what they had built, reopen it to fix the tank shortage, and close it
 * again. The lineup is now the right half of the same dialog: every click on the
 * left updates the seat count, the role gauges and the list on the right, so
 * "have I got a lobby" is answered without leaving the surface that answers it.
 *
 * It is deliberately NOT the tournament sidebar any more. That panel is a
 * roster editor for a workspace — collapsible, rank-layer-aware, at home in a
 * 320px rail. This is a picker for one mix, and the two had already started
 * paying for each other's constraints.
 *
 * The ranks it shows and edits are the *host's* book (`scope: "author"`), the
 * layer that decides this mix — read via `authorUserId` rather than defaulting
 * to the caller's, which is what used to make a co-organiser's list disagree
 * with the lineup beside it. The workspace canon shows through dimmed where the
 * host has not set their own.
 */
export function PickupAddPlayersDialog({
  open,
  onOpenChange,
  workspaceId,
  canEdit,
  canEditRanks,
  canWrite,
  hostUserId,
  rows,
  onTogglePlayer
}: Readonly<PickupAddPlayersDialogProps>) {
  const picker = useRosterPicker({
    workspaceId,
    open,
    hostUserId,
    rows,
    canWrite,
    onTogglePlayer
  });
  const { rosterQuery, pageData, visible, deferredSearch, listRef, page, cursor } = picker;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // A working surface, not a prompt: the roster needs three rank columns
        // and the lineup beside it, and at `sm:max-w-lg` the pickers wrapped
        // onto a second line for every single row.
        className="flex h-[min(58rem,calc(100svh-3rem))] w-[min(74rem,calc(100vw-2rem))] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none"
      >
        {/* The tool's hero motif, one hairline of it: this dialog is the only
            full-bleed surface in the mix flow, and without a lit top edge it read
            as a grey sheet dropped over a grey page. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[color:var(--aqt-teal)]"
        />
        <header className="flex shrink-0 items-baseline gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-5 py-3.5 pr-12">
          <DialogTitle className={cn(CARD_TITLE_CLASS, "tracking-label")}>Add players</DialogTitle>
          <DialogDescription className={cn(CAPTION_CLASS, "min-w-0 truncate")}>
            {picker.workspaceTotal == null
              ? "Loading the workspace roster\u2026"
              : `${picker.workspaceTotal} in this workspace \u00B7 ${
                  canEditRanks ? "your ranks decide" : "the host's ranks decide"
                }, workspace ranks fill the gaps`}
          </DialogDescription>
        </header>

        <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] overflow-hidden lg:grid-cols-[minmax(0,1fr)_21rem] lg:grid-rows-1">
          {/* ── The roster ───────────────────────────────────────────────── */}
          <div className="flex min-h-0 min-w-0 flex-col">
            <div className="shrink-0 space-y-2.5 px-4 pb-3 pt-3.5">
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[color:var(--aqt-fg-dim)]"
                  aria-hidden="true"
                />
                <Input
                  autoFocus
                  value={picker.search}
                  onChange={(event) => picker.onSearchChange(event.target.value)}
                  onKeyDown={picker.onSearchKeyDown}
                  placeholder={"Type a name or BattleTag \u2014 \u2191\u2193 to move, Enter to add"}
                  aria-label="Search the workspace roster"
                  autoComplete="off"
                  className="h-11 rounded-xl border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] pl-10 pr-24 text-sm"
                />
                <span
                  className={cn(
                    EYEBROW_CLASS,
                    "pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 tabular-nums"
                  )}
                >
                  {picker.foundCount == null ? "" : `${picker.foundCount} found`}
                </span>
              </div>

              <RosterFilterBar
                filter={picker.filter}
                onFilterChange={picker.onFilterChange}
                usingMine={picker.usingMine}
                workspaceTotal={picker.workspaceTotal}
                mineTotal={picker.mineTotal}
                visibleAuthors={picker.visibleAuthors}
                overflowAuthors={picker.overflowAuthors}
                canEdit={canEdit}
                canWrite={canWrite}
                workspaceId={workspaceId}
                onTogglePlayer={onTogglePlayer}
              />
            </div>

            {/* Column head. The three glyphs sit over the pickers below, so a
                host reads a rank column without a text label per row. */}
            <div className="flex shrink-0 items-center gap-2.5 border-y border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-1.5">
              <span aria-hidden="true" className="size-6 shrink-0" />
              <span className={cn(EYEBROW_CLASS, "min-w-0 flex-1")}>Player</span>
              <div aria-hidden="true" className="flex shrink-0 items-center gap-1.5">
                {ROLES.map((role) => (
                  <span
                    key={role.code}
                    title={ROLE_LABELS[role.code]}
                    className="flex size-8 items-center justify-center opacity-70"
                  >
                    <PlayerRoleIcon role={role.icon} size={14} decorative />
                  </span>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-2 py-1.5">
              {rosterQuery.isLoading ? (
                <div className="space-y-1 p-1">
                  {[0, 1, 2, 3, 4, 5, 6, 7].map((row) => (
                    <Skeleton key={row} className="h-12 w-full rounded-lg" />
                  ))}
                </div>
              ) : rosterQuery.isError && pageData == null ? (
                <PageStateCard
                  state="error"
                  title="Unable to load the roster"
                  description="Check your connection and try again."
                  actionLabel="Retry"
                  onAction={() => void rosterQuery.refetch()}
                  className="px-4 py-10"
                />
              ) : visible.length === 0 ? (
                <PageStateCard
                  state={deferredSearch ? "filtered-empty" : "empty"}
                  title={
                    deferredSearch
                      ? `Nobody matches \u201C${deferredSearch}\u201D`
                      : picker.activeAuthorLabel != null
                        ? picker.usingMine
                          ? "You haven't ranked anyone yet"
                          : `${picker.activeAuthorLabel} hasn't ranked anyone yet`
                        : "No players in this workspace yet"
                  }
                  description={
                    deferredSearch
                      ? "Try a different name, or add the BattleTag above."
                      : picker.activeAuthorLabel != null
                        ? "Set a rank on a player in Everyone to add them here."
                        : "Add a BattleTag above to start the roster this workspace balances from."
                  }
                  className="px-4 py-10"
                />
              ) : (
                <ul ref={listRef} className="space-y-0.5" aria-label="Workspace roster">
                  {visible.map((row, index) => (
                    <RosterRowItem
                      key={row.memberId}
                      row={row}
                      isInMix={picker.inMix.has(row.memberId)}
                      isCursor={index === cursor}
                      canWrite={canWrite}
                      onToggle={() => onTogglePlayer(row.memberId)}
                    />
                  ))}
                </ul>
              )}
            </div>

            <div className="flex h-14 shrink-0 items-center gap-3 border-t border-[color:var(--aqt-border)] px-4">
              <DataPagination
                page={page}
                totalPages={picker.totalPages}
                onPageChange={picker.setPage}
                className="w-full"
                summary={
                  pageData
                    ? pageData.total === 0
                      ? "0 players"
                      : `${(page - 1) * pageData.per_page + 1}\u2013${
                          (page - 1) * pageData.per_page + visible.length
                        } of ${pageData.total}`
                    : undefined
                }
              />
            </div>
          </div>

          {/* ── The lineup ───────────────────────────────────────────────── */}
          <MixLineupAside
            rows={rows}
            canWrite={canWrite}
            onTogglePlayer={onTogglePlayer}
            onDone={() => onOpenChange(false)}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
