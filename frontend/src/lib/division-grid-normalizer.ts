/**
 * Frontend mirror of the backend DivisionGridNormalizer.
 *
 * Normalises a player rank from a source grid version to the equivalent
 * division number in the target (workspace-default) grid version, using the
 * primary-mapping rules stored in the database.
 *
 * Usage:
 *   const normalizer = await DivisionGridNormalizer.build(targetVersion, sourceVersions);
 *   const divisionNumber = normalizer.safeNormalize(sourceVersionId, rank);
 */

import type { DivisionGridVersion, DivisionTier } from "@/types/workspace.types";
import { getTierForRank } from "@/lib/division-grid";
import workspaceService from "@/services/workspace.service";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Resolve a rank to the matching tier in a DivisionGridVersion.
 * Mirrors backend DivisionGrid.resolve_division().
 */
function resolveTier(version: DivisionGridVersion, rank: number): DivisionTier | null {
  return getTierForRank(version, rank);
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class DivisionGridNormalizationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DivisionGridNormalizationError";
  }
}

// ---------------------------------------------------------------------------
// Normalizer
// ---------------------------------------------------------------------------

export class DivisionGridNormalizer {
  private readonly targetVersion: DivisionGridVersion;
  private readonly sourceVersionsById: ReadonlyMap<number, DivisionGridVersion>;
  /**
   * source tier id → target division number (primary mapping rule).
   * Built from DivisionGridMapping.rules where is_primary = true (or the only rule).
   */
  private readonly primaryTargetNumberBySourceTierId: ReadonlyMap<number, number>;

  private constructor(
    targetVersion: DivisionGridVersion,
    sourceVersionsById: Map<number, DivisionGridVersion>,
    primaryTargetNumberBySourceTierId: Map<number, number>
  ) {
    this.targetVersion = targetVersion;
    this.sourceVersionsById = sourceVersionsById;
    this.primaryTargetNumberBySourceTierId = primaryTargetNumberBySourceTierId;
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /**
   * Normalise a rank from the given source grid version to the target grid's
   * division number.  Throws DivisionGridNormalizationError on any lookup miss.
   */
  normalize(sourceVersionId: number, rank: number): number {
    // Same grid — resolve directly in the target
    if (sourceVersionId === this.targetVersion.id) {
      const tier = resolveTier(this.targetVersion, rank);
      if (!tier) {
        throw new DivisionGridNormalizationError(
          `Cannot resolve rank ${rank} in target version ${this.targetVersion.id}`
        );
      }
      return tier.number;
    }

    const sourceVersion = this.sourceVersionsById.get(sourceVersionId);
    if (!sourceVersion) {
      throw new DivisionGridNormalizationError(
        `Source version ${sourceVersionId} was not loaded into the normalizer`
      );
    }

    const sourceTier = resolveTier(sourceVersion, rank);
    if (!sourceTier || sourceTier.id == null) {
      throw new DivisionGridNormalizationError(
        `Cannot resolve rank ${rank} in source version ${sourceVersionId}`
      );
    }

    const targetNumber = this.primaryTargetNumberBySourceTierId.get(sourceTier.id);
    if (targetNumber == null) {
      throw new DivisionGridNormalizationError(
        `No primary mapping found for source tier id=${sourceTier.id} ` +
          `(version ${sourceVersionId} → ${this.targetVersion.id})`
      );
    }

    return targetNumber;
  }

  /**
   * Same as normalize() but never throws.
   * Falls back to resolving the rank inside the source version's own grid when
   * a mapping is missing or the source version was not loaded.
   */
  safeNormalize(sourceVersionId: number, rank: number): number {
    try {
      return this.normalize(sourceVersionId, rank);
    } catch {
      const fallback = this.sourceVersionsById.get(sourceVersionId) ?? this.targetVersion;
      return resolveTier(fallback, rank)?.number ?? this.targetVersion.tiers[0]?.number ?? 1;
    }
  }

  // -------------------------------------------------------------------------
  // Factory
  // -------------------------------------------------------------------------

  /**
   * Build a normalizer by fetching all required grid mappings from the API.
   *
   * @param targetVersion  Workspace-default DivisionGridVersion (the target).
   * @param sourceVersions All DivisionGridVersions used by source tournaments.
   *                       May contain the target version — it is handled correctly.
   */
  static async build(
    targetVersion: DivisionGridVersion,
    sourceVersions: DivisionGridVersion[]
  ): Promise<DivisionGridNormalizer> {
    const sourceVersionsById = new Map<number, DivisionGridVersion>();
    for (const v of sourceVersions) {
      sourceVersionsById.set(v.id, v);
    }
    // Include the target so same-grid lookups always have a source entry.
    sourceVersionsById.set(targetVersion.id, targetVersion);

    // Index target tiers by their DB id for O(1) rule resolution.
    const targetTierNumberById = new Map<number, number>(
      targetVersion.tiers
        .filter((t): t is DivisionTier & { id: number } => t.id != null)
        .map((t) => [t.id, t.number])
    );

    const primaryTargetNumberBySourceTierId = new Map<number, number>();

    // Fetch mappings in parallel for all foreign (non-target) source versions.
    const foreignIds = [...sourceVersionsById.keys()].filter((id) => id !== targetVersion.id);

    await Promise.all(
      foreignIds.map(async (sourceVersionId) => {
        try {
          const mapping = await workspaceService.getDivisionGridMapping(
            sourceVersionId,
            targetVersion.id
          );

          // Group rules by source tier so we can detect single-rule entries.
          const rulesBySourceTierId = new Map<number, typeof mapping.rules>();
          for (const rule of mapping.rules) {
            const bucket = rulesBySourceTierId.get(rule.source_tier_id) ?? [];
            bucket.push(rule);
            rulesBySourceTierId.set(rule.source_tier_id, bucket);
          }

          for (const [sourceTierId, rules] of rulesBySourceTierId) {
            if (primaryTargetNumberBySourceTierId.has(sourceTierId)) continue;

            // Prefer the explicitly-flagged primary rule.
            const primaryRule =
              rules.find((r) => r.is_primary) ?? (rules.length === 1 ? rules[0] : null);
            if (!primaryRule) continue;

            const targetNumber = targetTierNumberById.get(primaryRule.target_tier_id);
            if (targetNumber != null) {
              primaryTargetNumberBySourceTierId.set(sourceTierId, targetNumber);
            }
          }
        } catch {
          // Mapping not found or fetch failed — safeNormalize() will fall back
          // to raw resolution inside the source grid for this version.
        }
      })
    );

    return new DivisionGridNormalizer(
      targetVersion,
      sourceVersionsById,
      primaryTargetNumberBySourceTierId
    );
  }
}
