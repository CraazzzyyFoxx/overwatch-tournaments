"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { RosterAuthor } from "@/services/workspace-player.service";

import type { RosterFilter } from "../_hooks/useRosterPicker";
import { AddBattleTagPopover } from "./AddBattleTagPopover";

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
  onTogglePlayer
}: Readonly<{
  filter: RosterFilter;
  onFilterChange: (next: RosterFilter) => void;
  usingMine: boolean;
  workspaceTotal: number | null;
  mineTotal: number | null;
  visibleAuthors: RosterAuthor[];
  overflowAuthors: RosterAuthor[];
  /** Workspace right: whether a new BattleTag can be added to the roster. */
  canEdit: boolean;
  canWrite: boolean;
  workspaceId: number;
  onTogglePlayer: (memberId: number) => void;
}>) {
  const [isAuthorMenuOpen, setIsAuthorMenuOpen] = useState(false);
  const overflowActiveAuthor = overflowAuthors.find((author) => author.user_id === filter) ?? null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <FilterChip
        label="Everyone"
        count={workspaceTotal}
        active={!usingMine}
        onClick={() => onFilterChange("all")}
      />
      <FilterChip
        label="My ranks"
        count={mineTotal}
        active={usingMine}
        onClick={() => onFilterChange("mine")}
      />
      {visibleAuthors.map((author) => (
        <FilterChip
          key={author.user_id}
          label={author.display_name ?? `#${author.user_id}`}
          count={author.count}
          active={filter === author.user_id}
          onClick={() => onFilterChange(author.user_id)}
        />
      ))}
      {overflowAuthors.length > 0 ? (
        <Popover open={isAuthorMenuOpen} onOpenChange={setIsAuthorMenuOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-pressed={overflowActiveAuthor != null}
              className={cn(
                "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-label transition-colors",
                overflowActiveAuthor != null
                  ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]"
                  : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              )}
            >
              <span className="max-w-24 truncate">
                {overflowActiveAuthor
                  ? (overflowActiveAuthor.display_name ?? `#${overflowActiveAuthor.user_id}`)
                  : `+${overflowAuthors.length} more`}
              </span>
              <ChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-56 p-1">
            <ul className="max-h-64 space-y-0.5 overflow-y-auto">
              {overflowAuthors.map((author) => (
                <li key={author.user_id}>
                  <button
                    type="button"
                    onClick={() => {
                      onFilterChange(author.user_id);
                      setIsAuthorMenuOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-caption transition-colors",
                      filter === author.user_id
                        ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)] text-[color:var(--aqt-teal)]"
                        : "text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                    )}
                  >
                    <span className="truncate">{author.display_name ?? `#${author.user_id}`}</span>
                    <span className="shrink-0 text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
                      {author.count}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      ) : null}
      {canEdit ? (
        <AddBattleTagPopover
          workspaceId={workspaceId}
          canWrite={canWrite}
          onTogglePlayer={onTogglePlayer}
        />
      ) : null}
    </div>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick
}: Readonly<{ label: string; count: number | null; active: boolean; onClick: () => void }>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-2 rounded-full border px-3 text-label transition-colors",
        active
          ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]"
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
      )}
    >
      <span className="truncate">{label}</span>
      <span
        className={cn(
          "rounded px-1 text-label tabular-nums",
          active
            ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_18%,transparent)]"
            : "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-faint)]"
        )}
      >
        {count ?? "\u2013"}
      </span>
    </button>
  );
}
