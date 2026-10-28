"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { NumberInput } from "@/components/ui/number-input";
import { Slider } from "@/components/ui/slider";
import { tint } from "@/lib/colors";
import {
  getDivisionLabel,
  resolveDivisionFromRank,
  resolveRankFromDivision,
  sortTiersAscending
} from "@/lib/divisions/grid";
import { roleColor, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { DivisionGrid } from "@/types/workspace.types";

/**
 * Role tinting for a rank card. Shared rather than per-sheet because the
 * tournament sheet and the mix sheet edit the same thing and had already
 * drifted into two different colour vocabularies for it.
 *
 * The tint is the role's own presentation colour from the owner game's ontology (`roleRankAccent`); a role
 * without one, or a rank that belongs to no single role, reads neutral. Nothing here knows a game's roles.
 */
export interface RoleRankAccent {
  /** A CSS colour, or `null` for the neutral tone. */
  color: string | null;
}

export function roleRankAccent(ontology: RoleOntology | null | undefined, code: string): RoleRankAccent {
  return { color: roleColor(ontology, code) };
}

/** Card frame for the active state. */
export function accentRowStyle({ color }: RoleRankAccent): CSSProperties {
  return color
    ? {
        borderColor: tint(color, 40),
        backgroundColor: tint(color, 7),
        boxShadow: `0 0 0 1px ${tint(color, 8)}`
      }
    : { borderColor: "var(--aqt-border-2)", backgroundColor: "var(--aqt-overlay-2)" };
}

export function accentTextStyle({ color }: RoleRankAccent): CSSProperties {
  return { color: color ?? "var(--aqt-fg-muted)" };
}

/** A role-tinted label chip (a rank's source, "First", a sub-role): the role's colour, neutral without one. */
export function AccentBadge({
  accent,
  className,
  children
}: Readonly<{ accent: RoleRankAccent; className?: string; children: ReactNode }>) {
  return (
    <Badge hue={accent.color ?? undefined} tone="neutral" size="sm" className={className}>
      {children}
    </Badge>
  );
}

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
    }
  };
}

function gridBounds(grid: DivisionGrid): { min: number; max: number | undefined } {
  if (!grid.tiers.length) {
    return { min: 0, max: 5000 };
  }

  const mins = grid.tiers.map((tier) => tier.rank_min);
  const maxes = grid.tiers
    .map((tier) => tier.rank_max)
    .filter((value): value is number => value != null);

  return {
    min: Math.min(...mins),
    max: grid.tiers.some((tier) => tier.rank_max == null) ? undefined : Math.max(...maxes, ...mins)
  };
}

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
  /** The owner game's grid these controls label and slide against. */
  grid: DivisionGrid;
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
 * The owner passes its resolved grid; there is no workspace-default fallback.
 */
export function RoleRankControls({
  rankValue,
  sourceLabel,
  accent,
  active,
  disabled = false,
  onClear,
  onChange,
  grid
}: Readonly<RoleRankControlsProps>) {
  const t = useTranslations("balancerTool.playerEdit.rank");
  const tCommon = useTranslations("common");
  const sliderColor = accent.color ?? "var(--aqt-teal)";
  const bounds = useMemo(() => gridBounds(grid), [grid]);
  const tiers = useMemo(() => sortTiersAscending(grid), [grid]);

  const divisionNumber = resolveDivisionFromRank(grid, rankValue);
  const divisionName = getDivisionLabel(grid, divisionNumber);
  const sliderIndex = Math.max(
    tiers.findIndex((tier) => tier.number === divisionNumber),
    0
  );

  return (
    <>
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <Eyebrow tone="dim">{t("skillRating")}</Eyebrow>
          {rankValue == null ? (
            <span className="text-label text-[color:var(--aqt-fg-dim)]">{t("noRank")}</span>
          ) : (
            <span className="flex items-center gap-1 text-label">
              <span
                className="flex items-center gap-1 font-semibold"
                style={active ? accentTextStyle(accent) : { color: "var(--aqt-fg-dim)" }}
              >
                {rankValue}
                {sourceLabel ? (
                  <AccentBadge accent={accent} className="uppercase">
                    {sourceLabel}
                  </AccentBadge>
                ) : null}
              </span>
              {/* Emptying the number field also clears, but nothing said so: the
                  slider under it reads as a required value, and the only visible
                  way out was deleting the whole role. */}
              {onClear ? (
                <Button
                  type="button"
                  variant="ghost-destructive"
                  size="inline"
                  disabled={disabled}
                  onClick={onClear}
                  title={t("clearHint")}
                  className="px-1 uppercase tracking-label"
                >
                  {t("clear")}
                </Button>
              ) : null}
            </span>
          )}
        </div>
        <NumberInput
          integer
          min={bounds.min}
          max={bounds.max}
          disabled={disabled}
          size="sm"
          className={cn("h-7", !active && "text-[color:var(--aqt-fg-dim)]")}
          value={rankValue}
          onValueChange={(next) => onChange(next, resolveDivisionFromRank(grid, next))}
        />
        <Slider
          aria-label={t("rank")}
          accent={sliderColor}
          min={0}
          max={Math.max(tiers.length - 1, 0)}
          step={1}
          disabled={disabled || !active}
          value={[sliderIndex]}
          onValueChange={([index]) => {
            const nextDivision = tiers[index]?.number ?? null;
            onChange(resolveRankFromDivision(grid, nextDivision), nextDivision);
          }}
        />
      </div>

      <div className="space-y-1">
        <Eyebrow tone="dim">{t("rank")}</Eyebrow>
        <div
          className={cn(
            "flex min-h-[36px] items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 py-1",
            !active && "text-[color:var(--aqt-fg-dim)]"
          )}
          title={divisionName ?? undefined}
        >
          {divisionNumber != null ? (
            <>
              <DivisionIcon
                division={divisionNumber}
                tournamentGrid={grid}
                width={20}
                height={20}
              />
              <div className="min-w-0">
                <div className="truncate text-label font-medium text-[color:var(--aqt-fg-muted)]">
                  {divisionName ?? tCommon("divisionWithId", { id: divisionNumber })}
                </div>
              </div>
            </>
          ) : (
            <span className="text-label text-[color:var(--aqt-fg-dim)]">{t("noRankYet")}</span>
          )}
        </div>
      </div>
    </>
  );
}
