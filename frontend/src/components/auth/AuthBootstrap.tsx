"use client";

import { useEffect, useRef } from "react";

import { isAuthRequiredPath } from "@/config/auth";
import { AUTH_UNAUTHORIZED_EVENT } from "@/lib/auth-events";
import { getAccessTokenCookie, refreshAccessToken } from "@/lib/auth-tokens";
import { isExpiredOrNearExpiry } from "@/lib/jwt";
import { useProactiveTokenRefresh } from "@/lib/use-proactive-token-refresh";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { realtimeClient } from "@/services/realtime.service";

const AUTH_PROFILE_STALE_MS = 60_000;

function redirectToLoginIfProtectedRoute() {
  if (typeof window === "undefined") {
    return;
  }

  const { pathname, search, hash } = window.location;
  if (!isAuthRequiredPath(pathname)) {
    return;
  }

  const nextPath = `${pathname}${search}${hash}`;
  const loginUrl = new URL("/", window.location.origin);
  loginUrl.searchParams.set("login", "1");
  loginUrl.searchParams.set("next", nextPath);

  window.location.assign(loginUrl.toString());
}

export default function AuthBootstrap() {
  const status = useAuthProfileStore((state) => state.status);
  const fetchMe = useAuthProfileStore((state) => state.fetchMe);
  const clear = useAuthProfileStore((state) => state.clear);
  const userId = useAuthProfileStore((state) => state.user?.id ?? null);

  useEffect(() => {
    if (status !== "idle") {
      return;
    }

    void fetchMe();
  }, [fetchMe, status]);

  useProactiveTokenRefresh(status === "authenticated", clear);

  // Reset the realtime socket when the authenticated identity settles into a
  // new value (login, logout, or account switch). The gateway freezes the
  // connection's principal at handshake, so a socket opened while anonymous
  // stays anonymous after login (workspace topics keep getting rejected) and a
  // socket opened while authenticated keeps its stream after logout until it
  // drops. Reconnecting re-handshakes with the current cookie. The first
  // settled identity is only a baseline — it must not force a reconnect.
  const realtimeIdentityRef = useRef<string | null>(null);
  useEffect(() => {
    if (status !== "authenticated" && status !== "anonymous") {
      return; // idle / loading / error: identity not settled yet
    }
    const identity = status === "authenticated" ? `user:${userId ?? ""}` : "anon";
    if (realtimeIdentityRef.current === null) {
      realtimeIdentityRef.current = identity;
      return;
    }
    if (realtimeIdentityRef.current !== identity) {
      realtimeIdentityRef.current = identity;
      realtimeClient.reset();
    }
  }, [status, userId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const revalidate = () => {
      void (async () => {
        // The proactive timer is throttled while backgrounded, so the token may
        // be expired by the time the tab is shown again. Refresh first (deduped
        // with any in-flight refresh) so the focus-triggered query refetches see
        // a fresh cookie, then revalidate the profile. Skip the proactive refresh
        // when anonymous — there's no session to refresh, so don't POST
        // /auth/refresh on every focus while logged out.
        const currentStatus = useAuthProfileStore.getState().status;
        if (currentStatus !== "anonymous") {
          const token = await getAccessTokenCookie();
          if (isExpiredOrNearExpiry(token)) {
            await refreshAccessToken();
          }
        }
        void fetchMe({ staleMs: AUTH_PROFILE_STALE_MS });
      })();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        revalidate();
      }
    };

    window.addEventListener("focus", revalidate);
    window.addEventListener("online", revalidate);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("focus", revalidate);
      window.removeEventListener("online", revalidate);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [fetchMe]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const handleUnauthorized = () => {
      clear();
      redirectToLoginIfProtectedRoute();
    };

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);

    return () => {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    };
  }, [clear]);

  return null;
}
