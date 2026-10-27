import { getLocale, getTranslations } from "next-intl/server";

import { MoreLink, Section, SectionHead } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { cn } from "@/lib/utils";

const TITLE_ID = "home-features-title";

type Audience = "players" | "organizers" | "everyone";

interface Feature {
  key: "profile" | "characters" | "registration" | "balancer" | "brackets" | "matches";
  audience: Audience;
  /** A real production capture; the changelog's are drawn per interface language. */
  src: (language: "ru" | "en") => string;
  width: number;
  height: number;
  href: string;
}

// Captures shared with `/get-workspace` (`public/showcase/`) and with the
// 2.0.0 release notes (`public/changelog/2.0.0/`, one per language); the
// organizer banner's tabs show the organizer ones.
export const FEATURES: readonly Feature[] = [
  {
    key: "profile",
    audience: "players",
    src: () => "/showcase/player-profile.webp",
    width: 2880,
    height: 2000,
    href: "/users"
  },
  {
    key: "characters",
    audience: "players",
    src: (language) => `/changelog/2.0.0/heroes.${language}.webp`,
    width: 2728,
    height: 1720,
    href: "/statistics"
  },
  {
    key: "registration",
    audience: "organizers",
    src: () => "/showcase/admin-registrations.webp",
    width: 2880,
    height: 2000,
    href: "/docs/organizers/registration"
  },
  {
    key: "balancer",
    audience: "organizers",
    src: (language) => `/changelog/2.0.0/mix-room.${language}.webp`,
    width: 2400,
    height: 1380,
    href: "/docs/organizers/team-formation"
  },
  {
    key: "brackets",
    audience: "organizers",
    src: () => "/showcase/bracket.webp",
    width: 2880,
    height: 2000,
    href: "/docs/organizers/brackets"
  },
  {
    key: "matches",
    audience: "everyone",
    src: () => "/showcase/match.webp",
    width: 2880,
    height: 2000,
    href: "/encounters"
  }
];

/**
 * What the platform does, one feature per row: a real screenshot beside who
 * it is for, what it does and where it lives. Rows alternate sides from
 * 1024px; on a phone the screenshot comes first. The screenshot window is the
 * organizer tour's: a 16:10 crop from the top-left that fades out at the
 * bottom, so a capture taller than the window ends softly, not on a cut.
 */
export async function PlatformFeatures() {
  const [t, locale] = await Promise.all([getTranslations("home.features"), getLocale()]);
  const language = locale === "ru" ? "ru" : "en";

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead title={t("title")} titleId={TITLE_ID} sub={t("sub")} />
      <ul className="mt-8 flex flex-col gap-[clamp(48px,6vw,88px)]">
        {FEATURES.map((feature, index) => (
          <li
            key={feature.key}
            className="grid items-center gap-x-[clamp(32px,5vw,72px)] gap-y-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]"
          >
            <div
              className={cn(
                "aspect-[16/10] overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] [mask-image:linear-gradient(to_bottom,black_78%,transparent)]",
                index % 2 === 1 && "lg:order-last"
              )}
            >
              <Image
                src={feature.src(language)}
                width={feature.width}
                height={feature.height}
                sizes="(min-width: 1280px) 720px, (min-width: 1024px) 56vw, 100vw"
                alt={t(`${feature.key}.alt` as const)}
                className="size-full object-cover object-left-top"
              />
            </div>
            <div className="min-w-0">
              <Eyebrow as="p">{t(`audience.${feature.audience}` as const)}</Eyebrow>
              <h3 className="mt-2 text-balance font-display text-[length:clamp(22px,2.2vw,28px)] font-semibold leading-[1.2] text-[color:var(--aqt-fg)]">
                {t(`${feature.key}.title` as const)}
              </h3>
              <p className="mt-3 max-w-[34rem] text-pretty text-ui leading-[1.6] text-[color:var(--aqt-fg-muted)]">
                {t(`${feature.key}.text` as const)}
              </p>
              <MoreLink href={feature.href} className="mt-4 min-h-11">
                {t(`${feature.key}.link` as const)}
              </MoreLink>
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}
