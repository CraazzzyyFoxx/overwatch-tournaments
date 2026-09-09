import { type ComponentProps } from "react";
import Link from "next/link";
import Image from "next/image";
import { useTranslations } from "next-intl";
import Github from "@/components/icons/Github";
import CookieSettingsButton from "@/components/CookieSettingsButton";
import { SITE_NAME, SITE_ICON, APP_VERSION } from "@/config/site";

const FOOTER_LINK_CLASS =
  "text-sm text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// Faint token (not muted-foreground/50): the opacity hack measured 2.7:1 on
// the page background, well under the 4.5:1 text floor. --aqt-fg-faint is the
// project's own low-emphasis-but-readable role, already verified elsewhere.
const COLUMN_HEADING_CLASS =
  "mb-4 text-label font-semibold tracking-label uppercase text-[color:var(--aqt-fg-faint)]";

// The bottom meta bar's own emphasis (xs, faint), distinct from the section
// links above it — shared so the three items stay pixel-identical.
const FOOTER_META_CLASS =
  "transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/**
 * The footer renders on every page, so its links sit in the viewport of every
 * page — and Next prefetches links on viewport entry by default. Under
 * `force-dynamic` that means a full server render of the privacy policy, the
 * terms and the whole section column for every visitor who scrolls, none of
 * which anyone asked for. Production on 2026-08-15 rendered /privacy 463 times
 * in 23 minutes, 12-19 per visitor, and that traffic helped saturate the edge.
 *
 * Not the hover-armed HoverPrefetchLink used in the nav: these are destinations
 * a reader reaches maybe once, so paying a normal request on the rare click is
 * the right trade. Every route here has a loading boundary.
 */
function FooterLink(props: ComponentProps<typeof Link>) {
  return <Link prefetch={false} {...props} />;
}

export function Footer() {
  const t = useTranslations();
  const year = new Date().getFullYear();

  return (
    <footer className="py-10 text-[color:var(--aqt-fg)]">
      {/* No extra horizontal padding here: the parent (site)/layout.tsx
          wrapper already supplies px-4 md:px-6 xl:px-10, the same edge
          <main> renders against. A second px-4 on this div (the previous
          implementation) inset the footer 16px further than the page
          content above it. */}
      <div className="grid grid-cols-1 gap-x-12 gap-y-10 sm:grid-cols-[1.4fr_1fr_1fr]">
        <div className="max-w-sm">
          <FooterLink
            href="/"
            className="inline-flex items-center gap-2 rounded-lg outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <Image src={SITE_ICON} alt="" width={28} height={28} className="size-7 rounded-md" />
            <span className="font-display text-lg uppercase tracking-wide text-foreground">
              {SITE_NAME}
            </span>
          </FooterLink>
          <p className="mt-4 text-sm text-[color:var(--aqt-fg-muted)]">
            {t("common.footer.disclaimer", { siteName: SITE_NAME })}
          </p>
        </div>

        <div>
          <p className={COLUMN_HEADING_CLASS}>{t("common.footer.sectionsHeading")}</p>
          <div className="flex flex-col gap-2.5">
            <FooterLink href="/tournaments" className={FOOTER_LINK_CLASS}>
              {t("nav.items.tournaments.title")}
            </FooterLink>
            <FooterLink href="/teams" className={FOOTER_LINK_CLASS}>
              {t("nav.items.teams.title")}
            </FooterLink>
            <FooterLink href="/users" className={FOOTER_LINK_CLASS}>
              {t("nav.items.users.title")}
            </FooterLink>
            <FooterLink href="/matches" className={FOOTER_LINK_CLASS}>
              {t("nav.items.matches.title")}
            </FooterLink>
            <FooterLink href="/achievements" className={FOOTER_LINK_CLASS}>
              {t("nav.items.achievements.title")}
            </FooterLink>
          </div>
        </div>

        <div>
          <p className={COLUMN_HEADING_CLASS}>{t("common.footer.resourcesHeading")}</p>
          <div className="flex flex-col gap-2.5">
            <FooterLink href="/docs" className={FOOTER_LINK_CLASS}>
              {t("common.footer.docs")}
            </FooterLink>
            {/* Same host, any tenant: the gateway registers /api/docs
                unconditionally regardless of which workspace domain served
                the request, so a relative link needs no per-host origin. */}
            <FooterLink href="/api/docs" className={FOOTER_LINK_CLASS}>
              {t("common.footer.apiDocs")}
            </FooterLink>
            <FooterLink href="/get-workspace" className={FOOTER_LINK_CLASS}>
              {t("common.footer.getWorkspace")}
            </FooterLink>
            <FooterLink
              href="https://github.com/CraazzzyyFoxx/anak-tournaments"
              className={`${FOOTER_LINK_CLASS} inline-flex items-center gap-1.5`}
            >
              <Github width={14} height={14} />
              {t("common.sourceOnGithub")}
            </FooterLink>
          </div>
        </div>
      </div>

      <div className="mt-8 flex flex-col gap-3 text-xs text-[color:var(--aqt-fg-faint)] sm:flex-row sm:items-center sm:justify-between">
        <span className="flex flex-wrap items-center gap-2">
          {t("common.footer.copyright", { year, siteName: SITE_NAME })}
          {APP_VERSION ? (
            <FooterLink
              href={`https://github.com/CraazzzyyFoxx/anak-tournaments/releases/tag/${APP_VERSION}`}
              className={FOOTER_META_CLASS}
            >
              {APP_VERSION}
            </FooterLink>
          ) : null}
        </span>
        <div className="flex flex-wrap items-center gap-4">
          <FooterLink href="/terms" className={FOOTER_META_CLASS}>
            {t("legal.terms.title")}
          </FooterLink>
          <FooterLink href="/privacy" className={FOOTER_META_CLASS}>
            {t("legal.privacy.title")}
          </FooterLink>
          <CookieSettingsButton className={FOOTER_META_CLASS} />
        </div>
      </div>
    </footer>
  );
}
