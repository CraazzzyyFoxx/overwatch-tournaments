"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import { FilterChip } from "@craazzzyyfoxx/admin-kit/ui/filter-chip";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import type { RosterAuthor } from "@/services/workspace-player.service";

import type { RosterFilter } from "../_hooks/useRosterPicker";
import { AddPlayerIdentityPopover } from "./AddPlayerIdentityPopover";

/**
 * Which rank book the roster list reads through: the workspace canon, this
 * host's own, or any other account that has rank-corrected somebody here --
 * one chip each, with everyone past the first few folded into a popover.
 */
export function RosterFilterBar({
  filter,
  onFilterChange,
  usingMine,
  workspaceTotal,
  mineTotal,
  visibleAuthors,
  overflowAuthors,
  canEdit,
  canWrite,
  workspaceId,
  discipline,
  onTogglePlayer
}: Readonly<{
  filter: RosterFilter;
  onFilterChange: (next: RosterFilter) => void;
  usingMine: boolean;
  workspaceTotal: number | null;
  mineTotal: number | null;
  visibleAuthors: RosterAuthor[];
  overflowAuthors: RosterAuthor[];
  /** Workspace right: whether a new player handle can be added to the roster. */
  canEdit: boolean;
  canWrite: boolean;
  workspaceId: number;
  discipline: string;
  onTogglePlayer: (memberId: number) => void;
}>) {
  const t = useTranslations("mixes.addPlayers.filter");
  const [isAuthorMenuOpen, setIsAuthorMenuOpen] = useState(false);
  const overflowActiveAuthor = overflowAuthors.find((author) => author.user_id === filter) ?? null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <FilterChip count={workspaceTotal ?? "\u2013"} active={!usingMine} onClick={() => onFilterChange("all")}>
        {t("everyone")}
      </FilterChip>
      <FilterChip count={mineTotal ?? "\u2013"} active={usingMine} onClick={() => onFilterChange("mine")}>
        {t("mine")}
      </FilterChip>
      {visibleAuthors.map((author) => (
        <FilterChip
          key={author.user_id}
          count={author.count}
          active={filter === author.user_id}
          onClick={() => onFilterChange(author.user_id)}
        >
          <span className="truncate">{author.display_name ?? `#${author.user_id}`}</span>
        </FilterChip>
      ))}
      {overflowAuthors.length > 0 ? (
        <Popover open={isAuthorMenuOpen} onOpenChange={setIsAuthorMenuOpen}>
          <PopoverTrigger asChild>
            <FilterChip active={overflowActiveAuthor != null}>
              <span className="max-w-24 truncate">
                {overflowActiveAuthor
                  ? (overflowActiveAuthor.display_name ?? `#${overflowActiveAuthor.user_id}`)
                  : t("more", { count: overflowAuthors.length })}
              </span>
              <ChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
            </FilterChip>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-56 p-1">
            <ul className="max-h-64 space-y-0.5 overflow-y-auto">
              {overflowAuthors.map((author) => (
                <li key={author.user_id}>
                  <RowButton
                    aria-current={filter === author.user_id ? "true" : undefined}
                    onClick={() => {
                      onFilterChange(author.user_id);
                      setIsAuthorMenuOpen(false);
                    }}
                    className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-caption text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)] aria-[current=true]:text-[color:var(--aqt-teal)]"
                  >
                    <span className="truncate">{author.display_name ?? `#${author.user_id}`}</span>
                    <span className="shrink-0 text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
                      {author.count}
                    </span>
                  </RowButton>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      ) : null}
      {canEdit ? (
        <AddPlayerIdentityPopover
          workspaceId={workspaceId}
          discipline={discipline}
          canWrite={canWrite}
          onTogglePlayer={onTogglePlayer}
        />
      ) : null}
    </div>
  );
}
