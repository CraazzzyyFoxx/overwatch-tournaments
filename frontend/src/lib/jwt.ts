// Client-safe JWT helpers. We only decode the (unverified) payload to read the
// `exp` claim and decide when to proactively refresh the access token — the
// gateway is the sole authority that verifies the signature. `atob` is used so
// the same module works both in the browser and in Node route handlers.

const DEFAULT_REFRESH_SKEW_MS = 60_000;

export function decodeJwtPayload(token: string): Record<string, unknown> | undefined {
  const parts = token.split(".");
  if (parts.length < 2) return undefined;

  try {
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const json = atob(padded);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return undefined;
  }
}

// Expiry of the token in epoch milliseconds, or undefined if it can't be read.
export function getTokenExpMs(token: string): number | undefined {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  return typeof exp === "number" ? exp * 1000 : undefined;
}

// True when the token is missing, already expired, or within `skewMs` of expiry
// (so we should refresh ahead of time). When `exp` can't be decoded we return
// false for a present token — let the reactive 401 path handle it rather than
// forcing a refresh on every call.
export function isExpiredOrNearExpiry(
  token: string | undefined,
  skewMs: number = DEFAULT_REFRESH_SKEW_MS,
): boolean {
  if (!token) return true;
  const expMs = getTokenExpMs(token);
  if (expMs === undefined) return false;
  return expMs <= Date.now() + skewMs;
}

// Remaining lifetime of the token in whole seconds, clamped to >= 0. Falls back
// to `fallbackSeconds` when `exp` can't be decoded. Used to align cookie
// lifetimes with the actual token lifetime.
export function getTokenMaxAgeSeconds(token: string, fallbackSeconds: number): number {
  const expMs = getTokenExpMs(token);
  if (expMs === undefined) return fallbackSeconds;
  return Math.max(0, Math.floor((expMs - Date.now()) / 1000));
}
