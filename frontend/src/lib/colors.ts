/** Below this many games a winrate is greyed and any comparison hidden (DESIGN.md §11). */
export const LOW_SAMPLE_GAMES = 10;

/** `color` at `percent`% over transparent: the wash and border every role/accent tint is drawn from. */
export const tint = (color: string, percent: number): string =>
  `color-mix(in srgb, ${color} ${percent}%, transparent)`;

/**
 * Winrate (0–100) → accent color on the design-book §1 thresholds:
 * ≥60 good · 50–59 mid · <50 bad.
 *
 * `lowSample` greys the number out entirely: a 100% winrate over three maps is
 * noise, and painting it green reads as a ranking it has not earned.
 */
export const winrateColor = (pct: number, lowSample = false): string => {
  if (lowSample) return "var(--aqt-fg-faint)";
  return { success: "var(--aqt-emerald)", warning: "var(--aqt-amber)", danger: "var(--aqt-rose)" }[
    winrateTone(pct)
  ];
};

/** `winrateColor`'s bands as a `Tone`, for a primitive that takes one (`Progress`). */
export const winrateTone = (pct: number): "success" | "warning" | "danger" =>
  pct >= 60 ? "success" : pct >= 50 ? "warning" : "danger";

/** 0–100 impact/percentile score → ramp: high up-green, low rose, the middle blue. */
export const getImpactColor = (value: number) => {
  if (value >= 66) return "var(--aqt-up)";
  if (value <= 34) return "var(--aqt-rose)";
  return "var(--aqt-blue)";
};
