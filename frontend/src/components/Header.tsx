"use client";

import Link from "next/link";
import Image from "next/image";
import { LogIn, Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import UserSearch from "@/components/UserSearch";
import MobilePlayerSearchSheet from "@/components/MobilePlayerSearchSheet";
import { useTranslations } from "next-intl";
import { SITE_ICON } from "@/config/site";
import UserMenu from "@/components/UserMenu";
import NotificationBell from "@/components/notifications/NotificationBell";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import WorkspaceSwitcher from "@/components/WorkspaceSwitcher";
import WorkspaceBrandIcon from "@/components/WorkspaceBrandIcon";
import ActiveEvents from "@/components/ActiveEvents";
import SiteNav from "@/components/site/SiteNav";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { getAuthProfileHref } from "@/lib/auth/profile-links";
import { useAuthModalStore } from "@/stores/auth-modal.store";

interface HeaderProps {
  /**
   * True on a tenant (white-label) host — injected server-side from the
   * `x-owt-host-mode` header (Task 6). The whole site is locked to one
   * workspace there, so cross-workspace UI (the workspace switcher) is
   * hidden. Absent/false on the apex/platform host.
   */
  tenantMode?: boolean;
  /**
   * The host workspace (name + icon) on a tenant host, resolved server-side.
   * Rendered as a branded logo linking home in place of the switcher.
   */
  tenantWorkspace?: { name: string; iconUrl: string | null };
}

const Header = ({ tenantMode, tenantWorkspace }: HeaderProps) => {
  const t = useTranslations();
  const { user } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const username = user?.username;
  const avatarUrl = user?.avatarUrl;
  const profileHref = getAuthProfileHref(user);

  const handleLoginClick = () => {
    const nextPath =
      typeof window === "undefined" ? "/" : getCurrentPathForAuthRedirect(window.location);
    openAuthModal(nextPath);
  };

  return (
    <header className="sticky top-0 z-50 flex h-14 items-center gap-4 border-b border-border/70 px-4 backdrop-blur-xl md:px-6">
      {/* First focusable element on every page: a keyboard user can jump the
          whole nav tree instead of tabbing through it on each navigation.
          Targets the <main id="main-content"> in (site)/layout.tsx. */}
      <a
        href="#main-content"
        className="sr-only rounded-md bg-card px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg)] ring-2 ring-ring focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50"
      >
        {t("common.skipToContent")}
      </a>
      {tenantMode ? (
        tenantWorkspace ? (
          // prefetch={false} on both logo links: the header is on every page, so
          // these sit in the viewport of every page, and `/` is force-dynamic —
          // Next's default would server-render the home page for every visitor
          // who never clicks the logo. Measured 463 such renders in 23 minutes
          // on 2026-08-15.
          <Link
            prefetch={false}
            href="/"
            aria-label={`${tenantWorkspace.name} — ${t("common.homeLink")}`}
            className="flex items-center gap-2 rounded-lg outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <WorkspaceBrandIcon
              name={tenantWorkspace.name}
              iconUrl={tenantWorkspace.iconUrl}
              className="size-7 rounded-md text-xs"
            />
            <span className="hidden max-w-48 truncate text-sm font-semibold sm:inline">
              {tenantWorkspace.name}
            </span>
          </Link>
        ) : null
      ) : (
        <WorkspaceSwitcher />
      )}
      <SiteNav variant="desktop" />
      <MobilePlayerSearchSheet />
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="outline" size="icon" className="shrink-0 md:hidden">
            <Menu className="h-5 w-5" aria-hidden />
            <span className="sr-only">{t("nav.toggleMenu")}</span>
          </Button>
        </SheetTrigger>
        {/* The sheet is a dialog: it needs a name, and Radix warns unless the
            absent description is declared absent on purpose. */}
        <SheetContent side="left" aria-describedby={undefined}>
          <SheetTitle className="sr-only">{t("nav.mobileMenuTitle")}</SheetTitle>
          <nav className="grid gap-2 text-lg font-medium">
            <Link
              prefetch={false}
              href="/"
              aria-label={t("common.homeLink")}
              className="mb-4 flex items-center gap-2 text-lg font-semibold"
            >
              {tenantMode && tenantWorkspace ? (
                <>
                  <WorkspaceBrandIcon
                    name={tenantWorkspace.name}
                    iconUrl={tenantWorkspace.iconUrl}
                    className="size-8 rounded-md text-sm"
                  />
                  <span className="max-w-48 truncate text-base font-semibold">
                    {tenantWorkspace.name}
                  </span>
                </>
              ) : (
                <Image src={SITE_ICON} alt="" width={32} height={32} aria-hidden />
              )}
            </Link>
            <SiteNav variant="mobile" />
          </nav>
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 items-center gap-1 md:ml-auto md:gap-4">
        <div className="hidden min-[360px]:block">
          <ActiveEvents />
        </div>
        <div className="hidden min-w-0 md:ml-auto md:block md:flex-initial">
          <UserSearch />
        </div>
        {username ? (
          <>
            <NotificationBell />
            <UserMenu username={username} avatarUrl={avatarUrl} profileHref={profileHref} />
          </>
        ) : (
          <div className="ml-auto flex min-w-0 items-center gap-1 sm:gap-3 md:ml-0">
            <LanguageSwitcher />
            <Button
              variant="outline"
              className="text-base"
              onClick={handleLoginClick}
              aria-label={t("common.signIn")}
            >
              <LogIn className="h-5 w-5" aria-hidden />
              <span className="hidden sm:inline">{t("nav.login")}</span>
            </Button>
          </div>
        )}
      </div>
    </header>
  );
};

export default Header;
