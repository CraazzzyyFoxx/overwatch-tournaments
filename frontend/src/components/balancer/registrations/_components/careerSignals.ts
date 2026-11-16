import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";

import type { CareerSignal } from "@/types/career-signals.types";

/** Most actionable first (the server sends them in this order too; sorted here so the column never depends on it). */
const ORDER = [
  "profile_not_found",
  "previously_found",
  "low_hours_high_rank",
  "inactive",
  "profile_private",
  "never_collected",
  "renamed"
];

/** Warning for what the organizer should chase, muted for what is merely unknown, accent for information. */
const TONES: Record<string, Tone> = {
  profile_not_found: "warning",
  previously_found: "warning",
  low_hours_high_rank: "warning",
  inactive: "warning",
  profile_private: "neutral",
  never_collected: "neutral",
  renamed: "accent"
};

const rank = (code: string) => {
  const index = ORDER.indexOf(code);
  return index < 0 ? ORDER.length : index;
};

/** A code this client does not know still shows, as neutral, after the known ones. */
export const signalTone = (code: string): Tone => TONES[code] ?? "neutral";

export const sortSignals = (signals: readonly CareerSignal[]): CareerSignal[] =>
  [...signals].sort((a, b) => rank(a.code) - rank(b.code));
