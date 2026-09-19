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
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { getAuthProfileHref } from "@/lib/auth-profile-links";
import { logout } from "@/lib/logout";
import { WorkspaceAvatar } from "@/components/WorkspaceSwitcher";
import { filterAccessibleWorkspaces, useWorkspaceStore } from "@/stores/workspace.store";
import { SITE_FAVICON, SITE_NAME } from "@/config/site";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

// Role names come from two RBAC scopes: global roles ("admin",
// "tournament_organizer", "moderator" — see AppRole in usePermissions) and
// workspace-scoped roles ("owner", "admin", "host", "member", "player" — see
// WORKSPACE_SYSTEM_ROLE_NAMES). A workspace admin never holds the *global*
// "admin" role, so checking only global roles left every workspace-scoped
// staff member (the common case) falling through to the "Operator"
// fallback. Check both scopes, global first.
function getRoleLabel({
  isSuperuser,
  globalRoles,
  workspaceRoles
}: {
  isSuperuser: boolean;
  globalRoles: string[];
  workspaceRoles: string[];
}) {
  if (isSuperuser) return "Superuser";
  if (globalRoles.includes("admin")) return "Admin";
  if (globalRoles.includes("tournament_organizer")) return "Organizer";
  if (globalRoles.includes("moderator")) return "Moderator";
  if (workspaceRoles.includes("owner")) return "Owner";
  if (workspaceRoles.includes("admin")) return "Admin";
  if (workspaceRoles.includes("host")) return "Host";
  if (workspaceRoles.includes("member")) return "Member";
  if (workspaceRoles.includes("player")) return "Player";
  return "Operator";
}

function getInitials(username?: string | null) {
  if (!username) return "AQ";
  return username.slice(0, 2).toUpperCase();
}

export function SidebarWorkspaceLogoItem({ href }: Readonly<{ href: string }>) {
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
          <Link href={href} aria-label={`${currentWorkspace?.name ?? SITE_NAME} admin home`}>
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
            <span className="truncate text-sm font-semibold tracking-tight text-sidebar-foreground group-data-[collapsible=icon]:hidden">
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
          tooltip="Return to site"
          className="h-7 rounded-md px-2.5 text-sm text-sidebar-foreground/40 hover:text-sidebar-foreground/70 hover:bg-sidebar-accent/40"
        >
          <Link href="/">
            <ArrowLeft aria-hidden className="size-4 text-sidebar-foreground/30" />
            <span>Return to site</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export function SidebarUserDropdown() {
  const { user, status } = useAuthProfile();
  const {
    workspaces: allWorkspaces,
    currentWorkspaceId,
    setCurrentWorkspace
  } = useWorkspaceStore();
  const clearAuthProfile = useAuthProfileStore((s) => s.clear);

  const workspaces = filterAccessibleWorkspaces(allWorkspaces, status, user);
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);
  const roleLabel = getRoleLabel({
    isSuperuser: user?.isSuperuser ?? false,
    globalRoles: user?.roles ?? [],
    workspaceRoles: user?.workspaces.flatMap((ws) => ws.roles) ?? []
  });
  const profileHref = getAuthProfileHref(user);

  // Same contract as the public UserMenu: drop the cached profile, then POST to
  // the logout route so the auth cookies are cleared server-side.
  const handleSignOut = () => {
    clearAuthProfile();
    void logout();
  };

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
                  <AvatarFallback className="rounded-lg bg-sidebar-accent text-xs font-medium text-sidebar-foreground/60">
                    {getInitials(user?.username)}
                  </AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                  <span className="truncate text-sm font-medium text-sidebar-foreground">
                    {user?.username ?? "User"}
                  </span>
                  <span className="truncate text-xs text-sidebar-foreground/40">
                    {roleLabel}
                    {currentWorkspace ? ` · ${currentWorkspace.name}` : ""}
                  </span>
                </div>
                <ChevronsUpDown
                  aria-hidden
                  className="ml-auto size-3.5 text-sidebar-foreground/25 group-data-[collapsible=icon]:hidden"
                />
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
                  <span className="text-sm font-medium">{user?.username ?? "User"}</span>
                  <span className="text-xs text-muted-foreground">{roleLabel}</span>
                </div>
              </div>

              <DropdownMenuSeparator />

              <DropdownMenuItem asChild className="h-8 rounded-md text-sm">
                <Link href={profileHref}>
                  <ArrowUpRight aria-hidden className="size-3.5 text-muted-foreground" />
                  View profile
                </Link>
              </DropdownMenuItem>

              {workspaces.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel className={cn(EYEBROW_CLASS, "px-2 py-1")}>
                    Workspace
                  </DropdownMenuLabel>
                  {workspaces.map((ws) => (
                    <DropdownMenuItem
                      key={ws.id}
                      onClick={() => setCurrentWorkspace(ws.id)}
                      aria-current={ws.id === currentWorkspaceId ? "true" : undefined}
                      className="flex items-center gap-2 h-8 rounded-md text-sm"
                    >
                      <WorkspaceAvatar workspace={ws} size="sm" />
                      <span className="flex-1 truncate">{ws.name}</span>
                      {ws.id === currentWorkspaceId && (
                        <Check aria-hidden className="size-3.5 text-sidebar-primary" />
                      )}
                    </DropdownMenuItem>
                  ))}
                </>
              )}

              <DropdownMenuSeparator />

              <DropdownMenuItem
                onClick={handleSignOut}
                className="h-8 rounded-md text-sm text-muted-foreground hover:text-foreground"
              >
                <LogOut aria-hidden className="size-3.5" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>
    </div>
  );
}
