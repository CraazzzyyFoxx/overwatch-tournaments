"use client";

import { BracketView, type BracketSlotRef } from "@/components/bracket/BracketView";
import { useIsMobile } from "@/hooks/use-mobile";
import type { Encounter } from "@/types/encounter.types";
import type { StreamEntry } from "@/types/stream.types";
import type { StageType } from "@/types/tournament.types";

import { MobileBracket } from "./MobileBracket";

type ResponsiveBracketProps = {
  encounters: Encounter[];
  type: StageType;
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
  onSwapSlots?: (
    source: BracketSlotRef<Encounter>,
    target: BracketSlotRef<Encounter>
  ) => Promise<unknown> | void;
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  highlightMatchId?: number | null;
};

/**
 * The tree at ≥768px, a one-round-at-a-time list below it. `useIsMobile` is
 * `false` until its effect runs, so SSR and the first client render agree on
 * the tree; phones swap to the list one frame later, before paint settles.
 */
export function ResponsiveBracket(props: Readonly<ResponsiveBracketProps>) {
  const isMobile = useIsMobile();
  if (isMobile) {
    return (
      <MobileBracket
        encounters={props.encounters}
        type={props.type}
        highlightMatchId={props.highlightMatchId}
        onEdit={props.onEdit}
        onReport={props.onReport}
        canEdit={props.canEdit}
        canReport={props.canReport}
      />
    );
  }
  return <BracketView {...props} />;
}
