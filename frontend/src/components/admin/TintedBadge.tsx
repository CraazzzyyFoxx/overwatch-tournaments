import { StatusPill } from "@/components/kit/StatusPill";
import type { Tone } from "@/components/kit/tone";

interface TintedBadgeProps {
  /** Machine value the badge represents; `null`/`undefined` renders `fallback`. */
  value: string | null | undefined;
  /** Tone per value (e.g. `{ ok: "success" }`); an unrecognised or missing
   *  value falls back to the neutral tone. */
  tones: Record<string, Tone>;
  /** Optional display wording per value; falls back to the raw value. */
  labels?: Record<string, string>;
  /** Text shown when `value` is null/undefined. */
  fallback: string;
  /**
   * Leading dot in the badge's own tone, for a collector's running/paused
   * state. Purely decorative — the label beside it already carries the state,
   * which is why the dot is `aria-hidden`.
   */
  dot?: boolean;
}

/**
 * A `StatusPill` whose tone is looked up from a machine value: every collector
 * (rank, subscriptions, streams) renders its status through this, supplying
 * its own vocabulary as data.
 *
 * Callers name a `Tone`, not a class string: indexing `TONE_CLASS` at every
 * call site is how three collectors ended up with three near-identical style
 * maps, and it let a page reach past the tone vocabulary into arbitrary
 * classes.
 */
export function TintedBadge({ value, tones, labels, fallback, dot }: Readonly<TintedBadgeProps>) {
  const tone = tones[value ?? ""] ?? "neutral";
  return (
    <StatusPill tone={tone} dot={dot}>
      {value ? (labels?.[value] ?? value) : fallback}
    </StatusPill>
  );
}
