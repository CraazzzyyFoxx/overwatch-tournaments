"use client";

import { useMemo, useState } from "react";
import { FileEdit, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  activeRoundNumber,
  bracketRoundShape,
  buildRoundGroups
} from "@/lib/bracket-view";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import type { Encounter } from "@/types/encounter.types";
import type { StageType } from "@/types/tournament.types";

import { MatchCard } from "../_components/MatchCard";

type MobileBracketProps = {
  encounters: Encounter[];
  type: StageType;
  /** Round of the deep-linked `?match=`, so that round opens first. */
  highlightMatchId?: number | null;
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
};

const ACTION_BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-caption font-semibold transition-colors";

/**
 * The bracket on a phone: one round at a time as a column of `MatchCard`s with
 * a round switcher, instead of a 1800px tree behind a horizontal scroll. The
 * tree (`BracketView`) is untouched and still renders at ≥768px.
 *
 * Round order is play order — upper rounds ascending, then lower rounds by
 * depth — the same order the tree's columns take.
 */
export function MobileBracket({
  encounters,
  type,
  highlightMatchId = null,
  onEdit,
  onReport,
  canEdit,
  canReport
}: Readonly<MobileBracketProps>) {
  const t = useTranslations();
  const roundLabel = useBracketRoundLabel();

  const { rounds, shape } = useMemo(() => {
    const groups = buildRoundGroups(encounters);
    const upper = groups.filter((g) => g.round > 0).sort((a, b) => a.round - b.round);
    const lower = groups.filter((g) => g.round < 0).sort((a, b) => b.round - a.round);
    return { rounds: [...upper, ...lower], shape: bracketRoundShape(type, encounters) };
  }, [encounters, type]);

  const initialRound =
    rounds.find((g) => g.matches.some((m) => m.id === highlightMatchId))?.round ??
    activeRoundNumber(rounds);
  const [round, setRound] = useState<number | null>(initialRound);
  const current = rounds.find((g) => g.round === round) ?? rounds[0];

  if (!current) {
    return <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">{t("common.noBracketMatches")}</div>;
  }

  // The chips list both brackets in one row, so their names keep the UB/LB
  // prefix the tree's own columns can do without.
  const label = (r: number) => roundLabel(r, shape);

  return (
    <div className="space-y-3">
      <FilterChipGroup label={t("tournamentDetail.bracketRegion")} className="overflow-x-auto">
        {rounds.map((g) => (
          <FilterChip key={g.round} active={g.round === current.round} onClick={() => setRound(g.round)}>
            {label(g.round)}
          </FilterChip>
        ))}
      </FilterChipGroup>
      <ul className="space-y-2">
        {current.matches.map((match) => {
          const encounter = encounters.find((e) => e.id === match.id);
          if (!encounter) return null;
          // The same gates the tree applies: an organizer on a phone edits, a
          // captain reports — the list is not a read-only copy of the bracket.
          const editable = onEdit && (canEdit?.(encounter) ?? true);
          const reportable = onReport && (canReport?.(encounter) ?? false);
          return (
            <li key={match.id} className={match.id === highlightMatchId ? "rounded-[10px] ring-2 ring-[color:var(--aqt-teal)]" : undefined}>
              <MatchCard
                encounter={encounter}
                eyebrow={`${label(match.round)} · Bo${encounter.best_of}`}
                href={`/encounters/${match.id}`}
              />
              {editable || reportable ? (
                <div className="mt-1.5 flex justify-end gap-2">
                  {editable ? (
                    <button
                      type="button"
                      className={`${ACTION_BUTTON} border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]`}
                      onClick={() => onEdit(encounter)}
                    >
                      <Pencil className="size-3.5" aria-hidden />
                      {t("bracket.editMatch")}
                    </button>
                  ) : null}
                  {reportable ? (
                    <button
                      type="button"
                      className={`${ACTION_BUTTON} border-[color:color-mix(in_srgb,var(--aqt-teal)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] text-[color:var(--aqt-teal)]`}
                      onClick={() => onReport(encounter)}
                    >
                      <FileEdit className="size-3.5" aria-hidden />
                      {t("bracket.reportMatch")}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
