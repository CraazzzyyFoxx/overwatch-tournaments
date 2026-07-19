"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Image from "next/image";
import { LogIn, Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from "@/components/ui/accordion";
import UserSearch from "@/components/UserSearch";
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger
} from "@/components/ui/navigation-menu";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { SITE_ICON, SITE_NAME } from "@/config/site";
import UserMenu from "@/components/UserMenu";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import WorkspaceSwitcher from "@/components/WorkspaceSwitcher";
import WorkspaceBrandIcon from "@/components/WorkspaceBrandIcon";
import ActiveEvents from "@/components/ActiveEvents";
import { adminEntryPermissions } from "@/components/admin/admin-navigation";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { getCurrentPathForAuthRedirect } from "@/lib/auth-redirect";
import { getAuthProfileHref } from "@/lib/auth-profile-links";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

// Navigation is data-driven by stable keys; the visible text (group labels,
// item titles + descriptions) is resolved from the `nav.*` message namespace at
// render time — module scope has no `t()`. `href` drives active-state matching,
// `key` drives translation lookup.
type NavItem = {
  key: string;
  href: string;
  requiresAdminAccess?: boolean;
  requiresBalancerAccess?: boolean;
};

type NavGroup = {
  key: "tournaments" | "users" | "matches" | "organization";
  items: readonly NavItem[];
};

const NAV_GROUPS = [
  {
    key: "tournaments",
    items: [
      { key: "tournaments", href: "/tournaments" },
      { key: "teams", href: "/teams" },
      { key: "analytics", href: "/tournaments/analytics" }
    ]
  },
  {
    key: "users",
    items: [
      { key: "users", href: "/users" },
      { key: "compare", href: "/users/compare" },
      { key: "heroesLeaderboard", href: "/users/heroes-compare" },
      { key: "achievements", href: "/achievements" }
    ]
  },
  {
    key: "matches",
    items: [
      { key: "encounters", href: "/encounters" },
      { key: "matches", href: "/matches" }
    ]
  },
  {
    key: "organization",
    items: [
      { key: "balancer", href: "/balancer", requiresBalancerAccess: true },
      { key: "admin", href: "/admin", requiresAdminAccess: true }
    ]
  }
] as const satisfies readonly NavGroup[];

// Redesign nav-link look (flat, teal-active) — overrides the shared
// navigationMenuTriggerStyle() via twMerge conflict resolution.
const navTriggerClass =
  "h-8 rounded-lg bg-transparent px-3 text-[13px] font-medium text-[var(--aqt-fg-muted)] " +
  "hover:bg-[hsl(0_0%_100%/0.04)] hover:text-[var(--aqt-fg)] " +
  "focus:bg-[hsl(0_0%_100%/0.04)] focus:text-[var(--aqt-fg)] " +
  "data-[state=open]:bg-[hsl(0_0%_100%/0.04)] data-[state=open]:text-[var(--aqt-fg)]";

const navTriggerActiveClass =
  "bg-[hsl(172_70%_49%/0.1)] text-[var(--aqt-teal)] " +
  "hover:bg-[hsl(172_70%_49%/0.16)] hover:text-[var(--aqt-teal)] " +
  "focus:bg-[hsl(172_70%_49%/0.16)] focus:text-[var(--aqt-teal)] " +
  "data-[state=open]:bg-[hsl(172_70%_49%/0.16)] data-[state=open]:text-[var(--aqt-teal)]";

