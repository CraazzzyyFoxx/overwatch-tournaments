"use client";

import { useContext, useMemo, useState } from "react";
import { FileEdit, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  activeRoundNumber,
  bracketRoundShape,
  buildRoundGroups,
  computeLatestMatchByTeam,
  orderEliminationRounds
} from "@/lib/bracket/view";
import { HEADER_CHIP } from "@/components/bracket/BracketCanvas";
import { StreamWatchContext } from "@/components/stream/stream-watch";
import { Button } from "@/components/ui/button";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { StatusDot } from "@/components/ui/status-dot";
import { swissPools } from "@/lib/bracket/swiss";
import { duelSeats } from "@/lib/encounter/seats";
import { isEncounterCompleted } from "@/lib/encounter/status";
import { streamEntryKey } from "@/lib/social/stream-platform";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";
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
  /** `false`: cards do not link to the encounter page (a stage still in preview). */
  interactive?: boolean;
  /** Team id → its participant stream on air; see `buildLiveTeamStreams`. */
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
};

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
  canReport,
  interactive = true,
  liveTeamStreams
}: Readonly<MobileBracketProps>) {
  const t = useTranslations();
  const roundLabel = useBracketRoundLabel();
  const watcher = useContext(StreamWatchContext);

  const { rounds, shape, swiss } = useMemo(() => {
    const groups = buildRoundGroups(encounters);
    const upper = groups.filter((g) => g.round > 0).sort((a, b) => a.round - b.round);
    const lower = groups.filter((g) => g.round < 0).sort((a, b) => b.round - a.round);
    return {
      rounds: [...upper, ...lower],
      shape: bracketRoundShape(type, encounters),
      swiss: type === "swiss" ? swissPools(upper) : null
    };
  }, [encounters, type]);
  // The tree's rule (`MatchNodeSeat.isLatest`): a team's stream is news for its
  // newest match only.
  const latestMatchByTeam = useMemo(
    () => computeLatestMatchByTeam(encounters, orderEliminationRounds(encounters, type).matchNumbers),
    [encounters, type]
  );

  const initialRound =
    rounds.find((g) => g.matches.some((m) => m.id === highlightMatchId))?.round ??
    activeRoundNumber(rounds);
  const [round, setRound] = useState<number | null>(initialRound);
  const current = rounds.find((g) => g.round === round) ?? rounds[0];

  if (!current) {
    return (
      <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">
        {t("common.noBracketMatches")}
      </div>
    );
  }

  // The chips list both brackets in one row, so their names keep the UB/LB
  // prefix the tree's own columns can do without.
  const label = (r: number) => roundLabel(r, shape);
  // Swiss: the round's matches under their record pools, the way the tree splits its column.
  const sections: { label: string | null; matches: typeof current.matches }[] = swiss?.rounds.find(
    (entry) => entry.round === current.round
  )?.pools ?? [{ label: null, matches: current.matches }];

  return (
    <div className="space-y-3">
      <FilterChipGroup label={t("tournamentDetail.bracketRegion")} className="overflow-x-auto">
        {rounds.map((g) => (
          <FilterChip
            key={g.round}
            active={g.round === current.round}
            onClick={() => setRound(g.round)}
          >
            {label(g.round)}
          </FilterChip>
        ))}
      </FilterChipGroup>
      {sections.map((section) => (
        <section key={section.label ?? "all"} className="space-y-2">
          {section.label !== null ? (
            <h3>
              <span className={HEADER_CHIP}>{section.label}</span>
            </h3>
          ) : null}
          <ul className="space-y-2">
            {section.matches.map((match) => {
              const encounter = encounters.find((e) => e.id === match.id);
              if (!encounter) return null;
              // The same gates the tree applies: an organizer on a phone edits, a
              // captain reports — the list is not a read-only copy of the bracket.
              const editable = onEdit && (canEdit?.(encounter) ?? true);
              const reportable = onReport && (canReport?.(encounter) ?? false);
              // The whole card is a link, and a button cannot live inside one,
              // so the tree's live dot becomes a labelled button under the card.
              const liveStreams =
                watcher === null || liveTeamStreams === undefined || isEncounterCompleted(encounter)
                  ? []
                  : duelSeats(encounter.teams).flatMap((seat) => {
                      if (!seat?.team_id || latestMatchByTeam.get(seat.team_id) !== match.id) return [];
                      const stream = liveTeamStreams.get(seat.team_id);
                      return stream ? [stream] : [];
                    });
              return (
                <li
                  key={match.id}
                  className={
                    match.id === highlightMatchId
                      ? "rounded-[10px] ring-2 ring-[color:var(--aqt-teal)]"
                      : undefined
                  }
                >
                  <MatchCard
                    encounter={encounter}
                    eyebrow={`${label(match.round)} · Bo${encounter.best_of}`}
                    href={interactive ? `/encounters/${match.id}` : undefined}
                  />
                  {editable || reportable || liveStreams.length > 0 ? (
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {liveStreams.map((stream) => {
                        const player = stream.player?.name ?? stream.channel;
                        const watchLabel =
                          stream.viewer_count == null
                            ? t("bracket.watchTeamStream", { player })
                            : t("bracket.watchTeamStreamWithViewers", { player, count: stream.viewer_count });
                        return (
                          <Button
                            key={streamEntryKey(stream)}
                            type="button"
                            variant="outline"
                            size="sm"
                            aria-label={watchLabel}
                            title={watchLabel}
                            aria-pressed={watcher?.watchingKey === streamEntryKey(stream)}
                            data-live-team-stream={stream.channel}
                            onClick={(event) => watcher?.watch(stream, event.currentTarget)}
                            className="aria-pressed:border-[color:var(--aqt-status-live)]"
                          >
                            <StatusDot pulse className="size-[7px] text-[color:var(--aqt-status-live)]" />
                            {player}
                          </Button>
                        );
                      })}
                      {editable || reportable ? (
                        <span className="ms-auto flex gap-2">
                          {editable ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => onEdit(encounter)}
                            >
                              <Pencil aria-hidden />
                              {t("bracket.editMatch")}
                            </Button>
                          ) : null}
                          {reportable ? (
                            <Button
                              type="button"
                              variant="accent"
                              size="sm"
                              onClick={() => onReport(encounter)}
                            >
                              <FileEdit aria-hidden />
                              {t("bracket.reportMatch")}
                            </Button>
                          ) : null}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
