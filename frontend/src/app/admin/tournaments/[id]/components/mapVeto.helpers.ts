import type { MapVetoConfig, Stage, VetoPreset, VetoSequenceToken } from "@/types/tournament.types";

export type VetoLevelType = "tournament" | "stage" | "stage_round";
export type VetoStepAction = "ban" | "pick" | "decider";
export type VetoStepSide = "first" | "second";

export const BO3_SEQUENCE: VetoSequenceToken[] = [
  "ban_first",
  "ban_second",
  "pick_first",
  "pick_second",
  "decider"
];

export const BO5_SEQUENCE: VetoSequenceToken[] = [
  "ban_first",
  "ban_second",
  "pick_first",
  "pick_second",
  "pick_first",
  "pick_second",
  "decider"
];

/** Bo1: alternating bans (first team starts) until one map remains, then a decider. */
export function buildBo1Sequence(poolSize: number): VetoSequenceToken[] {
  const sequence: VetoSequenceToken[] = [];
  for (let index = 0; index < poolSize - 1; index += 1) {
    sequence.push(index % 2 === 0 ? "ban_first" : "ban_second");
  }
  sequence.push("decider");
  return sequence;
}

export function tokenAction(token: VetoSequenceToken): VetoStepAction {
  if (token === "decider") return "decider";
  return token.startsWith("ban") ? "ban" : "pick";
}

export function tokenSide(token: VetoSequenceToken): VetoStepSide | null {
  if (token === "decider") return null;
  return token.endsWith("_first") ? "first" : "second";
}

export function buildToken(action: VetoStepAction, side: VetoStepSide): VetoSequenceToken {
  if (action === "decider") return "decider";
  return `${action}_${side}` as VetoSequenceToken;
}

export function tokenLabel(token: VetoSequenceToken): string {
  if (token === "decider") return "Decider";
  const action = tokenAction(token) === "ban" ? "Ban" : "Pick";
  return `${action} ${tokenSide(token) === "first" ? "1st" : "2nd"}`;
}

/** Mirrors backend config-upsert validation so errors surface before save. */
export function validateVetoConfigForm(
  sequence: VetoSequenceToken[],
  mapIds: number[]
): string[] {
  const errors: string[] = [];
  if (mapIds.length === 0) {
    errors.push("Select at least one map for the pool.");
  }
  if (sequence.length === 0) {
    errors.push("The sequence must contain at least one step.");
  } else {
    const deciderCount = sequence.filter((token) => token === "decider").length;
    if (deciderCount > 1) {
      errors.push("Only one decider step is allowed.");
    } else if (deciderCount === 1 && sequence[sequence.length - 1] !== "decider") {
      errors.push("The decider step must be the last step.");
    }
    if (!sequence.some((token) => tokenAction(token) !== "ban")) {
      errors.push("The sequence needs at least one pick or a decider.");
    }
  }
  if (mapIds.length > 0 && sequence.length > mapIds.length) {
    errors.push(
      `The sequence has ${sequence.length} steps but the pool only has ${mapIds.length} maps.`
    );
  }
  return errors;
}

export function getVetoLevelLabel(
  config: MapVetoConfig,
  stagesById: Map<number, Stage>
): string {
  if (config.stage_id == null) return "Tournament default";
  const stageName = stagesById.get(config.stage_id)?.name ?? `Stage #${config.stage_id}`;
  if (config.round == null) return `Stage: ${stageName}`;
  return `Stage: ${stageName} · Round ${config.round}`;
}

export function getVetoPresetLabel(preset: VetoPreset | null): string {
  switch (preset) {
    case "bo1":
      return "Bo1";
    case "bo3":
      return "Bo3";
    case "bo5":
      return "Bo5";
    default:
      return "Custom";
  }
}
