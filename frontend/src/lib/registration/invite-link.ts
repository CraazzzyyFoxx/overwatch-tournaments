/**
 * The shareable form of a team invite token.
 *
 * The token rides in the URL **fragment**, not the path or query string. A
 * fragment is the one part of a URL a browser never transmits: it stays out of
 * the Next.js access log, out of the API gateway's, and out of every `Referer`
 * header the landing page emits. The backend route table pins the same rule from
 * the other side — `POST /invites/preview` takes the token in the body, so the
 * only request the invitee makes carries it nowhere loggable either.
 *
 * Browser history still holds it, which is inherent to any link you can paste.
 * That is the residual risk a single-use, expiring, revocable token is for.
 */
export const INVITE_LINK_PATH = "/invite";

export function buildInviteLink(token: string, origin?: string): string {
  // `origin` is injectable because this is called from a client component in a
  // codebase that also renders on the server; a bare `window` reference would be
  // a runtime error waiting for the first server render of a page that imports it.
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  return `${base}${INVITE_LINK_PATH}#${token}`;
}

/**
 * The token from a landing URL's fragment, or null.
 *
 * Tolerates the leading `#` being present or absent, and treats an empty
 * fragment as absent rather than as an empty token — the page must be able to
 * tell "you arrived without a link" apart from "your link is invalid", because
 * those have different recourses.
 *
 * Strips EVERY whitespace character, not just the ends: a token is a bare
 * base64url string and never legitimately contains one, so a stray space or
 * line break picked up while the link was pasted, wrapped, or forwarded
 * through a chat client can only be corruption — removing it can rescue a
 * mangled link but can never turn one valid token into another.
 */
export function readInviteTokenFromHash(hash: string): string | null {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const token = decodeURIComponent(raw).replace(/\s+/g, "");
  return token.length > 0 ? token : null;
}
