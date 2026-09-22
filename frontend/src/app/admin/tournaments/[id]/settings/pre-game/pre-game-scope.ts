import type { PickBanConfig, PickBanKind } from "@/types/tournament.types";
import {
  findInheritedConfig,
  isRulesTemplate,
  pickBanDraftFromConfig,
  sameRuleValues
} from "@/lib/tournament/pick-ban-config";

/** One node of the scope tree: the tournament, a stage, or a stage's round. */
export interface PreGameScope {
  stageId: number | null;
  round: number | null;
}

export const TOURNAMENT_SCOPE_VALUE = "tournament";

/** Steps of one scope's configuration, in the order they are authored (F9 ·3). */
export const PRE_GAME_STEPS = ["pool", "sequence", "sides"] as const;
export type PreGameStep = (typeof PRE_GAME_STEPS)[number];

export const PRE_GAME_KINDS = ["map", "hero"] as const;

/**
 * `?scope=` (§1.2).
 *
 * A round is written as `round:<stageId>:<round>` rather than the plan's bare
 * `round:<n>`: a config's scope is the pair (stage, round) — round numbers
 * repeat across stages, and `round:2` alone names two different scopes in a
 * two-stage tournament.
 */
export function encodePreGameScope(scope: PreGameScope): string {
  if (scope.stageId == null) return TOURNAMENT_SCOPE_VALUE;
  return scope.round == null ? `stage:${scope.stageId}` : `round:${scope.stageId}:${scope.round}`;
}

/** `null` for an absent or unparseable value: nothing is selected. */
export function decodePreGameScope(value: string | null | undefined): PreGameScope | null {
  if (!value) return null;
  if (value === TOURNAMENT_SCOPE_VALUE) return { stageId: null, round: null };

  const stageMatch = /^stage:(-?\d+)$/.exec(value);
  if (stageMatch) return { stageId: Number(stageMatch[1]), round: null };

  const roundMatch = /^round:(-?\d+):(-?\d+)$/.exec(value);
  if (roundMatch) return { stageId: Number(roundMatch[1]), round: Number(roundMatch[2]) };

  return null;
}

/** The config saved at exactly this scope, if any. */
export function findScopeConfig(
  kind: PickBanKind,
  scope: PreGameScope,
  configs: PickBanConfig[]
): PickBanConfig | null {
  return (
    configs.find(
      (config) =>
        config.kind === kind &&
        config.stage_id === scope.stageId &&
        config.round === scope.round
    ) ?? null
  );
}

/**
 * What the tree says about a scope.
 *
 * - `own` — a saved config that actually decides something here;
 * - `template` — a saved config with no pool: rules for narrower scopes to
 *   inherit, playing nothing itself;
 * - `redundant` — a saved config whose rules only repeat the scope above it;
 * - `inherited` — no config here, but an ancestor's applies;
 * - `none` — no rules reach this scope at all, so its room stays closed.
 */
export type ScopeConfigState = "own" | "template" | "redundant" | "inherited" | "none";

export function scopeConfigState(
  kind: PickBanKind,
  scope: PreGameScope,
  configs: PickBanConfig[]
): ScopeConfigState {
  const own = findScopeConfig(kind, scope, configs);
  const inherited = findInheritedConfig(kind, scope.stageId, scope.round, configs);

  if (own != null) {
    // Checked before "redundant": a pool-less row repeats its parent's rules by
    // construction (it was prefilled from them), and calling that redundant
    // would hide the one thing it is missing.
    if (isRulesTemplate(pickBanDraftFromConfig(own))) return "template";
    return inherited != null &&
      sameRuleValues(pickBanDraftFromConfig(own), pickBanDraftFromConfig(inherited))
      ? "redundant"
      : "own";
  }
  return inherited != null ? "inherited" : "none";
}
