import type React from "react";

import type { BalanceJobResult, BalancerConfig } from "@/types/balancer.types";

import { createVariantLabel } from "./balancer-page-helpers";
import { convertBalanceResponseToInternalPayload, type BalanceVariant } from "./workspace-helpers";

export type JobResultContext = {
  /** Pool players excluded from the run (shown as a badge on the first variant). */
  skipped?: number;
  /** Config used for the run; attached to the variant for re-save. */
  config?: BalancerConfig | null;
};

/**
 * Append the generated variants from a completed balance job to local state and
 * select the best (first) one.
 *
 * Extracted from the run mutation so the realtime `balancer_job.succeeded`
 * handler can apply the result for EVERY viewer — the initiator and anyone else
 * with the page open — through a single code path.
 */
export function appendGeneratedVariants(
  setVariants: React.Dispatch<React.SetStateAction<BalanceVariant[]>>,
  setActiveVariantId: React.Dispatch<React.SetStateAction<string | null>>,
  result: BalanceJobResult,
  context: JobResultContext = {}
): void {
  const { skipped = 0, config = null } = context;
  // Pre-generate stable IDs outside the updater so setActiveVariantId and
  // setVariants agree on the same ID even if React invokes the updater more
  // than once (concurrent mode).
  const timestamp = Date.now();
  const newIds = result.variants.map((_, index) => `generated-${timestamp}-${index}`);

  setVariants((current) => {
    const next = [...current];
    const generatedCount = next.filter((variant) => variant.source === "generated").length;
    result.variants.forEach((variant, batchIndex) => {
      next.push({
        id: newIds[batchIndex],
        label: createVariantLabel(generatedCount + batchIndex + 1),
        payload: convertBalanceResponseToInternalPayload(variant),
        source: "generated",
        config: config ?? null,
        skippedCount: batchIndex === 0 && skipped > 0 ? skipped : undefined
      });
    });
    return next;
  });

  // The solver returns variants best-first (lowest composite_score), so
  // auto-select the first one — the highest-quality balance.
  const bestId = newIds[0];
  if (bestId) {
    setActiveVariantId(bestId);
  }
}
