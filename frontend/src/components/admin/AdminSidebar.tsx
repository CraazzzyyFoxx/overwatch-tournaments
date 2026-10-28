"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Search } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail
} from "@/components/ui/sidebar";
import {
  getActiveAdminNavHref,
  getVisibleAdminNavigationGroups
} from "@/components/admin/admin-navigation";
import { AdminCommandPalette, useCommandPalette } from "@/components/admin/AdminCommandPalette";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";
import {
  SidebarBackToSite,
  SidebarUserDropdown,
  SidebarWorkspaceLogoItem
} from "@/components/admin/sidebar-shared";
import { eyebrowClass } from "@/components/ui/eyebrow";

export function AdminSidebar() {
  const t = useTranslations("adminShell");
  const pathname = usePathname();
  const { canAccessAdminRoute } = usePermissions();
  const { currentWorkspaceId } = useWorkspaceStore();

  const navigationGroups = getVisibleAdminNavigationGroups((item) =>
    canAccessAdminRoute({
      permissions: item.permissions,
      workspaceId: item.workspaceAdminVisible ? null : currentWorkspaceId,
      globalOnly: item.globalOnly,
      workspaceAdminVisible: item.workspaceAdminVisible,
      superuserOnly: item.superuserOnly
    })
  );
  const { open: commandOpen, setOpen: setCommandOpen } = useCommandPalette();

  // Every group lives in the scrolling content now. The old split, which
  // pushed the "Administration" group into the footer at half opacity, was
  // what made two of its seven entries read as afterthoughts; PLATFORM is a
  // labelled group like the others (F1 ·1).
  const activeHref = getActiveAdminNavHref(
    pathname,
    navigationGroups.flatMap((group) => group.items),
  );

  return (
    <Sidebar collapsible="icon">
      {/* ── HEADER: Logo + search hint ─────────────────── */}
      <SidebarHeader className="px-3 pt-3 pb-2 group-data-[collapsible=icon]:px-1">
        <SidebarWorkspaceLogoItem href="/admin" />

        {/* Search trigger */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setCommandOpen(true)}
          aria-label={t("commandPalette.search")}
          aria-keyshortcuts="Control+K Meta+K"
          className="mt-1 w-full justify-start px-2.5 text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)] group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
        >
          <Search aria-hidden />
          <span aria-hidden className="truncate group-data-[collapsible=icon]:hidden">
            {t("commandPalette.searchPlaceholder")}
          </span>
          <kbd
            aria-hidden
            className="ml-auto shrink-0 whitespace-nowrap rounded border border-[color:var(--aqt-border-2)] px-1 py-0.5 text-label font-medium leading-none text-[color:var(--aqt-fg-dim)] group-data-[collapsible=icon]:hidden"
          >
            {t("commandPalette.ctrlK")}
          </kbd>
        </Button>
      </SidebarHeader>

      {/* ── NAVIGATION ─────────────────────────────────── */}
      <SidebarContent className="px-2 pt-1 group-data-[collapsible=icon]:px-1">
        {navigationGroups.map((group, groupIndex) => (
          <SidebarGroup key={group.title || "primary"} className="px-0 py-0">
            {/* Group divider — thin line between groups, not before first */}
            {groupIndex > 0 && <Separator className="mx-2 my-2 w-auto group-data-[collapsible=icon]:mx-1" />}

            {group.title ? (
              <div className="flex items-center gap-2 px-3 py-1.5 group-data-[collapsible=icon]:hidden">
                <span className={eyebrowClass("dim")}>{t(group.title as never)}</span>
              </div>
            ) : null}

            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const isActive = item.href === activeHref;
                  // Queue size beside the entry; nothing at zero, because a
                  // permanent `0` is noise.
                  const count = item.badge?.();
                  return (
                    <SidebarMenuItem key={item.href}>
                      {/* Current page: `isActive` (overlay fill + teal bar) and `aria-current`. */}
                      <SidebarMenuButton asChild isActive={isActive} tooltip={t(item.title as never)}>
                        <HoverPrefetchLink href={item.href} aria-current={isActive ? "page" : undefined}>
                          <item.icon aria-hidden />
                          <span className="flex-1 truncate">{t(item.title as never)}</span>
                          {count ? (
                            <span className="ml-auto shrink-0 text-label tabular-nums text-[color:var(--aqt-fg-dim)] group-data-[collapsible=icon]:hidden">
                              {count}
                            </span>
                          ) : null}
                        </HoverPrefetchLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      {/* ── FOOTER: Admin tools + user ─────────────────── */}
      <SidebarFooter className="px-2 pb-2 pt-0 group-data-[collapsible=icon]:px-1">
        <SidebarBackToSite />
        <SidebarUserDropdown />
      </SidebarFooter>

      <SidebarRail />

      <AdminCommandPalette
        groups={navigationGroups}
        open={commandOpen}
        onOpenChange={setCommandOpen}
      />
    </Sidebar>
  );
}
