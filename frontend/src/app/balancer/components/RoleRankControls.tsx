"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import DivisionIcon from "@/components/DivisionIcon";
import { NumberInput } from "@/components/ui/number-input";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import {
  getDivisionLabel,
  resolveDivisionFromRank,
  resolveRankFromDivision,
  sortTiersAscending,
} from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import type { DivisionGrid } from "@/types/workspace.types";

/**
 * Role tinting for a rank card. Shared rather than per-sheet because the
 * tournament sheet and the mix sheet edit the same thing and had already
 * drifted into two different colour vocabularies for it.
 */
export interface RoleRankAccent {
  /** Card frame for the active state. */
  row: string;
  text: string;
  chip: string;
  /** `accent-color` plus the slider's gradient stop, so it lands in `style`. */
  sliderColor: string;
}

export const ROLE_RANK_ACCENTS: Record<string, RoleRankAccent> = {
  tank: {
    row: "border-sky-400/40 bg-sky-500/[0.07] shadow-[0_0_0_1px_rgba(56,189,248,0.08)]",
    text: "text-sky-200",
    chip: "border-sky-300/30 bg-sky-500/12 text-sky-200",
    sliderColor: "var(--aqt-tank)",
  },
  damage: {
    row: "border-orange-400/40 bg-orange-500/[0.07] shadow-[0_0_0_1px_rgba(251,146,60,0.08)]",
    text: "text-orange-200",
    chip: "border-orange-300/30 bg-orange-500/12 text-orange-200",
    sliderColor: "var(--aqt-damage)",
  },
  support: {
    row: "border-emerald-400/40 bg-emerald-500/[0.07] shadow-[0_0_0_1px_rgba(52,211,153,0.08)]",
    text: "text-emerald-200",
    chip: "border-emerald-300/30 bg-emerald-500/12 text-emerald-200",
    sliderColor: "var(--aqt-support)",
  },
};

/** For a rank that belongs to no single role — a whole-player override, say. */
export const NEUTRAL_RANK_ACCENT: RoleRankAccent = {
  row: "border-[color:var(--aqt-border-2)] bg-white/[0.03]",
  text: "text-[color:var(--aqt-fg-muted)]",
  chip: "border-[color:var(--aqt-border-2)] bg-white/[0.06] text-[color:var(--aqt-fg-muted)]",
  sliderColor: "var(--aqt-teal)",
};

/** Long enough that a slider drag or a four-digit number is one write, not twenty. */
const RANK_WRITE_DELAY_MS = 400;

/**
 * A rank field whose value is local while the editor is still moving it.
 *
 * For the sheets that have no Save button — the mix sheet and the workspace
 * roster sheet — every control writes straight through, so a number field wired
 * directly to the mutation issued one write per keystroke and one per slider
 * step. The draft is what the field shows; the write lands once the editor
 * stops. The server value wins again the moment it changes, which is also how a
 * normalised value or another editor's change corrects the field.
 */
export function useDebouncedRank(committed: number | null, commit: (rank: number | null) => void) {
  const [committedSeen, setCommittedSeen] = useState<number | null>(committed);
  const [draft, setDraft] = useState<number | null>(committed);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Adjusted during render rather than in an effect: the draft is derived from
  // the server value, so a cascading second render is exactly what we want to
  // avoid — the field must never paint a value the server has already replaced.
  if (committedSeen !== committed) {
    setCommittedSeen(committed);
    setDraft(committed);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  return {
    value: draft,
    set: (rank: number | null) => {
      setDraft(rank);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => commit(rank), RANK_WRITE_DELAY_MS);
    },
    /** Skips the delay: a Clear is a decision, not a drag. */
    commitNow: (rank: number | null) => {
      clearTimeout(timer.current);
      setDraft(rank);
      commit(rank);
    },
  };
}

function gridBounds(grid: DivisionGrid): { min: number; max: number } {
  if (!grid.tiers.length) {
    return { min: 0, max: 5000 };
  }

  const mins = grid.tiers.map((tier) => tier.rank_min);
  const maxes = grid.tiers
    .map((tier) => tier.rank_max)
    .filter((value): value is number => value !== null);

  return { min: Math.min(...mins), max: Math.max(...maxes, ...mins) };
}

const LABEL_CLASS =
  "text-label font-semibold uppercase tracking-wide text-[color:var(--aqt-fg-dim)]";

type RoleRankControlsProps = {
  /** The rank these controls read and write; `null` renders as unset. */
  rankValue: number | null;
  /** Which layer the shown rank came from, badged beside it. */
  sourceLabel?: string | null;
  accent: RoleRankAccent;
  /** A role that is off keeps its numbers legible but locks the slider. */
  active: boolean;
  disabled?: boolean;
  /** Only rendered when there is something to clear. */
  onClear?: (() => void) | null;
  onChange: (rankValue: number | null, divisionNumber: number | null) => void;
  /**
   * The grid these controls label and slide against. Omitted = the workspace
   * grid, which is right for the tournament and workspace sheets.
   *
   * A mix MUST pass `OW_REFERENCE_GRID`: balancer-service resolves a mix's
   * ranks against the global, OW-synced grid (`workspace_id=None`), so reading
   * them through a workspace's tiers renames the same number.
   */
  grid?: DivisionGrid;
};

