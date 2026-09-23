import { authServiceBase } from "@/lib/api/routes";
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getAccessToken } from "@/lib/auth/cookies";

const AUTH_SERVICE_URL = authServiceBase();

type RouteContext = {
  params: Promise<{ apiKeyId: string }>;
};

function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

export async function GET(_request: NextRequest, context: RouteContext) {
  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);
  const { apiKeyId } = await context.params;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    const response = await fetch(
      `${AUTH_SERVICE_URL}/api-keys/${encodeURIComponent(apiKeyId)}/quota`,
      { method: "GET", headers: authHeaders(accessToken), cache: "no-store" }
    );
    const payload = await response
      .json()
      .catch(() => ({ detail: "Failed to load quota usage" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Failed to load quota usage" }, { status: 500 });
  }
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);
  const { apiKeyId } = await context.params;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    // Forwarded verbatim: the quota gate answers 422 `quota_above_inherited`
    // with the offending dimension in the body, and the screen marks that field
    // — rewriting the payload here would also have to rewrite that answer.
    const body = await request.json();
    const response = await fetch(
      `${AUTH_SERVICE_URL}/api-keys/${encodeURIComponent(apiKeyId)}/quota`,
      { method: "PUT", headers: authHeaders(accessToken), body: JSON.stringify(body) }
    );
    const payload = await response.json().catch(() => ({ detail: "Failed to save quota" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Failed to save quota" }, { status: 500 });
  }
}