function isNavGroupActive(
  items: readonly { href: string }[],
  pathname: string
): boolean {
  return items.some((item) => {
    if (item.href === "/") return pathname === "/";
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  });
}

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
  const pathname = usePathname() ?? "";
  const openAuthModal = useAuthModalStore((state) => state.open);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { isOrganizer, isLoaded, canAccessAdminRoute } = usePermissions();
  const username = user?.username;
  const avatarUrl = user?.avatarUrl;
  const profileHref = getAuthProfileHref(user);
  const canAccessAdmin =
    isLoaded &&
    canAccessAdminRoute({
      permissions: adminEntryPermissions,
      workspaceId: currentWorkspaceId,
      workspaceAdminVisible: true,
    });
  const canAccessBalancer = canAccessAdmin || isOrganizer;
  const canAccessOrganization = isLoaded && (canAccessAdmin || canAccessBalancer);
  const handleLoginClick = () => {
    const nextPath =
      typeof window === "undefined" ? "/" : getCurrentPathForAuthRedirect(window.location);
    openAuthModal(nextPath);
  };

  const getVisibleItems = (items: readonly NavItem[]) =>
    items.filter((item) => {
      if (item.requiresAdminAccess) return canAccessAdmin;
      if (item.requiresBalancerAccess) return canAccessBalancer;
      return true;
    });

  return (
    <header className="sticky top-0 z-50 flex h-14 items-center gap-4 border-b border-border/70 px-4 backdrop-blur-xl md:px-6">
      {tenantMode ? (
        tenantWorkspace ? (
          <Link
            href="/"
            aria-label={`${tenantWorkspace.name} — home`}
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
      <NavigationMenu className="hidden md:flex">
        {NAV_GROUPS.filter(
          (group) => group.key !== "organization" || canAccessOrganization
        ).map((group) => (
          <NavigationMenuList key={group.key}>
            <NavigationMenuItem>
              <NavigationMenuTrigger
                className={cn(
                  navTriggerClass,
                  isNavGroupActive(group.items, pathname) && navTriggerActiveClass
                )}
              >
                {t(`nav.groups.${group.key}`)}
              </NavigationMenuTrigger>
              <NavigationMenuContent>
                <ul className="grid w-100 gap-3 p-4 md:w-125 md:grid-cols-2 lg:w-150 ">
                  {getVisibleItems(group.items).map((item) => (
                    <ListItem
                      key={item.key}
                      title={t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
                      href={item.href}
                    >
                      {t(`nav.items.${item.key}.desc` as Parameters<typeof t>[0])}
                    </ListItem>
                  ))}
                </ul>
              </NavigationMenuContent>
            </NavigationMenuItem>
          </NavigationMenuList>
        ))}
      </NavigationMenu>
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="outline" size="icon" className="shrink-0 md:hidden">
            <Menu className="h-5 w-5" />
            <span className="sr-only">{t("nav.toggleMenu")}</span>
          </Button>
        </SheetTrigger>
        <SheetContent side="left">
          <nav className="grid gap-2 text-lg font-medium">
            <Link href="/" className="flex items-center gap-2 text-lg font-semibold mb-4">
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
                <>
                  <Image src={SITE_ICON} alt={SITE_NAME} width={32} height={32} />
                  <span className="sr-only">{SITE_NAME}</span>
                </>
              )}
            </Link>
            <Accordion type="single" collapsible className="w-full">
              {NAV_GROUPS.filter(
                (group) => group.key !== "organization" || canAccessOrganization
              ).map((group) => (
                <AccordionItem key={group.key} value={group.key}>
                  <AccordionTrigger className="text-base hover:text-foreground">
                    {t(`nav.groups.${group.key}`)}
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="grid gap-4 pl-4">
                      {getVisibleItems(group.items).map((item) => (
                        <Link
                          key={item.key}
                          href={item.href}
                          className="text-muted-foreground hover:text-foreground text-sm"
                        >
                          {t(`nav.items.${item.key}.title` as Parameters<typeof t>[0])}
                        </Link>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
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
          <UserMenu username={username} avatarUrl={avatarUrl} profileHref={profileHref} />
        ) : (
          <div className="ml-auto flex min-w-0 items-center gap-1 sm:gap-3 md:ml-0">
            <LanguageSwitcher />
            <Button variant="outline" className="text-base" onClick={handleLoginClick}>
              <LogIn className="h-5 w-5" />
              <span className="hidden sm:inline">{t("nav.login")}</span>
            </Button>
          </div>
        )}
      </div>
    </header>
  );
};

const ListItem = React.forwardRef<React.ElementRef<"a">, React.ComponentPropsWithoutRef<"a">>(
  ({ className, title, children, ...props }, ref) => {
    return (
      <li>
        <NavigationMenuLink asChild>
          <a
            ref={ref}
            className={cn(
              "block select-none space-y-1 rounded-md p-3 leading-none no-underline outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground",
              className
            )}
            {...props}
          >
            <div className="text-sm font-medium leading-none">{title}</div>
            <p className="line-clamp-2 text-sm leading-snug text-muted-foreground">{children}</p>
          </a>
        </NavigationMenuLink>
      </li>
    );
  }
);
ListItem.displayName = "ListItem";

export default Header;
