import { NextRequest, NextResponse } from "next/server";

import { requireAccessToken } from "@/lib/auth/cookies";
import { authServiceRequest } from "../_lib";

export async function GET(request: NextRequest) {
  // Authentication answers before the parameter check, so a signed-out caller
  // gets 401 rather than a 400 that leaks which parameters this route wants.
  const accessToken = await requireAccessToken();
  if (accessToken instanceof NextResponse) {
    return accessToken;
  }
  if (!request.nextUrl.searchParams.get("workspace_id")) {
    return NextResponse.json({ detail: "workspace_id is required" }, { status: 400 });
  }

  // Forward all query params (workspace_id + pagination/sort/search) to the gateway.
  return authServiceRequest(`/api-keys?${request.nextUrl.searchParams.toString()}`, {
    errorDetail: "Failed to load API keys"
  });
}

export async function POST(request: NextRequest) {
  // The body is forwarded verbatim (name, workspace_id, scopes, expires_at), so
  // new create fields need no change here. Authorization comes from the httpOnly
  // session cookie only — never from an inbound header, so an API key can never
  // be used to mint another API key.
  return authServiceRequest("/api-keys", {
    method: "POST",
    body: () => request.json(),
    errorDetail: "Failed to create API key"
  });
}
