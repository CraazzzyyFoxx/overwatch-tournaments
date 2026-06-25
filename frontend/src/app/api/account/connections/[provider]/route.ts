import { authServiceBase } from "@/lib/api-routes";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import type { OAuthProviderName } from "@/types/auth.types";

const AUTH_SERVICE_URL = authServiceBase();

const ALLOWED_PROVIDERS = new Set<OAuthProviderName>(["discord", "twitch", "battlenet"]);

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ provider: string }> }
) {
  const { provider } = await context.params;

  if (!ALLOWED_PROVIDERS.has(provider as OAuthProviderName)) {
    return NextResponse.json({ detail: "Unsupported provider" }, { status: 400 });
  }

  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  try {
    const response = await fetch(`${AUTH_SERVICE_URL}/oauth/${provider}/unlink`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json"
      },
      cache: "no-store"
    });

    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }

    const payload = await response.json().catch(() => ({ detail: `Failed to unlink ${provider}` }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: `Failed to unlink ${provider}` }, { status: 500 });
  }
}
