"use client";

import Image from "next/image";
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
import { SITE_FAVICON, SITE_NAME } from "@/config/site";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { WorkspaceAvatar } from "@/components/WorkspaceSwitcher";
import { filterAccessibleWorkspaces, useWorkspaceStore } from "@/stores/workspace.store";
import { SidebarBackToSite, SidebarUserDropdown } from "@/components/sidebar/sidebar-shared";
import { cn } from "@/lib/utils";

export function AdminSidebar() {
  const pathname = usePathname();
  const { user, status } = useAuthProfile();
  const { canAccessAdminRoute } = usePermissions();

  const { workspaces: allWorkspaces, currentWorkspaceId } = useWorkspaceStore();
  const workspaces = filterAccessibleWorkspaces(allWorkspaces, status, user);
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);

  const navigationGroups = getVisibleAdminNavigationGroups((item) =>
    canAccessAdminRoute({
      permissions: item.permissions,
      workspaceId: item.workspaceAdminVisible ? null : currentWorkspaceId,
      globalOnly: item.globalOnly,
      workspaceAdminVisible: item.workspaceAdminVisible,
      superuserOnly: item.superuserOnly
    })
  );
  const adminToolsGroup = navigationGroups.find((group) => group.title === "Administration");
  const primaryGroups = navigationGroups.filter(
    (group) => group.title !== "Administration" && group.title !== "Overview"
  );
  const { open: commandOpen, setOpen: setCommandOpen } = useCommandPalette();

  const allHrefs = navigationGroups.flatMap((g) => g.items.map((i) => i.href));
  const activeHref = getActiveAdminNavHref(pathname, allHrefs);

  return (
    <Sidebar collapsible="icon" variant="inset">
      {/* ── HEADER: Logo + search hint ─────────────────── */}
      <SidebarHeader className="px-3 pt-3 pb-2 group-data-[collapsible=icon]:px-1">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              size="lg"
              className="h-9 rounded-lg px-2 hover:bg-transparent group-data-[collapsible=icon]:justify-center"
            >
              <Link href="/admin">
                {currentWorkspace?.icon_url ? (
                  <div className="flex size-7 items-center justify-center">
                    <Image
                      src={currentWorkspace.icon_url}
                      alt={currentWorkspace.name}
                      width={20}
                      height={20}
                      unoptimized
                      className="size-5 rounded-md object-contain"
                    />
                  </div>
                ) : currentWorkspace ? (
                  <WorkspaceAvatar workspace={currentWorkspace} size="md" />
                ) : (
                  <div className="flex size-7 items-center justify-center">
                    <Image
                      src={SITE_FAVICON}
                      alt={SITE_NAME}
                      width={20}
                      height={20}
                      unoptimized
                      className="size-5 object-contain"
                    />
                  </div>
                )}
                <span className="truncate text-[13px] font-semibold tracking-[-0.01em] text-sidebar-foreground group-data-[collapsible=icon]:hidden">
                  {currentWorkspace?.name ?? SITE_NAME}
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        {/* Search trigger */}
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="mt-1 flex h-8 w-full items-center gap-2 rounded-lg border border-sidebar-border/60 bg-sidebar-accent/40 px-2.5 text-[12px] text-sidebar-foreground/35 transition-colors hover:border-sidebar-border hover:text-sidebar-foreground/50 cursor-pointer group-data-[collapsible=icon]:hidden"
        >
          <Search className="size-3.5 shrink-0" />
          <span>Search...</span>
          <kbd className="ml-auto rounded border border-sidebar-border/70 bg-sidebar/80 px-1 py-0.5 text-[10px] font-medium leading-none text-sidebar-foreground/30">
            /
          </kbd>
        </button>
      </SidebarHeader>

      {/* ── NAVIGATION ─────────────────────────────────── */}
      <SidebarContent className="px-2 pt-1 group-data-[collapsible=icon]:px-1">
        {primaryGroups.map((group, groupIndex) => (
          <SidebarGroup key={group.title} className="px-0 py-0">
            {/* Group divider — thin line between groups, not before first */}
            {groupIndex > 0 && (
              <div className="mx-2 my-2 h-px bg-sidebar-border/40 group-data-[collapsible=icon]:mx-1" />
            )}

            {/* Group label — subtle, lowercase-style */}
            <div className="flex items-center gap-2 px-3 py-1.5 group-data-[collapsible=icon]:hidden">
              <span className="text-[11px] font-medium text-sidebar-foreground/30">
                {group.title}
              </span>
            </div>

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
                          "relative h-[30px] rounded-md px-2.5 text-[13px] transition-all",
                          "text-sidebar-foreground/55 hover:text-sidebar-foreground hover:bg-sidebar-accent/60",
                          isActive && [
                            "bg-sidebar-accent text-sidebar-foreground font-medium",
                            // Left accent bar
                            "before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2",
                            "before:h-4 before:w-[2px] before:rounded-full before:bg-sidebar-primary"
                          ]
                        )}
                      >
                        <Link href={item.href}>
                          <item.icon
                            className={cn(
                              "size-5",
                              isActive ? "text-sidebar-primary" : "text-sidebar-foreground/40"
                            )}
                          />
                          <span>{item.title}</span>
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
        {/* Administration links — compact, dimmer */}
        {adminToolsGroup && (
          <>
            <div className="mx-2 mb-1.5 h-px bg-sidebar-border/40" />
            <SidebarMenu>
              {adminToolsGroup.items.map((item) => {
                const isActive = item.href === activeHref;
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      asChild
                      size="sm"
                      isActive={isActive}
                      tooltip={item.title}
                      className={cn(
                        "relative h-[28px] rounded-md px-2.5 text-[12px]",
                        "text-sidebar-foreground/40 hover:text-sidebar-foreground/70 hover:bg-sidebar-accent/40",
                        isActive && [
                          "bg-sidebar-accent/60 text-sidebar-foreground/80 font-medium",
                          "before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2",
                          "before:h-3 before:w-[2px] before:rounded-full before:bg-sidebar-primary/70"
                        ]
                      )}
                    >
                      <Link href={item.href}>
                        <item.icon
                          className={cn(
                            "size-4.5",
                            isActive ? "text-sidebar-primary/70" : "text-sidebar-foreground/30"
                          )}
                        />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </>
        )}

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
