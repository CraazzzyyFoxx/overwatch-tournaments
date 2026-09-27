"use client";

import { useEffect, useLayoutEffect } from "react";

import { type AuthProfile, useAuthProfileStore } from "@/stores/auth-profile.store";

// A layout effect in the browser, a no-op passive effect on the server (where
// `useLayoutEffect` warns). The distinction is the whole point: the zone's
// server HTML is still its loading shell, and only a layout effect commits the
// seeded profile before the browser paints that shell.
const useSeedEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Seeds the client auth store with a profile the server already fetched, so the
 * first painted frame of a zone has permissions instead of a spinner and the
 * browser never repeats `/api/v1/auth/me` on entry.
 *
 * Seeding happens in an effect, not during render, on purpose: the store is a
 * module singleton shared by every SSR request in the Node process, so writing
 * it while rendering would both hand one visitor's profile to another's render
 * and desync the hydrated DOM from the server's.
 *
 * `idle` only — anything else means the client has its own, fresher answer
 * (including `anonymous` after a sign-out), which the server's snapshot of the
 * request must never overwrite.
 */
export function AuthProfileSeed({ profile }: Readonly<{ profile: AuthProfile }>) {
  useSeedEffect(() => {
    if (useAuthProfileStore.getState().status !== "idle") {
      return;
    }
    useAuthProfileStore.setState({
      status: "authenticated",
      user: profile,
      error: undefined,
      lastFetchedAt: Date.now()
    });
  }, [profile]);

  return null;
}
