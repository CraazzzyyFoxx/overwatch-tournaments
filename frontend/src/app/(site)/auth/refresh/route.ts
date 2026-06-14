import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { authService } from "@/services/auth.service";

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get("aqt_refresh_token")?.value;

  if (!refreshToken) {
    const response = NextResponse.json({ message: "Missing refresh token" }, { status: 401 });
    response.cookies.delete("aqt_access_token");
    response.cookies.delete("aqt_refresh_token");
    return response;
  }

  try {
    const tokens = await authService.refresh(refreshToken, getForwardedClientHeaders(request));

    const response = NextResponse.json(tokens, { status: 200 });

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
  } catch {
    const response = NextResponse.json({ message: "Failed to refresh" }, { status: 401 });
    response.cookies.delete("aqt_access_token");
    response.cookies.delete("aqt_refresh_token");
    return response;
  }
}
