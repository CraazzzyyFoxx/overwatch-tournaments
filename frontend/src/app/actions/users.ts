"use server";

import { updateTag } from "next/cache";

/**
 * Bust the Next Data Cache for public user reads after a client mutation that
 * changes what `users/[slug]`, the users list, or search display — social
 * account visibility, primary, identities, avatar, or name.
 *
 * `getUserByName` and `getAll` are tagged `"users"`; per-user reads (profile,
 * tournaments, …) are tagged `user:<id>`. Client (react-query) mutations hit the
 * API directly, so without this the SSR pages serve stale data until the 5-min
 * `revalidate` window elapses. Uses Next 16 `updateTag` (Server-Action-only,
 * read-your-own-writes) so the very next render sees fresh data. Safe to call
 * un-awaited (`void revalidateUser()`).
 */
export async function revalidateUser(userId?: number): Promise<void> {
  updateTag("users");
  if (typeof userId === "number") {
    updateTag(`user:${userId}`);
  }
}
