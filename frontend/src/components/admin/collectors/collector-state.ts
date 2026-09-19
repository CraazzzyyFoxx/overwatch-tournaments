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
