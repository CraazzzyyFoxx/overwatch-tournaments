/**
 * Winrate → accent color. The single winrate-threshold function in the app;
 * `HeroUserStatsPopover` used to carry a second, coarser copy.
 *
 * Buckets and hue order are unchanged (red → orange → yellow → green → cyan →
 * purple); the values moved from raw pastel hex onto the `--aqt-*` palette so
 * they follow workspace theming.
 */
export const getWinrateColor = (winrate: number) => {
  const fraction = winrate > 1 ? winrate / 100 : winrate;
  if (fraction < 0.46) return "var(--aqt-rose)";
  if (fraction < 0.5) return "var(--aqt-amber)";
  if (fraction < 0.53) return "var(--aqt-gold)";
  if (fraction < 0.58) return "var(--aqt-emerald)";
  if (fraction < 0.64) return "var(--aqt-teal)";
  return "var(--aqt-violet)";
};
