import type { Tone } from "@/components/kit/tone";

/**
 * Tones for the "is this collector running" pill every collector shows above
 * its tiles. Only the running verb differs between them (Collecting, Polling),
 * and that is a `labels` entry, not a second style map.
 */
export const RUN_STATE_TONES: Record<string, Tone> = {
  running: "success",
  paused: "neutral"
};

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
