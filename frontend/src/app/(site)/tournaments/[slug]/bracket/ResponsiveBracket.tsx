"use client";

import { BracketView, type BracketSlotRef } from "@/components/bracket/BracketView";
import { useIsMobile } from "@/hooks/useMobile";
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
  /**
   * `false` for a stage still in preview: look-only for everyone — no links
   * out, and none of the actions (edit, report, rearrange) or live markers,
   * whatever the caller passed.
   */
  interactive?: boolean;
};

/**
 * The tree at ≥768px, a one-round-at-a-time list below it. `useIsMobile` is
 * `false` until its effect runs, so SSR and the first client render agree on
 * the tree; phones swap to the list one frame later, before paint settles.
 */
export function ResponsiveBracket({ interactive = true, ...props }: Readonly<ResponsiveBracketProps>) {
  const isMobile = useIsMobile();
  const view: Omit<ResponsiveBracketProps, "interactive"> = interactive
    ? props
    : { encounters: props.encounters, type: props.type, highlightMatchId: props.highlightMatchId };
  if (isMobile) {
    return (
      <MobileBracket
        encounters={view.encounters}
        type={view.type}
        highlightMatchId={view.highlightMatchId}
        interactive={interactive}
        onEdit={view.onEdit}
        onReport={view.onReport}
        canEdit={view.canEdit}
        canReport={view.canReport}
      />
    );
  }
  return <BracketView {...view} interactive={interactive} />;
}
