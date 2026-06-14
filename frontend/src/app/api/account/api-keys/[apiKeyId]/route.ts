import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const AUTH_SERVICE_URL =
  process.env.NEXT_PUBLIC_AUTH_SERVICE_URL?.replace(/\/$/, "") || "http://localhost:8001";

type RouteContext = {
  params: Promise<{ apiKeyId: string }>;
};

function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;
  const { apiKeyId } = await context.params;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    const body = await request.json();
    const response = await fetch(`${AUTH_SERVICE_URL}/api-keys/${encodeURIComponent(apiKeyId)}`, {
      method: "PATCH",
      headers: authHeaders(accessToken),
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({ detail: "Failed to rename API key" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Failed to rename API key" }, { status: 500 });
  }
}

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;
  const { apiKeyId } = await context.params;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}/api-keys/${encodeURIComponent(apiKeyId)}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    });
    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    const payload = await response.json().catch(() => ({ detail: "Failed to revoke API key" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Failed to revoke API key" }, { status: 500 });
  }
}