/**
 * The two rank cells of a role card — **skill rating** (number field over a
 * division slider) and **rank** (the crest that number lands on).
 *
 * Returned as grid siblings, not wrapped: the tournament sheet puts a sub-role
 * column in front of them and the mix sheet does not, so the columns belong to
 * the caller while the controls themselves stay one implementation. Both sheets
 * edit "what rank does this player have on this role", and two copies of that
 * had already produced two different ways to clear it.
 *
 * The grid defaults to the workspace's rather than being required of every
 * caller; only the mix surfaces, which live on the global OW grid, pass one.
 */
export function RoleRankControls({
  rankValue,
  sourceLabel,
  accent,
  active,
  disabled = false,
  onClear,
  onChange,
  grid: gridOverride,
}: Readonly<RoleRankControlsProps>) {
  const workspaceGrid = useDivisionGrid();
  const grid = gridOverride ?? workspaceGrid;
  const bounds = useMemo(() => gridBounds(grid), [grid]);
  const tiers = useMemo(() => sortTiersAscending(grid), [grid]);

  const divisionNumber = resolveDivisionFromRank(grid, rankValue);
  const divisionName = getDivisionLabel(grid, divisionNumber);
  const sliderIndex = Math.max(
    tiers.findIndex((tier) => tier.number === divisionNumber),
    0,
  );
  const fillPercent = tiers.length <= 1 ? 100 : (sliderIndex / (tiers.length - 1)) * 100;

  return (
    <>
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <span className={LABEL_CLASS}>Skill rating</span>
          {rankValue == null ? (
            <span className="text-label text-[color:var(--aqt-fg-dim)]">No rank</span>
          ) : (
            <span className="flex items-center gap-1">
              <span
                className={cn(
                  "flex items-center gap-1 text-label font-semibold",
                  active ? accent.text : "text-[color:var(--aqt-fg-dim)]",
                )}
              >
                {rankValue}
                {sourceLabel ? (
                  <span
                    className={cn(
                      "inline-flex h-4 items-center rounded-md border px-1.5 text-label uppercase",
                      accent.chip,
                    )}
                  >
                    {sourceLabel}
                  </span>
                ) : null}
              </span>
              {/* Emptying the number field also clears, but nothing said so: the
                  slider under it reads as a required value, and the only visible
                  way out was deleting the whole role. */}
              {onClear ? (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={onClear}
                  title="Clear this role's rank"
                  className="rounded px-1 text-label font-semibold uppercase tracking-wide text-[color:var(--aqt-fg-dim)] transition-colors hover:text-rose-200 disabled:opacity-50"
                >
                  Clear
                </button>
              ) : null}
            </span>
          )}
        </div>
        <NumberInput
          integer
          min={bounds.min}
          max={bounds.max}
          disabled={disabled}
          className={cn(
            "h-7 border-[color:var(--aqt-border-2)] bg-black/15 px-2 text-xs text-[color:var(--aqt-fg)] shadow-none focus-visible:ring-1 focus-visible:ring-primary/40",
            !active && "text-[color:var(--aqt-fg-dim)]",
          )}
          value={rankValue}
          onValueChange={(next) => onChange(next, resolveDivisionFromRank(grid, next))}
        />
        <input
          type="range"
          min={0}
          max={Math.max(tiers.length - 1, 0)}
          step={1}
          disabled={disabled || !active}
          value={sliderIndex}
          onChange={(event) => {
            const nextDivision = tiers[Number(event.target.value)]?.number ?? null;
            onChange(resolveRankFromDivision(grid, nextDivision), nextDivision);
          }}
          className={cn(
            "h-1 w-full cursor-pointer appearance-none rounded-full bg-white/8",
            (disabled || !active) && "cursor-not-allowed opacity-50",
          )}
          style={{
            accentColor: accent.sliderColor,
            background: `linear-gradient(90deg, ${accent.sliderColor} 0%, ${accent.sliderColor} ${fillPercent}%, rgba(255,255,255,0.08) ${fillPercent}%, rgba(255,255,255,0.08) 100%)`,
          }}
        />
      </div>

      <div className="space-y-1">
        <span className={LABEL_CLASS}>Rank</span>
        <div
          className={cn(
            "flex min-h-[36px] items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-black/15 px-2 py-1",
            !active && "text-[color:var(--aqt-fg-dim)]",
          )}
          title={divisionName ?? undefined}
        >
          {divisionNumber != null ? (
            <>
              <DivisionIcon division={divisionNumber} width={20} height={20} />
              <div className="min-w-0">
                <div className="truncate text-label font-medium text-[color:var(--aqt-fg-muted)]">
                  {divisionName ?? `Division ${divisionNumber}`}
                </div>
              </div>
            </>
          ) : (
            <span className="text-label text-[color:var(--aqt-fg-dim)]">No rank yet</span>
          )}
        </div>
      </div>
    </>
  );
}
