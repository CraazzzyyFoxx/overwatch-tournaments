import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { authService } from "@/services/auth.service";
import { getAccessToken } from "@/lib/auth-cookies";
import { safeRedirectTarget } from "@/lib/oauth-callback";
import { publicOrigin } from "@/lib/request-origin";

// Task 10R fix 1: the single-use, HOST-ONLY guard cookie set by
// oauth-login.ts's custom-domain apex bounce, on THIS exact domain, before
// the flow ever left for the apex. Its raw value is required alongside the
// ticket EVEN THOUGH the caller also presents a valid bearer below --
// without it, a victim's own live session could be lured into completing an
// attacker's link ticket (reverse CSRF / account takeover via linking, the
// vulnerability this fix closes). See oauth-login.ts's module docstring.
const GUARD_COOKIE = "owt_xdomain_guard";

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
// GUARD_COOKIE above on every outcome (host-only, no `domain` attribute --
// must match exactly what oauth-login.ts set, or the delete won't take).
function clearGuardCookie(response: NextResponse): void {
  response.cookies.delete({ name: GUARD_COOKIE, path: "/" });
}

function errorRedirect(origin: string, errorCode: string): NextResponse {
  const errorUrl = new URL("/", origin);
  errorUrl.searchParams.set("auth_error", errorCode);
  const response = NextResponse.redirect(errorUrl);
  clearGuardCookie(response);
  return response;
}

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
    return errorRedirect(currentOrigin, "invalid_state");
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
    return errorRedirect(currentOrigin, "invalid_state");
  }

  try {
    await authService.completeLink(ticket, accessToken, guard);
    const response = NextResponse.redirect(safeRedirectTarget(next, currentOrigin));
    clearGuardCookie(response);
    return response;
  } catch (err) {
    console.error("Link ticket exchange error:", err);
    return errorRedirect(currentOrigin, "exchange_failed");
  }
}
