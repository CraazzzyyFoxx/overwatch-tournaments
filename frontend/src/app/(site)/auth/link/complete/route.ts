import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { revalidateTag } from "next/cache";
import { authService, OAuthLinkFailedError } from "@/services/auth.service";
import { getAccessToken } from "@/lib/auth/cookies";
import { GUARD_COOKIE } from "@/lib/auth/cookie-names";
import { clearGuardCookie, guardTicketErrorRedirect, safeRedirectTarget } from "@/lib/auth/oauth-callback";
import { publicOrigin } from "@/lib/site/request-origin";

// Far side of the custom-domain account-linking end-ticket (Task 10R). This
// route runs ON the workspace's custom domain itself -- never the platform
// apex -- after oauth-callback.ts's "link" branch has already
// authoritatively verified (via isVerifiedTenantOrigin/by_host,
// buildLinkTicketRedirect) that this exact origin is a real, resolvable
// workspace before ever redirecting the browser here. That check happened
// once, upstream; this route trusts it and focuses on resolving the LOCAL
// live session and redeeming the ticket against it.
//
// SECURITY INVARIANT #1: the linked-to site account is resolved from THIS
// request's own live session cookie -- the ticket carries ONLY the provider
// identity (see pending_link_tickets.py), never a site user id, and nothing
// here reads one from any URL/query param either. No session on this domain
// means there is nothing to link to, so this bounces to login rather than
// guessing or falling back to any identity the ticket might carry.
//
// Sets no SESSION cookies: unlike /auth/sso/route.ts (which establishes a
// brand-new session from a ticket that DOES carry session tokens), linking
// never changes the caller's session here -- it only calls an authenticated
// RPC with the session that already exists. It DOES clear the single-use
// GUARD_COOKIE on every outcome (via guardTicketErrorRedirect/
// clearGuardCookie) -- see lib/auth/oauth-callback.ts for the shared definition
// and clear helper, which /auth/sso/route.ts also uses.

function loginRedirect(origin: string, next: string): NextResponse {
  const loginUrl = new URL("/", origin);
  loginUrl.searchParams.set("login", "1");
  loginUrl.searchParams.set("next", next);
  const response = NextResponse.redirect(loginUrl);
  clearGuardCookie(response);
  return response;
}

export async function GET(request: Request) {
  // Runs ON the workspace's custom domain. request.url's host behind the edge
  // is the internal bind addr (0.0.0.0:3000), so derive the real origin from
  // the forwarded headers — otherwise the post-link redirect (e.g. back to
  // /?settings=profile) sends the user to https://0.0.0.0:3000. See request-origin.ts.
  const currentOrigin = publicOrigin(request);
  const searchParams = new URL(request.url).searchParams;
  const ticket = searchParams.get("ticket");
  const next = searchParams.get("next") || "/account";

  if (!ticket) {
    return guardTicketErrorRedirect(currentOrigin, "invalid_state");
  }

  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);

  if (!accessToken) {
    // Can't link without a live session on THIS domain (SECURITY INVARIANT
    // #1) -- send the user to log in, then retry from account settings.
    // Never fall back to any identity the ticket carries.
    return loginRedirect(currentOrigin, next);
  }

  const guard = cookieStore.get(GUARD_COOKIE)?.value;

  // Fail closed (Task 10R fix 1): with no guard cookie there is nothing to
  // bind this redemption to the browser that started the flow -- identity-svc
  // would reject a missing `guard` anyway, but there's no reason to spend an
  // RPC round trip (and burn the single-use ticket) on a request that's
  // already missing something required.
  if (!guard) {
    return guardTicketErrorRedirect(currentOrigin, "invalid_state");
  }

  try {
    await authService.completeLink(ticket, accessToken, guard);
    // Best-effort: bust the Next Data Cache "users" tag so the public profile
    // reflects the newly linked social account immediately (react-query
    // mutations use revalidateUser). The link is already committed, so a
    // cache-bust failure must never fail the request — worst case the profile
    // self-heals within the 300s revalidate window.
    try {
      revalidateTag("users", "max");
    } catch {
      // cache invalidation is best-effort
    }
    const response = NextResponse.redirect(safeRedirectTarget(next, currentOrigin));
    clearGuardCookie(response);
    return response;
  } catch (err) {
    console.error("Link ticket exchange error:", err);
    // A refusal identity-svc can explain (409: the provider account is already
    // linked to another account here) carries its own code, so the user gets
    // the actual reason and the way out. No provider name on this path: unlike
    // the apex callback, this route never sees the signed state — only an
    // opaque ticket — so the toast falls back to a generic provider label.
    if (err instanceof OAuthLinkFailedError) {
      return guardTicketErrorRedirect(currentOrigin, err.code);
    }
    return guardTicketErrorRedirect(currentOrigin, "exchange_failed");
  }
}
