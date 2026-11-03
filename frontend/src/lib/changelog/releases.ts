/**
 * The product changelog: one entry per minor or major release that changed
 * something a player or an organizer can see, newest first. A patch release
 * gets no entry, so no page section and no card; the footer's version chip
 * then opens the newest entry at or below the running version.
 *
 * An entry is two things at once: a section of `/changelog`, whose text is
 * `src/app/(site)/changelog/_content/<locale>/<version>.mdx`, and for
 * RELEASE_CARD_DAYS from its `date` the release card of the floating stack.
 */
import Cookies from "js-cookie";

export interface Release {
  /** `major.minor.patch` without the `v`; `/changelog#v<version>` is the entry's anchor. */
  version: string;
  /** Release day, `YYYY-MM-DD` (UTC). The page prints it; the card runs RELEASE_CARD_DAYS from it. */
  date: string;
  /** The entry's headline, on the page and on the card. */
  title: { ru: string; en: string };
  /** Games whose marks fill the card's tile, by discipline code. Without it the tile is a sparkle. */
  games?: readonly string[];
}

export const RELEASES: readonly Release[] = [
  {
    version: "2.8.0",
    date: "2026-11-03",
    title: {
      ru: "Личная швейцарка и голосовые каналы турниров",
      en: "Individual Swiss and tournament voice channels"
    }
  },
  {
    version: "2.7.0",
    date: "2026-11-02",
    title: {
      ru: "Статистика в миксах, матчи Deadlock и имена игроков по игре",
      en: "Mix statistics, Deadlock matches and names per game"
    },
    games: ["overwatch", "deadlock"]
  },
  {
    version: "2.6.0",
    date: "2026-11-01",
    title: {
      ru: "Новые страницы турниров, новый MVP и главная страница",
      en: "New tournament pages, a new MVP and a new home page"
    }
  },
  {
    version: "2.0.0",
    date: "2026-10-23",
    title: {
      ru: "Четыре игры, драфт в миксах и новая статистика",
      en: "Four games, captain drafts in mixes and new statistics"
    },
    games: ["overwatch", "valorant", "lol", "deadlock"]
  }
];

export const RELEASE_CARD_DAYS = 14;
const DAY_MS = 86_400_000;

/** The newest version this browser has opened, closed or read the card of. One value: a newer release outranks it. */
export const RELEASE_SEEN_COOKIE = "owt-release-seen";

export function rememberReleaseSeen(version: string): void {
  Cookies.set(RELEASE_SEEN_COOKIE, version, { sameSite: "lax", expires: 365 });
}

/** `"v2.1.3"` or `"2.1.3"` -> `[2, 1, 3]`; anything else (a `dev` build) -> `null`. */
function parseVersion(value: string): [number, number, number] | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(value);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

function atOrBelow(version: string, ceiling: readonly [number, number, number]): boolean {
  const parsed = parseVersion(version);
  if (!parsed) return false;
  for (let part = 0; part < 3; part += 1) {
    if (parsed[part] !== ceiling[part]) return parsed[part] < ceiling[part];
  }
  return true;
}

/** The entry the footer's version chip opens: the newest one at or below the running version. */
export function releaseForVersion(appVersion: string | undefined): Release | null {
  const ceiling = appVersion ? parseVersion(appVersion) : null;
  if (!ceiling) return null;
  return RELEASES.find((release) => atOrBelow(release.version, ceiling)) ?? null;
}

/**
 * The release the floating card announces: the newest entry, still within
 * RELEASE_CARD_DAYS of its date, unless this browser has seen it. The clock is
 * read here, not by the caller: `Date.now()` in a component body is an impure
 * render (`react-hooks/purity`), the same split as `isLiveInvite`.
 */
export function releaseForCard(seenVersion: string | undefined, now: number = Date.now()): Release | null {
  const latest = RELEASES[0];
  if (!latest || latest.version === seenVersion) return null;
  return now < Date.parse(latest.date) + RELEASE_CARD_DAYS * DAY_MS ? latest : null;
}
