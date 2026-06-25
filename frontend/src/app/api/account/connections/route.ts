import { authServiceBase } from "@/lib/api-routes";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const AUTH_SERVICE_URL = authServiceBase();

export async function GET() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}/oauth/connections`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json"
      },
      cache: "no-store"
    });

    const payload = await response.json().catch(() => ({ detail: "Failed to load OAuth connections" }));

    if (!response.ok) {
      return NextResponse.json(payload, { status: response.status });
    }

    return NextResponse.json(payload, { status: 200 });
  } catch {
    return NextResponse.json({ detail: "Failed to load OAuth connections" }, { status: 500 });
  }
}
