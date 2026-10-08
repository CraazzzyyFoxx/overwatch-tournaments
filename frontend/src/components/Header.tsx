"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, LogIn, Menu, Plus, Search, X } from "lucide-react";
import { useTranslations } from "next-intl";

import ActiveEvents from "@/components/ActiveEvents";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { PlayerSearchCombobox } from "@/components/PlayerSearchCombobox";
import { NAV_GROUPS, NAV_LINKS, currentNavHref } from "@/components/site/site-nav-groups";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import UserMenu from "@/components/UserMenu";
import { WorkspaceAvatar, type WorkspaceAvatarSource } from "@/components/workspace/WorkspaceAvatar";
import WorkspaceSwitcher from "@/components/workspace/WorkspaceSwitcher";
import { BRAND_NAME } from "@/config/site";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { cn } from "@/lib/utils";
import { useAuthModalStore } from "@/stores/auth-modal.store";

/** Mock `.btn.btn--outline.btn--icon`: the plate's square 36px controls. */
const ICON_BUTTON_CLASS =
  "inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--aqt-radius-sm)] " +
  "border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] " +
  "text-[color:var(--aqt-fg-muted)] outline-none transition-colors " +
  "hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] " +
  "focus-visible:ring-2 focus-visible:ring-ring";

/** Mock `.menu-item`: one row of a popover, dropdown or the mobile sheet. */
const MENU_ITEM_CLASS =
  "flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]";

/** Mock `.pop`: the floating panel every header disclosure lands in. */
const POP_CLASS =
  "min-w-[240px] max-w-[min(360px,calc(100vw-24px))] rounded-xl border-[color:var(--aqt-border-2)] " +
  "bg-[color:var(--aqt-card-2)] p-1.5 shadow-[0_18px_50px_rgb(0_0_0/0.5)]";

const EYEBROW_CLASS =
  "px-2.5 pb-1.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-faint)]";

interface HeaderProps {
  /**
   * True on a tenant (white-label) host — injected server-side from the
   * `x-owt-host-mode` header. The whole site is locked to one community there,
   * so the cross-community switcher is replaced by that community's mark.
   */
  tenantMode?: boolean;
  /** The host community on a tenant host, resolved server-side. */
  tenantWorkspace?: WorkspaceAvatarSource;
}

