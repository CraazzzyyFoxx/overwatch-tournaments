import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const AUTH_SERVICE_URL =
  process.env.NEXT_PUBLIC_AUTH_SERVICE_URL?.replace(/\/$/, "") || "http://localhost:8001";

function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  if (!workspaceId) {
    return NextResponse.json({ detail: "workspace_id is required" }, { status: 400 });
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}/api-keys?workspace_id=${encodeURIComponent(workspaceId)}`, {
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
  const accessToken = cookieStore.get("aqt_access_token")?.value;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
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
