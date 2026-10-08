"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { type ComponentProps, type ReactNode } from "react";

import CookieSettingsButton from "@/components/CookieSettingsButton";
import Github from "@/components/icons/Github";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { APP_VERSION, BRAND_NAME, SITE_URL } from "@/config/site";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { getAuthProfileHref } from "@/lib/auth/profile-links";
import type { Workspace } from "@/types/workspace.types";

const COLUMN_HEADING_CLASS =
  "mb-3 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-faint)]";
const LINK_CLASS =
  "inline-flex min-h-8 items-center gap-1.5 text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
const META_CLASS =
  "transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
const VERSION_CLASS =
  "rounded-[5px] border border-[color:var(--aqt-border-2)] px-1.5 py-[3px] text-label font-semibold tabular-nums text-[color:var(--aqt-fg-dim)]";

// The repository the app is built from. One constant, because the source link
// and the version tag link must point at the same repo — they were written out
// twice and both carried the old `anak-tournaments` name after the rename, so
// every version chip in the footer 404'd.
const REPO_URL = "https://github.com/CraazzzyyFoxx/overwatch-tournaments";

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

/**
 * Site chrome, in two readings of the same frame: the platform's own footer,
 * and a community's on its white-label host — where the community speaks first
 * and the platform is a credit line at the bottom.
 */
