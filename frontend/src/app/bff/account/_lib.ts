import { NextResponse } from "next/server";

import { authServiceBase } from "@/lib/api/routes";
import { requireAccessToken } from "@/lib/auth/cookies";

// Why /bff/* exists at all: next.config.mjs's rewrites forward only /api/v1 and
// /api/v2 to the gateway, so `/bff/*` is never proxied — it is served by Next
// itself. That is the point: these endpoints authenticate from the httpOnly
// session cookie, which browser JS cannot read and therefore cannot send to the
// gateway as a bearer.

const AUTH_SERVICE_URL = authServiceBase();

type AuthServiceRequest = {
  method?: string;
  /**
   * Lazy on purpose: `request.json()` rejects on a malformed body, and reading
   * it inside this helper's `try` keeps that answer a JSON `{ detail }` 500
   * instead of an opaque framework error.
   */
  body?: () => Promise<unknown>;
  /** `detail` returned when the upstream body is not JSON, or the call failed. */
  errorDetail: string;
};

/**
 * The one shape every `/bff/account/**` handler had inline: require the session
 * cookie, call identity-svc with it as a bearer, and pass the upstream status
 * and body straight back. Responses are forwarded verbatim so the screens keep
 * reading the upstream's own error payloads (e.g. the quota gate's 422
 * `quota_above_inherited` with its offending dimension).
 */
export async function authServiceRequest(
  path: string,
  { method = "GET", body, errorDetail }: AuthServiceRequest
): Promise<NextResponse> {
  const accessToken = await requireAccessToken();
  if (accessToken instanceof NextResponse) {
    return accessToken;
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json"
      },
      body: body ? JSON.stringify(await body()) : undefined,
      cache: "no-store"
    });

    // 204 carries no body: parsing it would throw and turn a successful revoke
    // into the generic failure detail.
    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }

    const payload = await response.json().catch(() => ({ detail: errorDetail }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: errorDetail }, { status: 500 });
  }
}
