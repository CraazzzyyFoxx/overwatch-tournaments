import type { FilterDef, FilterOption } from "@/components/kit/useFilters";
import type { PregameRoomRow } from "@/types/admin.types";

import { PHASE_LABEL } from "./model";

/**
 * The chips that narrow the room list.
 *
 * Both option lists are derived from the rows already on screen rather than
 * fetched: the overview is one whole-tournament read, so a stage or a phase
 * nobody is in would only offer an empty result. The counts come free with it.
 */
export function pregameRoomFilterDefs(rooms: readonly PregameRoomRow[]): FilterDef[] {
  const stages = new Map<string, FilterOption>();
  const phases = new Map<string, FilterOption>();

  for (const room of rooms) {
    const stageKey = room.stage_id == null ? "none" : String(room.stage_id);
    const stage = stages.get(stageKey);
    if (stage) stage.count = (stage.count ?? 0) + 1;
    else stages.set(stageKey, { value: stageKey, label: room.stage_name ?? "Unassigned", count: 1 });

    const phase = phases.get(room.phase);
    if (phase) phase.count = (phase.count ?? 0) + 1;
    else phases.set(room.phase, { value: room.phase, label: PHASE_LABEL[room.phase], count: 1 });
  }

  const defs: FilterDef[] = [
    { key: "attention", label: "Needs attention", kind: "toggle" },
    // Multi rather than single: "who is still in veto or bans" is the question
    // an organizer actually asks before a round starts.
    { key: "phase", label: "Phase", kind: "multi", options: [...phases.values()] }
  ];
  if (stages.size > 1) {
    defs.push({ key: "stage", label: "Stage", kind: "single", options: [...stages.values()] });
  }
  return defs;
}
