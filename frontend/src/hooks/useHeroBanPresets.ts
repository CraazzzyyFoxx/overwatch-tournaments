import { useQuery } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import pickBanService from "@/services/pickBan.service";
import type { PickBanPreset, PickBanRulesCatalog, PickBanStepAction } from "@/types/tournament.types";

/**
 * The presets a pickup mix may play (spec §8.1), in catalog order. The server decides (`mix_eligible`, the same
 * `pick_ban_rules` check the mix writer runs), so this never re-evaluates a ruleset.
 */
export function mixBanPresetIds(catalog: PickBanRulesCatalog | undefined): string[] {
  return (catalog?.presets ?? []).filter((preset) => preset.mix_eligible).map((preset) => preset.id);
}

/** A mix's host clocks over its preset: the preset's own seconds (null: untimed), absent for a step it never takes. */
export type MixPresetClocks = { ban?: number | null; pick?: number | null };

/** Which host clock a step runs on, as the room applies them: a protect on the ban clock; a side pick or an assignment on none. */
const CLOCK_OF: Partial<Record<PickBanStepAction, keyof MixPresetClocks>> = { ban: "ban", protect: "ban", pick: "pick" };

export function presetClocks(preset: PickBanPreset | undefined): MixPresetClocks {
  const clocks: MixPresetClocks = {};
  for (const step of preset?.ruleset.phases.flatMap((phase) => phase.steps) ?? []) {
    const clock = CLOCK_OF[step.action];
    if (clock != null && !(clock in clocks)) clocks[clock] = step.timer_seconds ?? preset?.ruleset.timer_seconds ?? null;
  }
  return clocks;
}

/**
 * Whether a preset has anything for the host's pickers to apply to: a turn-by-turn player pick (the free order), any
 * player pick at all (captains only). An assignment is a captain's already.
 */
export type MixPresetPickers = { turns: boolean; players: boolean };

export function presetPickers(preset: PickBanPreset | undefined): MixPresetPickers {
  const members = preset?.ruleset.phases.flatMap((phase) => phase.steps).map((step) => step.member) ?? [];
  return { turns: members.includes("next"), players: members.some((member) => member != null) };
}

function useRulesCatalog(discipline: string | null | undefined): PickBanRulesCatalog | undefined {
  return useQuery({
    queryKey: tournamentQueryKeys.pickBanRulesCatalog(discipline),
    queryFn: ({ signal }) => pickBanService.getRulesCatalog(discipline as string, signal),
    enabled: Boolean(discipline),
    staleTime: Infinity,
  }).data;
}

/** One game's mix presets; empty while the game is unknown or its catalog loads. */
export function useHeroBanPresets(discipline: string | null | undefined): string[] {
  return mixBanPresetIds(useRulesCatalog(discipline));
}

/** The clocks a host may set over one of the game's presets; empty for no preset, or while the catalog loads. */
export function useMixPresetClocks(discipline: string | null | undefined, code: string | null): MixPresetClocks {
  return presetClocks(useRulesCatalog(discipline)?.presets.find((preset) => preset.id === code));
}

/** What the pickers apply to over one of the game's presets; nothing for no preset, or while the catalog loads. */
export function useMixPresetPickers(discipline: string | null | undefined, code: string | null): MixPresetPickers {
  return presetPickers(useRulesCatalog(discipline)?.presets.find((preset) => preset.id === code));
}
