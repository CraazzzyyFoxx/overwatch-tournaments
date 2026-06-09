"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, Check, ChevronsUpDown, LogOut } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem
} from "@/components/ui/sidebar";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { getAuthProfileHref } from "@/lib/auth-profile-links";
import { WorkspaceAvatar } from "@/components/WorkspaceSwitcher";
import { filterAccessibleWorkspaces, useWorkspaceStore } from "@/stores/workspace.store";
import { SITE_FAVICON, SITE_NAME } from "@/config/site";

export function getRoleLabel({
  isSuperuser,
  isAdmin,
  isOrganizer,
  isModerator
}: {
  isSuperuser: boolean;
  isAdmin: boolean;
  isOrganizer: boolean;
  isModerator: boolean;
}) {
  if (isSuperuser) return "Superuser";
  if (isAdmin) return "Admin";
  if (isOrganizer) return "Organizer";
  if (isModerator) return "Moderator";
  return "Operator";
}

export function getInitials(username?: string | null) {
  if (!username) return "AQ";
  return username.slice(0, 2).toUpperCase();
}

export function SidebarWorkspaceLogoItem({ href }: { href: string }) {
  const { user, status } = useAuthProfile();
  const { workspaces: allWorkspaces, currentWorkspaceId } = useWorkspaceStore();
  const workspaces = filterAccessibleWorkspaces(allWorkspaces, status, user);
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          asChild
          size="lg"
          className="h-9 rounded-lg px-2 hover:bg-transparent group-data-[collapsible=icon]:justify-center"
        >
          <Link href={href}>
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
  );
}

export function SidebarBackToSite() {
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          asChild
          size="sm"
          tooltip="Back to site"
          className="h-7 rounded-md px-2.5 text-[12px] text-sidebar-foreground/40 hover:text-sidebar-foreground/70 hover:bg-sidebar-accent/40"
        >
          <Link href="/">
            <ArrowLeft className="size-4 text-sidebar-foreground/30" />
            <span>Back to site</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export function SidebarUserDropdown() {
  const { user, status } = useAuthProfile();
  const { isSuperuser, isAdmin, isOrganizer, isModerator } = usePermissions();
  const {
    workspaces: allWorkspaces,
    currentWorkspaceId,
    setCurrentWorkspace
  } = useWorkspaceStore();

  const workspaces = filterAccessibleWorkspaces(allWorkspaces, status, user);
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);
  const roleLabel = getRoleLabel({ isSuperuser, isAdmin, isOrganizer, isModerator });
  const profileHref = getAuthProfileHref(user);

  return (
    <div className="mt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton
                size="lg"
                tooltip={user?.username ?? "Profile"}
                className="h-12 rounded-lg px-2 hover:bg-sidebar-accent/60 data-[state=open]:bg-sidebar-accent/60"
              >
                <Avatar className="size-8 rounded-lg ring-1 ring-sidebar-border/60">
                  <AvatarImage
                    src={user?.avatarUrl ?? undefined}
                    alt={user?.username ?? "User"}
                  />
                  <AvatarFallback className="rounded-lg bg-sidebar-accent text-[11px] font-medium text-sidebar-foreground/60">
                    {getInitials(user?.username)}
                  </AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                  <span className="truncate text-[13px] font-medium text-sidebar-foreground">
                    {user?.username ?? "User"}
                  </span>
                  <span className="truncate text-[11px] text-sidebar-foreground/40">
                    {roleLabel}
                    {currentWorkspace ? ` · ${currentWorkspace.name}` : ""}
                  </span>
                </div>
                <ChevronsUpDown className="ml-auto size-3.5 text-sidebar-foreground/25 group-data-[collapsible=icon]:hidden" />
              </SidebarMenuButton>
            </DropdownMenuTrigger>

            <DropdownMenuContent align="start" side="top" className="w-64 p-1.5">
              <div className="flex items-center gap-2.5 px-2 py-2">
                <Avatar className="size-9 rounded-lg ring-1 ring-border/60">
                  <AvatarImage src={user?.avatarUrl ?? undefined} />
                  <AvatarFallback className="rounded-lg text-xs">
                    {getInitials(user?.username)}
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col">
                  <span className="text-[13px] font-medium">{user?.username ?? "User"}</span>
                  <span className="text-[11px] text-muted-foreground">{roleLabel}</span>
                </div>
              </div>

              <DropdownMenuSeparator />

              <DropdownMenuItem asChild className="h-8 rounded-md text-[13px]">
                <Link href={profileHref}>
                  <ArrowUpRight className="size-3.5 text-muted-foreground" />
                  View Profile
                </Link>
              </DropdownMenuItem>

              {workspaces.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60 px-2 py-1">
                    Workspace
                  </DropdownMenuLabel>
                  {workspaces.map((ws) => (
                    <DropdownMenuItem
                      key={ws.id}
                      onClick={() => setCurrentWorkspace(ws.id)}
                      className="flex items-center gap-2 h-8 rounded-md text-[13px]"
                    >
                      <WorkspaceAvatar workspace={ws} size="sm" />
                      <span className="flex-1 truncate">{ws.name}</span>
                      {ws.id === currentWorkspaceId && (
                        <Check className="size-3.5 text-sidebar-primary" />
                      )}
                    </DropdownMenuItem>
                  ))}
                </>
              )}

              <DropdownMenuSeparator />

              <DropdownMenuItem className="h-8 rounded-md text-[13px] text-muted-foreground hover:text-foreground">
                <LogOut className="size-3.5" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>
    </div>
  );
}