const Header = ({ tenantMode, tenantWorkspace }: HeaderProps) => {
  const t = useTranslations();
  const { user } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const current = currentNavHref(usePathname() ?? "");
  // Below `md` the inline combobox has no room; the search is a toggle that
  // drops a full-width row under the plate (mock `openMobileSearch`).
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);

  const tenant = tenantMode ? tenantWorkspace : undefined;

  return (
    <header className="sticky top-0 z-50 pt-2.5">
      {/* First focusable element on every page: a keyboard user can jump the
        whole nav tree instead of tabbing through it on each navigation.
        Targets the <main id="main-content"> in (site)/layout.tsx. */}
      <a
        href="#main-content"
        className="absolute left-3 top-3 z-[80] -translate-y-[200%] rounded-lg bg-[color:var(--aqt-card-2)] px-3 py-2 text-sm font-medium text-[color:var(--aqt-fg)] ring-2 ring-ring focus:translate-y-0"
      >
        {t("common.skipToContent")}
      </a>
      <div className="relative">
        <div className="flex h-[var(--aqt-header-h)] items-center gap-3 rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border-2)] bg-[color:color-mix(in_srgb,var(--aqt-card)_86%,transparent)] pl-3 pr-2 shadow-[0_10px_30px_-18px_rgb(0_0_0/0.7)] backdrop-blur-[20px] backdrop-saturate-[1.4]">
          <Sheet>
            <SheetTrigger asChild>
              <button type="button" aria-label={t("nav.toggleMenu")} className={cn(ICON_BUTTON_CLASS, "lg:hidden")}>
                <Menu className="size-4" aria-hidden />
              </button>
            </SheetTrigger>
            {/* The sheet is a dialog: it needs a name, and Radix warns unless
              the absent description is declared absent on purpose. */}
            <SheetContent
              side="left"
              closeButton={false}
              aria-describedby={undefined}
              className="w-[min(320px,86vw)] border-r-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] p-[18px_16px_24px] sm:max-w-none"
            >
              <SheetTitle className="sr-only">{t("nav.label")}</SheetTitle>
              <div className="flex items-center justify-between gap-3">
                <SheetClose asChild>
                  <Link
                    prefetch={false}
                    href="/"
                    aria-label={
                      tenant
                        ? `${tenant.name} — ${t("common.homeLink")}`
                        : t("common.homeLink")
                    }
                    className="flex min-h-10 min-w-0 items-center gap-2.5 rounded-lg"
                  >
                    {tenant ? (
                      <>
                        <WorkspaceAvatar workspace={tenant} size={32} />
                        <span className="truncate font-display text-base font-extrabold tracking-[0.02em]">
                          {tenant.name}
                        </span>
                      </>
                    ) : (
                      <>
                        <Image src="/brand-mark.svg" alt="" width={28} height={28} className="size-7 rounded-[7px]" />
                        <span className="font-display text-[17px] font-extrabold leading-none tracking-[0.02em]">
                          {BRAND_NAME}
                        </span>
                      </>
                    )}
                  </Link>
                </SheetClose>
                <SheetClose asChild>
                  <button
                    type="button"
                    aria-label={t("nav.closeMenu")}
                    className="inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--aqt-radius-sm)] text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <X className="size-4" aria-hidden />
                  </button>
                </SheetClose>
              </div>

              {NAV_GROUPS.map((group) => (
                <div key={group.key} className="mt-[18px]">
                  <p className={EYEBROW_CLASS}>{t(`nav.groups.${group.key}`)}</p>
                  {group.items.map((item) => (
                    <SheetClose asChild key={item.key}>
                      <HoverPrefetchLink
                        href={item.href}
                        aria-current={item.href === current ? "page" : undefined}
                        className={MENU_ITEM_CLASS}
                      >
                        <item.icon className="size-4 shrink-0" aria-hidden />
                        <span className="min-w-0 flex-1 truncate">
                          {t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
                        </span>
                      </HoverPrefetchLink>
                    </SheetClose>
                  ))}
                </div>
              ))}

              <div className="mt-[18px]">
                <p className={EYEBROW_CLASS}>{t("nav.groups.play")}</p>
                {NAV_LINKS.map((item) => (
                  <SheetClose asChild key={item.key}>
                    <HoverPrefetchLink
                      href={item.href}
                      aria-current={item.href === current ? "page" : undefined}
                      className={MENU_ITEM_CLASS}
                    >
                      <item.icon className="size-4 shrink-0" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">
                        {t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
                      </span>
                    </HoverPrefetchLink>
                  </SheetClose>
                ))}
              </div>

              {tenantMode ? null : (
                <div className="mt-[18px]">
                  <p className={EYEBROW_CLASS}>{t("nav.groups.organizers")}</p>
                  <SheetClose asChild>
                    <Link href="/get-workspace" className={MENU_ITEM_CLASS}>
                      <Plus className="size-4 shrink-0" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{t("nav.createWorkspace")}</span>
                    </Link>
                  </SheetClose>
                </div>
              )}

              {/* Signed in, the language lives in the account menu instead. */}
              {user ? null : (
                <div className="mt-[18px] px-2.5">
                  <LanguageSwitcher />
                </div>
              )}
            </SheetContent>
          </Sheet>

          {tenant ? (
            // prefetch={false}: the header is on every page, so this link sits
            // in every viewport, and `/` is force-dynamic — Next's default
            // would server-render the home page for every visitor who never
            // clicks it. Measured 463 such renders in 23 minutes on 2026-08-15.
            <Link
              prefetch={false}
              href="/"
              aria-label={`${tenant.name} — ${t("common.homeLink")}`}
              className="flex min-h-10 min-w-0 shrink-0 items-center gap-2.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <WorkspaceAvatar workspace={tenant} size={30} />
              <span className="hidden max-w-48 truncate font-display text-base font-extrabold tracking-[0.02em] sm:inline">
                {tenant.name}
              </span>
            </Link>
          ) : (
            <>
              <Link
                prefetch={false}
                href="/"
                aria-label={t("common.homeLink")}
                className="hidden min-h-10 shrink-0 items-center gap-2.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex"
              >
                <Image src="/brand-mark.svg" alt="" width={28} height={28} className="size-7 rounded-[7px]" />
                {/* 1024–1279 the nav joins the row; the mark carries the brand alone. */}
                <span className="font-display text-[17px] font-extrabold leading-none tracking-[0.02em] lg:max-xl:hidden">
                  {BRAND_NAME}
                </span>
              </Link>
              <span
                aria-hidden
                className="hidden h-[22px] w-px shrink-0 bg-[color:var(--aqt-border-2)] sm:block"
              />
              <WorkspaceSwitcher />
            </>
          )}

          <nav aria-label={t("nav.label")} className="hidden min-w-0 items-center gap-0.5 lg:flex">
            {NAV_GROUPS.map((group) => {
              const isCurrent = group.items.some((item) => item.href === current);
              return (
                <DropdownMenu key={group.key}>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      data-current={isCurrent || undefined}
                      className="group inline-flex h-9 items-center gap-1 rounded-lg px-2.5 text-body font-medium text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-[color:var(--aqt-overlay-2)] data-[state=open]:text-[color:var(--aqt-fg)] data-[current]:rounded-b-none data-[current]:text-[color:var(--aqt-fg)] data-[current]:shadow-[inset_0_-2px_0_var(--aqt-teal)]"
                    >
                      {t(`nav.groups.${group.key}`)}
                      <ChevronDown
                        aria-hidden
                        className="size-3.5 text-[color:var(--aqt-fg-faint)] transition-transform group-data-[state=open]:rotate-180"
                      />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" sideOffset={8} className={POP_CLASS}>
                    {group.items.map((item) => (
                      <DropdownMenuItem key={item.key} asChild className={cn(MENU_ITEM_CLASS, "px-2.5")}>
                        <HoverPrefetchLink
                          href={item.href}
                          aria-current={item.href === current ? "page" : undefined}
                        >
                          <item.icon className="size-4 shrink-0" aria-hidden />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate">
                              {t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
                            </span>
                            <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">
                              {t(`nav.items.${item.key}.desc` as Parameters<typeof t>[0])}
                            </span>
                          </span>
                        </HoverPrefetchLink>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              );
            })}
            {NAV_LINKS.map((item) => (
              <HoverPrefetchLink
                key={item.key}
                href={item.href}
                data-current={item.href === current || undefined}
                aria-current={item.href === current ? "page" : undefined}
                className="inline-flex h-9 items-center rounded-lg px-2.5 text-body font-medium text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-ring data-[current]:rounded-b-none data-[current]:text-[color:var(--aqt-fg)] data-[current]:shadow-[inset_0_-2px_0_var(--aqt-teal)]"
              >
                {t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
              </HoverPrefetchLink>
            ))}
          </nav>

          {/* Actions never shrink; the switcher label is what gives way. */}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <ActiveEvents />
            <PlayerSearchCombobox
              placeholder={t("nav.search.placeholder")}
              className="hidden w-[clamp(160px,16vw,280px)] md:block"
            />
            <button
              type="button"
              aria-label={t("nav.search.mobileTrigger")}
              aria-expanded={mobileSearchOpen}
              onClick={() => setMobileSearchOpen((open) => !open)}
              className={cn(ICON_BUTTON_CLASS, "md:hidden")}
            >
              <Search className="size-4" aria-hidden />
            </button>
            {user ? (
              <>
                <NotificationBell />
                <UserMenu user={user} />
              </>
            ) : (
              <>
                <LanguageSwitcher className="hidden lg:inline-flex" />
                <button
                  type="button"
                  aria-label={t("nav.login")}
                  onClick={() =>
                    openAuthModal(
                      typeof window === "undefined"
                        ? "/"
                        : getCurrentPathForAuthRedirect(window.location)
                    )
                  }
                  className="inline-flex h-9 min-w-9 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2.5 text-body font-semibold text-[color:var(--aqt-fg)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <LogIn className="size-4 sm:hidden" aria-hidden />
                  <span className="hidden sm:inline">{t("nav.login")}</span>
                </button>
              </>
            )}
          </div>
        </div>
        {mobileSearchOpen ? (
          <div className="mt-2 md:hidden">
            <PlayerSearchCombobox autoFocus placeholder={t("nav.search.placeholder")} />
          </div>
        ) : null}
      </div>
    </header>
  );
};

export default Header;
