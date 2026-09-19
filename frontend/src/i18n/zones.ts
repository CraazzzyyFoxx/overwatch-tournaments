import ZONE_NAMESPACES from "./zone-namespaces.json";

/**
 * Route zones, as `docs/frontend-zones.md` defines them. The i18n concern here
 * is payload: `NextIntlClientProvider` serialises whatever `messages` it is
 * given into the RSC payload, and with no `messages` prop it serialises the
 * *whole* tree (`next-intl/dist/.../NextIntlClientProviderServer.js`:
 * `messages: undefined === v ? await getMessages() : v`). That shipped all 47
 * namespaces — the admin draft console, the quota editor, the registration form
 * builder — to every anonymous visitor.
 */
export type Zone = keyof typeof ZONE_NAMESPACES;

export const ZONES = Object.keys(ZONE_NAMESPACES) as readonly Zone[];

/** Prefixes that identify a non-default zone. `(site)` is a route group, so web has none. */
const ZONE_PREFIXES: ReadonlyArray<readonly [string, Zone]> = [
  ["/admin", "admin"],
  ["/balancer", "tools"],
  ["/draft", "tools"],
];

/**
 * Zone for a request path. Web is the default because `app/(site)` is a route
 * group and contributes no URL segment — and because a path nothing matches
 * (`/_not-found`, an error boundary) renders root-layout chrome, whose
 * namespaces are in every bundle.
 */
export function zoneFromPathname(pathname: string): Zone {
  for (const [prefix, zone] of ZONE_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return zone;
  }
  return "web";
}

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
