/** Shared value formatters (framework-agnostic, safe in server & client). */

export const formatPercent = (value: number, digits = 0) => `${(value * 100).toFixed(digits)}%`;

export const formatSeconds = (secondsRaw: number) => {
  const seconds = Math.max(0, Math.floor(secondsRaw));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};
