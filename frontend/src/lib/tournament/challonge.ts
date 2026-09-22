export function normalizeChallongeSlug(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";

  try {
    const url = new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`);
    if (url.hostname.includes("challonge.com")) {
      const segments = url.pathname.split("/").filter(Boolean);
      return segments.at(-1) ?? trimmed;
    }
  } catch {
    // Fall back to raw slug parsing when the value is not a valid URL.
  }

  return trimmed.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean).at(-1) ?? trimmed;
}
