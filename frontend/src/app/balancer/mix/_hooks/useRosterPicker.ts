"use client";

import { useCallback, useDeferredValue, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { CustomGamePlayer } from "@/services/custom-game.service";
import {
  workspacePlayerKeys,
  workspacePlayerService,
  type RosterAuthor,
  type RosterMember
} from "@/services/workspace-player.service";

/** Dense enough that a 900px-tall dialog shows a full page without scrolling twice. */
const PER_PAGE = 24;

/** Chips before the rest collapse into the "+K more" overflow popover. */
const VISIBLE_AUTHOR_CHIPS = 4;

/**
 * One workspace roster row, normalised for display: `ranks` is what a balance
 * would actually use (canon overridden by this host's own book, the same
 * precedence the balancer applies), `authorRanks` is that book alone so a
 * picker can tell "mine" from "inherited".
 */
export type RosterRow = {
  memberId: number;
  battleTag: string | null;
  displayName: string | null;
  ranks: Record<string, number>;
  authorRanks: Record<string, number>;
};

/** "all" (the workspace canon) | "mine" (the mix host's own book) | one author's user id. */
export type RosterFilter = "all" | "mine" | number;

/**
 * Everything the add-players dialog reads: the paged roster under the active
 * filter, both chip totals, the authors who have rank-corrected anyone here,
 * and the keyboard cursor that makes "add twelve people" twelve keystrokes.
 *
 * The ranks it reads are the *host's* book (`authorUserId`), the layer that
 * decides this mix -- which is what keeps a co-organiser's list from
 * disagreeing with the lineup beside it.
 */
export function useRosterPicker({
  workspaceId,
  open,
  hostUserId,
  rows,
  canWrite,
  onTogglePlayer
}: Readonly<{
  workspaceId: number;
  open: boolean;
  hostUserId: number | null;
  rows: CustomGamePlayer[];
  canWrite: boolean;
  onTogglePlayer: (memberId: number) => void;
}>) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<RosterFilter>("all");
  const [cursor, setCursor] = useState(0);
  const [cursorKey, setCursorKey] = useState("all|1|");
  const listRef = useRef<HTMLUListElement>(null);
  const deferredSearch = useDeferredValue(search.trim());

  const usingMine = filter === "mine";
  const usingNamedAuthor = typeof filter === "number";
  // Under "Everyone" the list still reads through the host's own book (the
  // layer this mix actually balances on), same as before named-author chips
  // existed; a named chip instead reads that account's book.
  const activeAuthorUserId = usingNamedAuthor ? filter : (hostUserId ?? undefined);
  const listParams = {
    page,
    perPage: PER_PAGE,
    query: deferredSearch,
    authorUserId: activeAuthorUserId,
    authorOnly: usingMine || usingNamedAuthor
  };
  const rosterQuery = useQuery({
    queryKey: workspacePlayerKeys.list(workspaceId, listParams),
    queryFn: () => workspacePlayerService.list(workspaceId, listParams),
    enabled: open,
    // Every keystroke and page click is a new key: without this the rows are
    // replaced by skeletons mid-typing and the whole column flickers per
    // character.
    placeholderData: keepPreviousData
  });

  // Both chip counts, independent of which filter is active: `rosterQuery`'s
  // total means "matches under the current filter", the wrong number for the
  // header and the inactive chip, and neither chip's count should require
  // clicking it first to appear.
  const summaryQuery = useQuery({
    queryKey: workspacePlayerKeys.summary(workspaceId, hostUserId ?? undefined),
    queryFn: () => workspacePlayerService.summary(workspaceId, hostUserId ?? undefined),
    enabled: open
  });

  // Every account that has personally rank-corrected somebody here, one chip
  // each -- the point of this dialog surfacing a filter beyond "Everyone"/
  // "My ranks" in the first place. This mix's own host is excluded: "My
  // ranks" already is that chip, so listing the host again here would be
  // the same filter under a second label.
  const authorsQuery = useQuery({
    queryKey: workspacePlayerKeys.authors(workspaceId),
    queryFn: () => workspacePlayerService.listAuthors(workspaceId),
    enabled: open
  });
  const authors = useMemo<RosterAuthor[]>(
    () => (authorsQuery.data?.authors ?? []).filter((author) => author.user_id !== hostUserId),
    [authorsQuery.data, hostUserId]
  );
  const visibleAuthors = authors.slice(0, VISIBLE_AUTHOR_CHIPS);
  const overflowAuthors = authors.slice(VISIBLE_AUTHOR_CHIPS);
  const overflowActiveAuthor = overflowAuthors.find((author) => author.user_id === filter) ?? null;
  // Whoever the active named-author filter reads as, for the empty state --
  // `null` under "Everyone", where that message reads differently.
  const activeAuthorLabel = usingMine
    ? "You"
    : usingNamedAuthor
      ? (visibleAuthors.find((author) => author.user_id === filter)?.display_name ??
        overflowActiveAuthor?.display_name ??
        `#${filter}`)
      : null;

  const pageData = rosterQuery.data;

  const visible = useMemo<RosterRow[]>(
    () =>
      (pageData?.results ?? []).map((member: RosterMember) => ({
        memberId: member.member_id,
        battleTag: member.battle_tag,
        displayName: member.display_name,
        // Effective = canon overridden by this host's own book, the same
        // precedence the balancer applies.
        ranks: { ...member.ranks, ...member.author_ranks },
        authorRanks: member.author_ranks
      })),
    [pageData]
  );

  const inMix = useMemo(() => new Set(rows.map((row) => row.workspace_member_id)), [rows]);

  // A new result set invalidates the cursor: leaving it at row 9 of a list that is
  // now three long would put the Enter key on nothing. Adjusted during render
  // rather than in an effect — the cursor is derived from the query, so a
  // cascading second render is exactly what must not happen between the list
  // changing and the highlight moving.
  const resultKey = `${filter}|${page}|${deferredSearch}`;
  if (cursorKey !== resultKey) {
    setCursorKey(resultKey);
    setCursor(0);
  }

  const move = useCallback(
    (delta: 1 | -1) => {
      setCursor((current) => {
        const next = Math.min(Math.max(current + delta, 0), Math.max(visible.length - 1, 0));
        listRef.current
          ?.querySelectorAll("[data-roster-row]")
          [next]?.scrollIntoView({ block: "nearest" });
        return next;
      });
    },
    [visible.length]
  );

  const onSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      move(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const row = visible[cursor];
      if (row != null && canWrite) onTogglePlayer(row.memberId);
    }
  };

  return {
    search,
    /** Any change to what the list shows restarts it at page one. */
    onSearchChange: (next: string) => {
      setSearch(next);
      setPage(1);
    },
    onSearchKeyDown,
    deferredSearch,
    page,
    setPage,
    filter,
    onFilterChange: (next: RosterFilter) => {
      setFilter(next);
      setPage(1);
    },
    usingMine,
    activeAuthorLabel,
    visibleAuthors,
    overflowAuthors,
    rosterQuery,
    pageData,
    workspaceTotal: summaryQuery.data?.total ?? null,
    mineTotal: summaryQuery.data?.author_total ?? null,
    visible,
    inMix,
    cursor,
    listRef,
    totalPages: pageData ? Math.max(1, Math.ceil(pageData.total / pageData.per_page)) : 1,
    foundCount: pageData?.total ?? null
  };
}
