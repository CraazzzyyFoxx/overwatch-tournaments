"use client";

import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { useFormatter } from "@/lib/datetime/client";
import { UNKNOWN_ROUND_SHAPE, type BracketRoundShape } from "@/lib/bracket/round-name";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";
import type { StageSummary } from "@/types/tournament.types";

/**
 * How one encounter reads on the overview — the stamp, the round name, the card
 * eyebrow, the link into the bracket and whether anybody is streaming it.
 *
 * One object rather than five props threaded through the branch columns: every
 * block that draws a match needs the whole set, and they all hang off the same
 * three inputs (the drawn stage, the per-stage round shapes and the live
 * streams).
 */
export type OverviewMatchPresenter = {
  clock: (value: Date | string | null) => string | null;
  encounterRound: (encounter: Encounter) => string;
  eyebrowOf: (encounter: Encounter) => string;
  streamsCountOf: (encounter: Encounter) => number;
  bracketHref: (encounter: Encounter) => string;
};

export function useOverviewMatchPresenter({
  slug,
  stage,
  stageId,
  roundShapeByStage,
  liveTeamStreams
}: Readonly<{
  slug: string;
  stage: StageSummary | null;
  stageId: number | null;
  roundShapeByStage: Record<number, BracketRoundShape>;
  liveTeamStreams: ReadonlyMap<number, StreamEntry>;
}>): OverviewMatchPresenter {
  const format = useFormatter();
  const roundLabel = useBracketRoundLabel();

  const clock = (value: Date | string | null) => {
    if (value === null) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    // No explicit zone: next-intl's configured deployment zone is the same on
    // the server and the client, so the stamp survives hydration.
    return format.dateTime(date, { hour: "2-digit", minute: "2-digit" });
  };

  const encounterRound = (encounter: Encounter) =>
    roundLabel(
      encounter.round,
      (encounter.stage_id === null ? undefined : roundShapeByStage[encounter.stage_id]) ??
        UNKNOWN_ROUND_SHAPE
    );

  /** `STAGE · ROUND · BoN[ · HH:MM]`; the card's eyebrow is uppercased by CSS. */
  const eyebrowOf = (encounter: Encounter) => {
    const stageName =
      encounter.stage?.name ?? (encounter.stage_id === stageId ? stage?.name : undefined);
    const at = clock(encounter.scheduled_at);
    return [
      stageName,
      encounterRound(encounter),
      encounter.best_of ? `Bo${encounter.best_of}` : null,
      at
    ]
      .filter((part): part is string => typeof part === "string" && part.length > 0)
      .join(" · ");
  };

  const streamsCountOf = (encounter: Encounter) =>
    [encounter.home_team_id, encounter.away_team_id].filter((teamId) => liveTeamStreams.has(teamId))
      .length;

  const bracketHref = (encounter: Encounter) =>
    `/tournaments/${slug}/bracket?stage=${encounter.stage_id ?? stageId ?? ""}&match=${encounter.id}`;

  return { clock, encounterRound, eyebrowOf, streamsCountOf, bracketHref };
}