export function Footer({ tenant }: Readonly<{ tenant: Workspace | null }>) {
  const t = useTranslations();
  const { user } = useAuthProfile();
  const year = new Date().getFullYear();

  const version = APP_VERSION ? (
    <FooterLink href={`${REPO_URL}/releases/tag/${APP_VERSION}`} className={VERSION_CLASS}>
      {APP_VERSION}
    </FooterLink>
  ) : null;

  const legal = (
    <nav aria-label={t("common.footer.legalLabel")} className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <FooterLink href="/terms" className={META_CLASS}>
        {t("legal.terms.title")}
      </FooterLink>
      <FooterLink href="/privacy" className={META_CLASS}>
        {t("legal.privacy.title")}
      </FooterLink>
      <CookieSettingsButton className={META_CLASS} />
    </nav>
  );

  const profileHref = getAuthProfileHref(user);

  return (
    <footer className="mt-[var(--section-gap)] border-t border-[color:var(--aqt-border)] text-[color:var(--aqt-fg)]">
      {/* No extra horizontal padding here: the parent (site)/layout.tsx
          wrapper already supplies px-4 md:px-6 xl:px-10, the same edge
          <main> renders against. */}
      <div className="grid grid-cols-1 gap-x-10 gap-y-7 pb-7 pt-10 md:grid-cols-[minmax(0,1.4fr)_1fr_1fr]">
        <div>
          <FooterLink
            href="/"
            className="inline-flex min-h-10 items-center gap-2.5 rounded-lg outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {tenant ? (
              <>
                <WorkspaceAvatar workspace={tenant} size={28} />
                <span className="font-display text-[16px] font-extrabold tracking-[0.02em]">
                  {tenant.name}
                </span>
              </>
            ) : (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/brand-mark.svg" alt="" width={28} height={28} className="rounded-[7px]" />
                <span className="font-display text-[17px] font-extrabold leading-none tracking-[0.02em]">
                  {BRAND_NAME}
                </span>
              </>
            )}
          </FooterLink>
          <p className="mt-3 max-w-[26rem] text-caption text-[color:var(--aqt-fg-dim)]">
            {tenant
              ? t("common.footer.tenantDisclaimer", { name: tenant.name, siteName: BRAND_NAME })
              : t("common.footer.disclaimer", { siteName: BRAND_NAME })}
          </p>
        </div>

        {tenant ? (
          <>
            <Column heading={t("common.footer.communityHeading")}>
              <FooterLink href="/tournaments" className={LINK_CLASS}>
                {t("nav.items.tournaments.title")}
              </FooterLink>
              <FooterLink href="/users" className={LINK_CLASS}>
                {t("nav.items.users.title")}
              </FooterLink>
              <FooterLink href="/statistics" className={LINK_CLASS}>
                {t("common.footer.statistics")}
              </FooterLink>
              {tenant.discord_url && (
                <ExternalLink href={tenant.discord_url}>{t("common.footer.discord")}</ExternalLink>
              )}
              {tenant.twitch_url && (
                <ExternalLink href={tenant.twitch_url}>{t("common.footer.twitch")}</ExternalLink>
              )}
              {tenant.boosty_url && (
                <ExternalLink href={tenant.boosty_url}>{t("common.footer.boosty")}</ExternalLink>
              )}
            </Column>
            <Column heading={t("common.footer.platformHeading", { siteName: BRAND_NAME })}>
              {/* The apex origin, not a path: this host serves one community. */}
              <ExternalLink href={SITE_URL}>{t("common.footer.allCommunities")}</ExternalLink>
              {profileHref && (
                <FooterLink href={profileHref} className={LINK_CLASS}>
                  {t("common.footer.myPlayerProfile")}
                </FooterLink>
              )}
              <FooterLink href="/docs" className={LINK_CLASS}>
                {t("common.footer.docs")}
              </FooterLink>
            </Column>
          </>
        ) : (
          <>
            <Column heading={t("common.footer.sectionsHeading")}>
              <FooterLink href="/tournaments" className={LINK_CLASS}>
                {t("nav.items.tournaments.title")}
              </FooterLink>
              <FooterLink href="/users" className={LINK_CLASS}>
                {t("nav.items.users.title")}
              </FooterLink>
              <FooterLink href="/achievements" className={LINK_CLASS}>
                {t("nav.items.achievements.title")}
              </FooterLink>
              <FooterLink href="/#directory" className={LINK_CLASS}>
                {t("common.footer.communities")}
              </FooterLink>
            </Column>
            <Column heading={t("common.footer.resourcesHeading")}>
              <FooterLink href="/docs" className={LINK_CLASS}>
                {t("common.footer.docs")}
              </FooterLink>
              {/* Same host, any tenant: the gateway registers /api/docs
                  unconditionally regardless of which workspace domain served
                  the request, so a relative link needs no per-host origin. */}
              <FooterLink href="/api/docs" className={LINK_CLASS}>
                {t("common.footer.apiDocs")}
              </FooterLink>
              <FooterLink href="/get-workspace" className={LINK_CLASS}>
                {t("common.footer.getWorkspace")}
              </FooterLink>
              <FooterLink href={REPO_URL} className={LINK_CLASS}>
                <Github width={14} height={14} />
                {t("common.sourceOnGithub")}
                <ArrowUpRight className="size-3.5" aria-hidden />
              </FooterLink>
            </Column>
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2 border-t border-[color:var(--aqt-border)] pb-7 pt-4 text-caption text-[color:var(--aqt-fg-dim)]">
        {tenant ? (
          <span className="inline-flex items-center gap-2">
            {t("common.footer.poweredBy")}
            <FooterLink
              href={SITE_URL}
              className="inline-flex items-center gap-1.5 font-semibold text-[color:var(--aqt-fg)]"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/brand-mark.svg" alt="" width={18} height={18} className="rounded-[4px]" />
              {BRAND_NAME}
            </FooterLink>
            {version}
          </span>
        ) : (
          <span className="inline-flex flex-wrap items-center gap-2">
            {t("common.footer.copyright", { year, siteName: BRAND_NAME })}
            {version}
          </span>
        )}
        {legal}
      </div>
    </footer>
  );
}

function Column({ heading, children }: Readonly<{ heading: string; children: ReactNode }>) {
  return (
    <div>
      <h3 className={COLUMN_HEADING_CLASS}>{heading}</h3>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

function ExternalLink({ href, children }: Readonly<{ href: string; children: ReactNode }>) {
  return (
    <a href={href} className={LINK_CLASS}>
      {children}
      <ArrowUpRight className="size-3.5" aria-hidden />
    </a>
  );
}
