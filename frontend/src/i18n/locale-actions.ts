"use server";

import { cookies } from "next/headers";

import type { Locale } from "./resolve-locale";

/**
 * Persist the user's locale choice in the `NEXT_LOCALE` cookie. The cookie is
 * read back server-side in `request.ts` on the next request, so callers should
 * trigger a refresh (`router.refresh()`) after awaiting this action.
 */
export async function setUserLocale(locale: Locale): Promise<void> {
  const store = await cookies();
  store.set("NEXT_LOCALE", locale, {
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
    sameSite: "lax",
  });
}
