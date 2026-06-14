"use client";

import { useEffect } from "react";

import { isAuthRequiredPath } from "@/config/auth";
import { AUTH_UNAUTHORIZED_EVENT } from "@/lib/auth-events";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

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

  useEffect(() => {
    if (status !== "idle") {
      return;
    }

    void fetchMe();
  }, [fetchMe, status]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const revalidate = () => {
      void fetchMe({ staleMs: AUTH_PROFILE_STALE_MS });
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
