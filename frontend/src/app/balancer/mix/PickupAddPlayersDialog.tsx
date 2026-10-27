"use client";

import { useTranslations } from "next-intl";
import { Search } from "lucide-react";

import { CAPTION_CLASS } from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { DataPagination } from "@/components/ui/data-pagination";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { cn } from "@/lib/utils";
import type { CustomGamePlayer } from "@/services/custom-game.service";

import type { MixOwner } from "./pickup-lineup";
import { MixLineupAside } from "./_components/MixLineupAside";
import { RosterFilterBar } from "./_components/RosterFilterBar";
import { RosterRowItem } from "./_components/RosterRowItem";
import { useRosterPicker } from "./_hooks/useRosterPicker";

type PickupAddPlayersDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  discipline: string;
  /** The mix owner's game: the rank columns, the full-lobby size and the grid the ranks are on. */
  owner: MixOwner;
  /** Workspace right: whether a new player handle can be added to the roster. */
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
  discipline,
  owner,
  canEdit,
  canEditRanks,
  canWrite,
  hostUserId,
  rows,
  onTogglePlayer
}: Readonly<PickupAddPlayersDialogProps>) {
  const t = useTranslations("mixes.addPlayers");
  const tMixes = useTranslations("mixes");
  const tCommon = useTranslations("common");
  const slotLabel = useSlotLabel(owner.ontology);
  const picker = useRosterPicker({
    workspaceId,
    discipline,
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
        variant="panel"
        // A working surface, not a prompt: the roster needs three rank columns
        // and the lineup beside it, and at `sm:max-w-lg` the pickers wrapped
        // onto a second line for every single row.
        className="h-[min(58rem,calc(100svh-3rem))] w-[min(74rem,calc(100vw-2rem))] max-w-none"
      >
        {/* The tool's hero motif, one hairline of it: this dialog is the only
            full-bleed surface in the mix flow, and without a lit top edge it read
            as a grey sheet dropped over a grey page. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[color:var(--aqt-teal)]"
        />
        <DialogHeader variant="panel" className="flex-row items-baseline gap-3 space-y-0">
          <DialogTitle>{tMixes("start.addPlayers")}</DialogTitle>
          {/* A div, not the default <p>: the loading skeleton is a block element. */}
          <DialogDescription asChild className={cn(CAPTION_CLASS, "min-w-0 truncate")}>
            <div>
              {picker.workspaceTotal == null ? (
                <span role="status">
                  <span className="sr-only">{t("loadingRoster")}</span>
                  <Skeleton aria-hidden className="h-4 w-80 max-w-full" />
                </span>
              ) : (
                t("summary", {
                  total: picker.workspaceTotal,
                  decider: canEditRanks ? "you" : "host"
                })
              )}
            </div>
          </DialogDescription>
        </DialogHeader>

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
                  placeholder={t("searchPlaceholder")}
                  aria-label={t("searchLabel")}
                  autoComplete="off"
                  className="h-11 pl-10 pr-24"
                />
                <span
                  className={cn(
                    eyebrowClass(),
                    "pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 tabular-nums"
                  )}
                >
                  {picker.foundCount == null ? "" : t("found", { count: picker.foundCount })}
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
                discipline={discipline}
                onTogglePlayer={onTogglePlayer}
              />
            </div>

            {/* Column head. The three glyphs sit over the pickers below, so a
                host reads a rank column without a text label per row. */}
            <div className="flex shrink-0 items-center gap-2.5 border-y border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-1.5">
              <span aria-hidden="true" className="size-6 shrink-0" />
              <Eyebrow className="min-w-0 flex-1">{tMixes("leaderboard.player")}</Eyebrow>
              {owner.showsRoles ? (
                <div aria-hidden="true" className="flex shrink-0 items-center gap-1.5">
                  {owner.roles.map((role) => (
                    <IconTooltip
                      key={role}
                      label={slotLabel(role)}
                      hint={t("rankHint")}
                      className="size-8 items-center justify-center opacity-70"
                    >
                      <PlayerRoleIcon role={role} ontology={owner.ontology} size={14} decorative />
                    </IconTooltip>
                  ))}
                </div>
              ) : null}
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
                  title={t("errorTitle")}
                  description={tMixes("list.errorDescription")}
                  actionLabel={tCommon("retry")}
                  onAction={() => void rosterQuery.refetch()}
                  className="px-4 py-10"
                />
              ) : visible.length === 0 ? (
                <PageStateCard
                  state={deferredSearch ? "filtered-empty" : "empty"}
                  title={
                    deferredSearch
                      ? t("noMatch", { q: deferredSearch })
                      : picker.activeAuthorLabel != null
                        ? picker.usingMine
                          ? t("noneMine")
                          : t("noneAuthor", { name: picker.activeAuthorLabel })
                        : t("noneWorkspace")
                  }
                  description={
                    deferredSearch
                      ? t("noMatchHint")
                      : picker.activeAuthorLabel != null
                        ? t("noneRankedHint")
                        : t("noneWorkspaceHint")
                  }
                  className="px-4 py-10"
                />
              ) : (
                <ul ref={listRef} className="space-y-0.5" aria-label={t("rosterLabel")}>
                  {visible.map((row, index) => (
                    <RosterRowItem
                      key={row.memberId}
                      row={row}
                      owner={owner}
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
                leading={
                  pageData
                    ? pageData.total === 0
                      ? t("noPlayers")
                      : t("range", {
                          start: (page - 1) * pageData.per_page + 1,
                          end: (page - 1) * pageData.per_page + visible.length,
                          total: pageData.total
                        })
                    : undefined
                }
              />
            </div>
          </div>

          {/* ── The lineup ───────────────────────────────────────────────── */}
          <MixLineupAside
            rows={rows}
            owner={owner}
            canWrite={canWrite}
            onTogglePlayer={onTogglePlayer}
            onDone={() => onOpenChange(false)}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
