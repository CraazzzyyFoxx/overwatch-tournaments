"use client";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RowButton } from "@/components/ui/row-button";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { DivisionGridVersion } from "@/types/workspace.types";
import type { PlayerVM } from "@/disciplines/overwatch/analytics/useAnalyticsViewModel";

import AnomalyFlag from "../AnomalyFlag";
import MoveMark from "../MoveMark";
import ImpactBar from "./ImpactBar";
import PlayerNick from "./PlayerNick";

interface RosterRowProps {
  player: PlayerVM;
  tournamentGrid?: DivisionGridVersion | null;
  /** The tournament's own role dictionary (null while it loads: the glyph stays neutral). */
  ontology: RoleOntology | null;
  onSelect: () => void;
}

/**
 * A roster line in the team panel: role, division crest, nick with its
 * newcomer marks and watch flag, the impact bar (v2 readers only), and the predicted move.
 * Selecting it opens the player panel.
 */
export default function RosterRow({ player, tournamentGrid, ontology, onSelect }: Readonly<RosterRowProps>) {
  const flag = player.anomalies[0];

  return (
    <RowButton
      onClick={onSelect}
      className="grid grid-cols-[1.25rem_1.75rem_minmax(0,1fr)_auto] items-center gap-x-2.5 px-4 py-2.5"
    >
      <PlayerRoleIcon role={player.role} ontology={ontology} size={18} />
      <DivisionIcon division={player.division} tournamentGrid={tournamentGrid} width={28} height={28} tooltip />
      <span className="flex min-w-0 flex-col gap-1.5">
        <PlayerNick player={player} className="text-ui font-semibold" />
        {/* The flag is a word in the meta line (DESIGN.md §4), beside the impact it qualifies. */}
        <span className="flex min-w-0 items-center gap-3">
          {player.impact !== null ? <ImpactBar value={player.impact} className="w-full max-w-[8rem]" /> : null}
          {flag ? <AnomalyFlag kind={flag.kind} reasons={flag.reasons} label="short" /> : null}
        </span>
      </span>
      <MoveMark
        direction={player.predicted_direction}
        target={player.predicted_division ?? player.division}
        tournamentGrid={tournamentGrid}
      />
    </RowButton>
  );
}
