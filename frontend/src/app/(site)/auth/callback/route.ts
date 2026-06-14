import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { handleOAuthCallback } from "@/lib/oauth-callback";
import type { OAuthProviderName } from "@/types/auth.types";

const ALLOWED_PROVIDERS = new Set<OAuthProviderName>(["discord", "twitch", "battlenet"]);
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export async function GET(request: Request) {
  const cookieStore = await cookies();
  const provider = cookieStore.get("aqt_oauth_provider")?.value;

  if (!provider || !ALLOWED_PROVIDERS.has(provider as OAuthProviderName)) {
    const errorUrl = new URL("/", SITE_URL);
    errorUrl.searchParams.set("auth_error", "invalid_provider");
    const response = NextResponse.redirect(errorUrl);
    response.cookies.delete("aqt_oauth_provider");
    response.cookies.delete("aqt_oauth_state");
    response.cookies.delete("aqt_post_login_redirect");
    response.cookies.delete("aqt_oauth_action");
    return response;
  }

  return handleOAuthCallback(request, provider as OAuthProviderName);
}
