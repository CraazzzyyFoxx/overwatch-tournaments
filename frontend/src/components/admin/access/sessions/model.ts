import type { DateFormatter } from "@/components/kit/format-time";
import { detectBrowser, detectPlatform } from "@/lib/user-agent";
import type { AdminAuthSession, AdminSessionStatus } from "@/types/rbac.types";

export const SESSION_STATUSES: readonly AdminSessionStatus[] = ["active", "revoked", "expired"];

/** A missing time renders nothing. */
export function formatTimestamp(format: DateFormatter, value: string | null | undefined): string {
  return value ? format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" }) : "";
}

export function formatDeviceLabel(
  userAgent: string | null | undefined,
  unknownDevice: string
): string {
  if (!userAgent) return unknownDevice;

  const browser = detectBrowser(userAgent);
  const platform = detectPlatform(userAgent);

  if (browser && platform) return `${browser} · ${platform}`;
  if (browser) return browser;
  if (platform) return platform;

  return userAgent.length > 64 ? `${userAgent.slice(0, 64)}…` : userAgent;
}

/** The Accounts list searched down to the session's account, with its inspector open. */
export function accountsHref(session: AdminAuthSession): string {
  const needle = encodeURIComponent(session.email ?? session.username ?? "");
  return `/admin/access/accounts?search=${needle}&id=${session.user_id}`;
}
