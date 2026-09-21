import ZONE_NAMESPACES from "./zone-namespaces.json";

/**
 * Route zones, as `docs/frontend-zones.md` defines them. The i18n concern here
 * is payload: `NextIntlClientProvider` serialises whatever `messages` it is
 * given into the RSC payload, and with no `messages` prop it serialises the
 * *whole* tree (`next-intl/dist/.../NextIntlClientProviderServer.js`:
 * `messages: undefined === v ? await getMessages() : v`). That shipped all 49
 * namespaces — the admin draft console, the quota editor, the registration form
 * builder — to every anonymous visitor.
 *
 * The bundle is chosen by the LAYOUT that renders it (`ZoneIntlProvider`), not
 * by the request path: a client-side navigation re-renders only the segments
 * below the deepest shared layout, so a root-layout provider keeps the bundle
 * of whatever page was loaded first. Going /tournaments → /draft/x that way
 * left the draft room reading the web bundle and rendering the draft console's
 * own keys raw. A zone's layout, by construction, re-renders exactly when
 * its zone is entered.
 */
export type Zone = keyof typeof ZONE_NAMESPACES;

export const ZONES = Object.keys(ZONE_NAMESPACES) as readonly Zone[];

/**
 * The zone's slice of the message tree. Sub-trees are aliased, not cloned: the
 * cost is one object with ~35 references, not a copy of 195 kB of JSON.
 */
export function pickMessages<T extends Record<string, unknown>>(all: T, zone: Zone): Partial<T> {
  const picked: Partial<T> = {};
  for (const namespace of ZONE_NAMESPACES[zone]) {
    if (namespace in all) picked[namespace as keyof T] = all[namespace as keyof T];
  }
  return picked;
}
