import { NextResponse } from "next/server";
import { startOAuthLogin } from "@/lib/oauth-login";

export async function GET(request: Request) {
  try {
    return await startOAuthLogin(request, "discord");
  } catch (err) {
    console.error("Failed to get Discord OAuth URL:", err);
    const errorUrl = new URL("/?auth_error=oauth_init_failed", request.url);
    return NextResponse.redirect(errorUrl);
  }
}
