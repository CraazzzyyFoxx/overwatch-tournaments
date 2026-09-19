import { authServiceBase } from "@/lib/api-routes";
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getAccessToken } from "@/lib/auth-cookies";

const AUTH_SERVICE_URL = authServiceBase();

function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  if (!workspaceId) {
    return NextResponse.json({ detail: "workspace_id is required" }, { status: 400 });
  }

  try {
    // Forward all query params (workspace_id + pagination/sort/search) to the gateway.
    const query = request.nextUrl.searchParams.toString();
    const response = await fetch(`${AUTH_SERVICE_URL}/api-keys?${query}`, {
      method: "GET",
      headers: authHeaders(accessToken),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({ detail: "Failed to load API keys" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Failed to load API keys" }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    // The body is forwarded verbatim (name, workspace_id, scopes, expires_at), so
    // new create fields need no change here. Authorization comes from the httpOnly
    // session cookie only — never from an inbound header, so an API key can never
    // be used to mint another API key.
    const body = await request.json();
    const response = await fetch(`${AUTH_SERVICE_URL}/api-keys`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({ detail: "Failed to create API key" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Failed to create API key" }, { status: 500 });
  }
}
