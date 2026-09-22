/**
 * Where a room hands the viewer back when it is done with them.
 *
 * Carried as a query param rather than inferred from `document.referrer`: the
 * param survives a reload, it is shareable, and it is the only thing that can
 * tell "opened from the bracket" apart from "opened from the encounter page".
 * The pre-game room is reachable from both and used to send everyone to the
 * encounter page, which is the wrong place to be mid-tournament — the bracket
 * is where the next match is picked.
 */
export const RETURN_TO_PARAM = "from";

/**
 * `raw` when it is a same-origin path we may navigate to, else `fallback`.
 *
 * Anything that could leave the site is dropped rather than repaired: an
 * absolute URL, a protocol-relative `//host`, or the backslash variants
 * browsers normalise to it. A rejected value is not worth a clever parse when
 * the fallback is always a correct destination.
 */
export function safeReturnPath(raw: string | null | undefined, fallback: string): string {
  if (!raw || !raw.startsWith("/")) return fallback;
  if (raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  return raw;
}

/** `href` with `from` attached, so whatever `href` opens can come back here. */
export function withReturnTo(href: string, from: string): string {
  return `${href}${href.includes("?") ? "&" : "?"}${RETURN_TO_PARAM}=${encodeURIComponent(from)}`;
}
