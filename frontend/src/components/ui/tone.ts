/**
 * Tone vocabulary for tinted status surfaces, on the `--aqt-*` palette.
 *
 * One tint for every chip, alert, toast and "chosen" state: a 32% rim and a
 * 12% wash of `--tone-hue`, the text in the hue itself (Button `accent` is the
 * same mix over teal). `neutral` is the same mix over `--aqt-fg-muted`, which
 * lands about on `--aqt-overlay-3` with a `--aqt-border-3` rim, so it still
 * reads on a card. Index these maps instead of re-typing the classes; the
 * Tailwind `success`/`warning`/`info`/`danger` colours point at the same hues.
 */
export type Tone = "neutral" | "accent" | "success" | "warning" | "info" | "danger";

/** The tint over `--tone-hue`. A hue no `Tone` names (a lifecycle status) sets the variable itself. */
export const TONE_TINT =
  "border-[color:color-mix(in_srgb,var(--tone-hue)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--tone-hue)_12%,transparent)] text-[color:var(--tone-hue)]";

/** `--tone-hue` per tone, for a surface that spends the hue its own way (a toast's rim and icon, an active tab's count). */
export const TONE_HUE: Record<Tone, string> = {
  neutral: "[--tone-hue:var(--aqt-fg-muted)]",
  accent: "[--tone-hue:var(--aqt-teal)]",
  success: "[--tone-hue:var(--aqt-emerald)]",
  warning: "[--tone-hue:var(--aqt-amber)]",
  info: "[--tone-hue:var(--aqt-blue)]",
  danger: "[--tone-hue:var(--aqt-rose)]"
};

/** Tinted surface: border colour + wash + readable text. The caller adds `border`. */
export const TONE_CLASS: Record<Tone, string> = {
  neutral: `${TONE_TINT} ${TONE_HUE.neutral}`,
  accent: `${TONE_TINT} ${TONE_HUE.accent}`,
  success: `${TONE_TINT} ${TONE_HUE.success}`,
  warning: `${TONE_TINT} ${TONE_HUE.warning}`,
  info: `${TONE_TINT} ${TONE_HUE.info}`,
  danger: `${TONE_TINT} ${TONE_HUE.danger}`
};

/** Text-only tone, for icons and inline labels on an untinted surface. */
export const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-[color:var(--aqt-fg-muted)]",
  accent: "text-[color:var(--aqt-teal)]",
  success: "text-[color:var(--aqt-emerald)]",
  warning: "text-[color:var(--aqt-amber)]",
  info: "text-[color:var(--aqt-blue)]",
  danger: "text-[color:var(--aqt-rose)]"
};
