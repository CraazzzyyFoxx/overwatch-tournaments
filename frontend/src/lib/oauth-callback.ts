import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import type { OAuthProviderName } from "@/types/auth.types";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

function createRedirectResponse(redirectUrl: URL, clearOAuthCookies: boolean = true): NextResponse {
  const response = NextResponse.redirect(redirectUrl);
  if (clearOAuthCookies) {
    response.cookies.delete("aqt_oauth_state");
    response.cookies.delete("aqt_post_login_redirect");
    response.cookies.delete("aqt_oauth_action");
    response.cookies.delete("aqt_oauth_provider");
  }
  return response;
}

function resolveSafeRedirect(postLoginRedirect: string): URL {
  try {
    const redirectUrl = new URL(postLoginRedirect, SITE_URL);
    const siteOrigin = new URL(SITE_URL).origin;
    if (redirectUrl.origin === siteOrigin) {
      return redirectUrl;
    }
  } catch {
    return new URL("/", SITE_URL);
  }

  return new URL("/", SITE_URL);
}

export async function handleOAuthCallback(request: Request, provider: OAuthProviderName): Promise<NextResponse> {
  const { cookies } = await import("next/headers");

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const error = url.searchParams.get("error");
  const errorDescription = url.searchParams.get("error_description");

  const cookieStore = await cookies();
  const expectedState = cookieStore.get("aqt_oauth_state")?.value;
  const oauthAction = cookieStore.get("aqt_oauth_action")?.value;
  const storedProvider = cookieStore.get("aqt_oauth_provider")?.value;
  const postLoginRedirect = cookieStore.get("aqt_post_login_redirect")?.value || "/";

  if (error) {
    const errorUrl = new URL("/", SITE_URL);
    errorUrl.searchParams.set("auth_error", error);
    if (errorDescription) {
      errorUrl.searchParams.set("auth_error_description", errorDescription);
    }
    return createRedirectResponse(errorUrl);
  }

  if (!code || !state || !expectedState || state !== expectedState || storedProvider !== provider) {
    const errorUrl = new URL("/", SITE_URL);
    errorUrl.searchParams.set("auth_error", "invalid_state");
    return createRedirectResponse(errorUrl);
  }

  try {
    const forwardedHeaders = getForwardedClientHeaders(request);

    if (oauthAction === "link") {
      const accessToken = cookieStore.get("aqt_access_token")?.value;

      if (!accessToken) {
        const loginUrl = new URL("/", SITE_URL);
        loginUrl.searchParams.set("login", "1");
        loginUrl.searchParams.set("next", "/account");
        return createRedirectResponse(loginUrl);
      }

      await authService.linkOAuth(provider, code, state, accessToken, forwardedHeaders);
      return createRedirectResponse(new URL("/account", SITE_URL));
    }

    const tokens = await authService.exchangeOAuthCode(provider, code, state, forwardedHeaders);
    const response = createRedirectResponse(resolveSafeRedirect(postLoginRedirect));

    response.cookies.set("aqt_access_token", tokens.access_token, {
      httpOnly: false,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 13 * 60
    });

    response.cookies.set("aqt_refresh_token", tokens.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 30 * 24 * 60 * 60
    });

    return response;
  } catch (err) {
    console.error("OAuth callback error:", err);
    const errorUrl = new URL("/", SITE_URL);
    errorUrl.searchParams.set("auth_error", "exchange_failed");
    return createRedirectResponse(errorUrl);
  }
}
