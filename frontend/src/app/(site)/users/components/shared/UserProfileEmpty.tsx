import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { getTranslations } from "next-intl/server";
import { CalendarSearch, Medal, Sparkles, Swords, Trophy, Users } from "lucide-react";

import { HeroFrame } from "@/components/site/PageHero";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { canonicalDisplay } from "@/lib/player";

/**
 * Shown in place of the profile tab strip when a player has never entered a
 * tournament.
 *
 * Every tab (overview, tournaments, matches, heroes, maps, achievements) is
 * derived from tournament participation, so rendering the strip would offer six
 * dead ends. One hero-framed panel states it once, names what will appear here
 * when the player does compete, and points at the two pages that are not empty.
 */

const UNLOCKS = [
  { key: "tournaments", icon: Trophy },
  { key: "matches", icon: Swords },
  { key: "heroes", icon: Sparkles },
  { key: "achievements", icon: Medal }
] as const;

/** `name` is the raw `BattleTag#1234`; the copy reads better without the tag. */
const UserProfileEmpty = async ({ name }: { name: string }) => {
  const t = await getTranslations();
  const displayName = canonicalDisplay(name).name;

  return (
    <HeroFrame variant="profile">
      <div
        // Polite: an empty career is not a failure the visitor needs announced
        // assertively — it is simply the state of this profile.
        role="status"
        className="flex flex-col items-center gap-6 px-6 py-14 text-center md:py-20"
      >
        <span
          aria-hidden
          className="flex size-16 items-center justify-center rounded-2xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
        >
          <CalendarSearch className="size-7 text-[color:var(--aqt-teal)]" />
        </span>

        <div className="space-y-2.5">
          <Eyebrow as="p" className="aqt-tnum">
            {t("users.profile.empty.eyebrow")}
          </Eyebrow>
          <h2 className="aqt-display text-2xl font-semibold tracking-tight text-[color:var(--aqt-fg)] md:text-headline">
            {t("users.profile.empty.title")}
          </h2>
          <p className="mx-auto max-w-prose text-caption leading-relaxed text-[color:var(--aqt-fg-muted)] md:text-sm">
            {t("users.profile.empty.description", { name: displayName })}
          </p>
        </div>

        <ul className="flex flex-wrap items-center justify-center gap-2">
          {UNLOCKS.map(({ key, icon: Icon }) => (
            <li
              key={key}
              className="inline-flex items-center gap-2 rounded-full border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-3 py-1.5 text-label font-medium text-[color:var(--aqt-fg-dim)]"
            >
              <Icon aria-hidden className="size-3.5 text-[color:var(--aqt-fg-faint)]" />
              {t(`users.profile.empty.unlocks.${key}` as never)}
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
          <Button asChild variant="accent">
            <HoverPrefetchLink href="/tournaments">
              <Trophy aria-hidden />
              {t("users.profile.empty.browseTournaments")}
            </HoverPrefetchLink>
          </Button>
          <Button asChild variant="outline">
            <HoverPrefetchLink href="/users">
              <Users aria-hidden />
              {t("users.profile.empty.browsePlayers")}
            </HoverPrefetchLink>
          </Button>
        </div>
      </div>
    </HeroFrame>
  );
};

export default UserProfileEmpty;
