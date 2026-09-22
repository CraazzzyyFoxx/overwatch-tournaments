/**
 * Which announcements this browser has closed.
 *
 * Every viewer's dismissal lands here, not only a guest's. A signed-in viewer
 * also gets a `notification_read` row (it travels to their other devices), but
 * that row alone cannot keep the banner shut: `/announcements/active` is
 * `AuthOptional`, and once the short-lived access cookie lapses the server
 * render and the client read both arrive anonymous — every global
 * announcement comes back, the dismissed one included.
 *
 * A cookie rather than `localStorage` because the layout reads it server-side
 * and drops these ids before the first paint; the client reads the same value,
 * so hydration agrees with the HTML instead of flashing the notice.
 *
 * ponytail: dismissals made while signed out are never merged into
 * `notification_read` at login, so that notice still shows on the viewer's
 * other devices. Upgrade path: post this list to `notifications_mark_read` from
 * the auth bootstrap after sign-in — the endpoint already validates each id
 * against the caller's audience.
 */
import Cookies from "js-cookie";

import type { NotificationItem } from "@/types/notification.types";

export const DISMISSED_ANNOUNCEMENTS_COOKIE = "owt-announcement-dismissed";

// Announcements expire, so an unbounded list would only accumulate ids the
// server stopped sending months ago — and a cookie rides on every request.
const KEEP_LAST = 50;
const COOKIE_TTL_DAYS = 365;

/** `"31.40"` -> `[31, 40]`; anything that is not an id is dropped, never thrown. */
export function parseDismissedAnnouncements(raw: string | undefined): number[] {
  if (!raw) return [];
  return raw
    .split(".")
    .map(Number)
    .filter((id) => Number.isSafeInteger(id) && id > 0);
}

/** Client read. On the server there is no `document`, so it answers `[]`. */
export function readDismissedAnnouncements(): number[] {
  return parseDismissedAnnouncements(Cookies.get(DISMISSED_ANNOUNCEMENTS_COOKIE));
}

export function rememberDismissedAnnouncement(id: number): void {
  const next = [...readDismissedAnnouncements().filter((known) => known !== id), id].slice(-KEEP_LAST);
  Cookies.set(DISMISSED_ANNOUNCEMENTS_COOKIE, next.join("."), {
    sameSite: "lax",
    expires: COOKIE_TTL_DAYS
  });
}

/** The layouts' half: the server's list minus what this browser closed. */
export function withoutDismissedAnnouncements(
  items: NotificationItem[] | undefined,
  cookieValue: string | undefined
): NotificationItem[] | undefined {
  const dismissed = parseDismissedAnnouncements(cookieValue);
  return items?.filter((item) => !dismissed.includes(item.id));
}
