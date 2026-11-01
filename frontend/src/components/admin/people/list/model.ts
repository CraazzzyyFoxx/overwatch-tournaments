import { canonicalDisplay } from "@/lib/player";
import type { AuthAdminUser } from "@/types/rbac.types";

/** Access searches accounts by text, so the link carries the handle without its `#tag`. */
export function accessAccountsHref(name: string): string {
  return `/admin/access/accounts?q=${encodeURIComponent(canonicalDisplay(name).name)}`;
}

/**
 * RBAC lists accounts with the players they link; the table asks the other way
 * round, once per row.
 */
export function authAccountsByPlayerId(accounts: readonly AuthAdminUser[]): Map<number, AuthAdminUser> {
  const map = new Map<number, AuthAdminUser>();
  for (const account of accounts) {
    for (const link of account.linked_players) map.set(link.player_id, account);
  }
  return map;
}
