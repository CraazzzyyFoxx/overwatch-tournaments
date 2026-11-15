import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";

/**
 * A collector's one-word verdict for the tab bar's health dot.
 *
 * The word itself lives in `collectors.common.health.<state>`: the dot is
 * computed by plain functions the tab bar calls for all three collectors, and
 * those cannot reach a translator.
 */
export interface CollectorHealth {
  tone: Tone;
  state: "healthy" | "degraded" | "failing" | "paused";
}
