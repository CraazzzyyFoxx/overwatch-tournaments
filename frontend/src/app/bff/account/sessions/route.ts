import { authServiceBase } from "@/lib/api-routes";
import { NextResponse } from "next/server";
import { requireAccessToken } from "@/lib/auth-cookies";

const AUTH_SERVICE_URL = authServiceBase();

export async function GET() {
  const accessToken = await requireAccessToken();
  if (accessToken instanceof NextResponse) {
    return accessToken;
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}/sessions`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    const payload = await response.json().catch(() => ({ detail: "Failed to load sessions" }));
    if (!response.ok) {
      return NextResponse.json(payload, { status: response.status });
    }

    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ detail: "Failed to load sessions" }, { status: 500 });
  }
}
