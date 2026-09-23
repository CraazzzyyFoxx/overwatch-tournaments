/**
 * Which locale of an announcement a viewer reads.
 *
 * An announcement is the one notification row with author-written text, stored
 * one entry per locale. The viewer's locale may genuinely be absent — a
 * workspace announcement is only required to carry one — so the publisher's
 * `default_locale` is the fallback. Three surfaces render the same row (the
 * banner, the inbox and the admin table); a fallback that differed between them
 * would show the same reader two different announcements.
 */

import type { AnnouncementLocaleText } from "@/types/notification.types";

export function announcementText(
  payload: Record<string, unknown>,
  locale: string
): AnnouncementLocaleText | null {
  const locales = payload.locales as Record<string, AnnouncementLocaleText> | undefined;
  if (!locales) return null;
  const fallback = typeof payload.default_locale === "string" ? payload.default_locale : null;
  return locales[locale] ?? (fallback ? locales[fallback] : null) ?? null;
}

/**
 * The one link an announcement may carry, re-validated on the way out.
 *
 * `AnnouncementPayload._href_is_safe` already rejects anything else on the way
 * in; this is the second check on the same value, because it ends up as an
 * anchor target on a surface every visitor sees and a `javascript:` URL there
 * is stored XSS. Both readers — the floating banner and the inbox row — go
 * through here, so neither can be the one that forgets.
 */
export function announcementHref(payload: Record<string, unknown>): string | null {
  const raw = typeof payload.href === "string" ? payload.href : null;
  if (!raw) return null;
  const safe = raw.startsWith("https://") || (raw.startsWith("/") && !raw.startsWith("//"));
  return safe ? raw : null;
}
