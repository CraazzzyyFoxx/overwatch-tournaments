"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search } from "lucide-react";

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
import { Badge } from "@/components/ui/badge";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

/**
 * Queue counter beside a nav entry. Renders nothing at zero: a badge is a
 * "there is work here" signal, and a permanent `0` is noise.
 */
function NavBadge({ value, isActive }: Readonly<{ value?: number; isActive: boolean }>) {
  if (!value) return null;

  return (
    <Badge
      shape="pill"
      className={cn(
        "ml-auto shrink-0 border-transparent px-1.5 tabular-nums group-data-[collapsible=icon]:hidden",
        isActive
          ? "bg-sidebar-primary/20 text-sidebar-primary"
          : "bg-sidebar-accent text-sidebar-foreground/60"
      )}
    >
      {value}
    </Badge>
  );
}

export function AdminSidebar() {
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
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          aria-label="Search admin pages (Ctrl or Cmd + K)"
          aria-keyshortcuts="Control+K Meta+K"
          className="mt-1 flex h-8 w-full cursor-pointer items-center gap-2 rounded-lg border border-sidebar-border/60 bg-sidebar-accent/40 px-2.5 text-sm text-sidebar-foreground/50 transition-colors hover:border-sidebar-border hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
        >
          <Search aria-hidden className="size-3.5 shrink-0" />
          <span aria-hidden className="group-data-[collapsible=icon]:hidden">
            Search…
          </span>
          <kbd
            aria-hidden
            className="ml-auto rounded border border-sidebar-border/70 bg-sidebar/80 px-1 py-0.5 text-xs font-medium leading-none text-sidebar-foreground/40 group-data-[collapsible=icon]:hidden"
          >
            Ctrl K
          </kbd>
        </button>
      </SidebarHeader>

      {/* ── NAVIGATION ─────────────────────────────────── */}
      <SidebarContent className="px-2 pt-1 group-data-[collapsible=icon]:px-1">
        {navigationGroups.map((group, groupIndex) => (
          <SidebarGroup key={group.title || "primary"} className="px-0 py-0">
            {/* Group divider — thin line between groups, not before first */}
            {groupIndex > 0 && (
              <div className="mx-2 my-2 h-px bg-sidebar-border/40 group-data-[collapsible=icon]:mx-1" />
            )}

            {/* Group label — mono uppercase eyebrow, the design book's label
                register, tinted to the sidebar ramp rather than the page one. */}
            {group.title ? (
              <div className="flex items-center gap-2 px-3 py-1.5 group-data-[collapsible=icon]:hidden">
                <span className={cn(EYEBROW_CLASS, "font-mono text-sidebar-foreground/40")}>
                  {group.title}
                </span>
              </div>
            ) : null}

            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const isActive = item.href === activeHref;
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive}
                        tooltip={item.title}
                        className={cn(
                          "relative h-8 rounded-md px-2.5 text-sm transition-all",
                          "text-sidebar-foreground/55 hover:text-sidebar-foreground hover:bg-sidebar-accent/60",
                          isActive && [
                            "bg-sidebar-accent text-sidebar-foreground font-medium",
                            // Left accent bar
                            "before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2",
                            "before:h-4 before:w-0.5 before:rounded-full before:bg-sidebar-primary"
                          ]
                        )}
                      >
                        <Link href={item.href} aria-current={isActive ? "page" : undefined}>
                          <item.icon
                            aria-hidden
                            className={cn(
                              "size-5",
                              isActive ? "text-sidebar-primary" : "text-sidebar-foreground/40"
                            )}
                          />
                          <span className="flex-1 truncate">{item.title}</span>
                          <NavBadge value={item.badge?.()} isActive={isActive} />
                        </Link>
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
