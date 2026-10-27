"use client";

import { useId } from "react";
import Image from "@/components/ui/image";
import { useTranslations } from "next-intl";
import { ArrowLeft, Bell, Check, ChevronsUpDown } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Popover, PopoverClose, PopoverTrigger } from "@/components/ui/popover";
import { RowButton } from "@/components/ui/row-button";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem
} from "@/components/ui/sidebar";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useQueryParams } from "@/hooks/useQueryParams";
import {
  ACCOUNT_MENU_ITEM_CLASS,
  AccountMenuPanel,
  AccountMenuSeparator
} from "@/components/UserMenu";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { filterAccessibleWorkspaces, useWorkspaceStore } from "@/stores/workspace.store";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { SITE_FAVICON, SITE_NAME } from "@/config/site";
import { DISCIPLINE_PARAM } from "@/lib/site/discipline-scope";
import { initials } from "@/lib/utils";
import type { WorkspaceListItem } from "@/types/workspace.types";

// Role names come from two RBAC scopes: global roles ("admin", "moderator" —
// see AppRole in usePermissions) and
// workspace-scoped roles ("owner", "admin", "referee", "host", "player" —
// see WORKSPACE_SYSTEM_ROLE_NAMES). A workspace admin never holds
// the *global* "admin" role, so checking only global roles left every
// workspace-scoped staff member (the common case) falling through to the
// "Operator" fallback. Check both scopes, global first.
function getRoleLabel({
  isSuperuser,
  globalRoles,
  workspaceRoles
}: {
  isSuperuser: boolean;
  globalRoles: string[];
  workspaceRoles: string[];
}) {
  if (isSuperuser) return "superuser";
  if (globalRoles.includes("admin") || workspaceRoles.includes("admin")) return "admin";
  if (globalRoles.includes("moderator")) return "moderator";
  if (workspaceRoles.includes("owner")) return "owner";
  if (workspaceRoles.includes("referee")) return "referee";
  if (workspaceRoles.includes("host")) return "host";
  if (workspaceRoles.includes("player")) return "player";
  return "operator";
}

export function SidebarWorkspaceLogoItem({ href }: Readonly<{ href: string }>) {
  const t = useTranslations("adminShell.dashboardExtra");
  const { user, status } = useAuthProfile();
  const { workspaces: allWorkspaces, currentWorkspaceId } = useWorkspaceStore();
  const workspaces = filterAccessibleWorkspaces(allWorkspaces, status, user);
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton asChild size="lg">
          <HoverPrefetchLink href={href} aria-label={t("workspaceAdminHome", { workspace: currentWorkspace?.name ?? SITE_NAME })}>
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
              <WorkspaceAvatar workspace={currentWorkspace} size={28} />
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
            <span className="truncate text-sm font-semibold text-sidebar-foreground group-data-[collapsible=icon]:hidden">
              {currentWorkspace?.name ?? SITE_NAME}
            </span>
          </HoverPrefetchLink>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export function SidebarBackToSite() {
  const t = useTranslations("adminShell.sidebar");
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton asChild size="sm" tooltip={t("returnToSite")}>
          <HoverPrefetchLink href="/">
            <ArrowLeft aria-hidden />
            <span>{t("returnToSite")}</span>
          </HoverPrefetchLink>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export function SidebarUserDropdown() {
  const t = useTranslations("adminShell.sidebar");
  const tCommon = useTranslations("common");
  const tDashboard = useTranslations("adminShell.dashboardExtra");
  const workspaceLabelId = useId();
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const { user, status } = useAuthProfile();
  const {
    workspaces: allWorkspaces,
    currentWorkspaceId,
    setCurrentWorkspace
  } = useWorkspaceStore();
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });

  const workspaces = filterAccessibleWorkspaces(allWorkspaces, status, user);
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);
  const pickWorkspace = (next: WorkspaceListItem) => {
    setCurrentWorkspace(next.id);
    // A game filter the new community does not run would narrow its list to nothing.
    const game = searchParams?.get(DISCIPLINE_PARAM);
    if (game && !next.disciplines_enabled.includes(game)) setParams({ [DISCIPLINE_PARAM]: null });
  };
  const roleLabel = t(`roles.${getRoleLabel({
    isSuperuser: user?.isSuperuser ?? false,
    globalRoles: user?.roles ?? [],
    workspaceRoles: user?.workspaces.flatMap((ws) => ws.roles) ?? []
  })}` as never);

  return (
    <div className="mt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <Popover>
            <PopoverTrigger asChild>
              <SidebarMenuButton size="lg" tooltip={user?.username ?? tDashboard("profile")}>
                <Avatar className="size-8 rounded-lg ring-1 ring-sidebar-border/60">
                  <AvatarImage
                    src={user?.avatarUrl ?? undefined}
                    alt={user?.username ?? tDashboard("user")}
                  />
                  <AvatarFallback className="rounded-lg">
                    {initials(user?.username)}
                  </AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                  <span className="truncate text-sm font-medium text-sidebar-foreground">
                    {user?.username ?? tDashboard("user")}
                  </span>
                  <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
                    {roleLabel}
                    {currentWorkspace ? ` · ${currentWorkspace.name}` : ""}
                  </span>
                </div>
                <ChevronsUpDown
                  aria-hidden
                  className="ml-auto text-[color:var(--aqt-fg-dim)] group-data-[collapsible=icon]:hidden"
                />
              </SidebarMenuButton>
            </PopoverTrigger>

            {user && (
              <AccountMenuPanel
                user={user}
                align="start"
                side="top"
                actions={
                  // The admin shell has no notification bell, so its settings live here.
                  <PopoverClose asChild>
                    <RowButton
                      className={ACCOUNT_MENU_ITEM_CLASS}
                      onClick={() => openSettings("notifications")}
                    >
                      <Bell className="size-4 shrink-0" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{tCommon("notificationSettings")}</span>
                    </RowButton>
                  </PopoverClose>
                }
              >
                {workspaces.length > 0 && (
                  <>
                    <AccountMenuSeparator />
                    <div role="group" aria-labelledby={workspaceLabelId}>
                      <p
                        id={workspaceLabelId}
                        className="px-2.5 pb-1 pt-1.5 text-caption text-[color:var(--aqt-fg-dim)]"
                      >
                        {t("workspace")}
                      </p>
                      {workspaces.map((ws) => (
                        <PopoverClose key={ws.id} asChild>
                          <RowButton
                            onClick={() => pickWorkspace(ws)}
                            aria-current={ws.id === currentWorkspaceId ? "true" : undefined}
                            className={ACCOUNT_MENU_ITEM_CLASS}
                          >
                            <WorkspaceAvatar workspace={ws} size={20} />
                            <span className="min-w-0 flex-1 truncate">{ws.name}</span>
                            {ws.id === currentWorkspaceId && (
                              <Check aria-hidden className="size-4 shrink-0 text-[color:var(--aqt-teal)]" />
                            )}
                          </RowButton>
                        </PopoverClose>
                      ))}
                    </div>
                  </>
                )}
              </AccountMenuPanel>
            )}
          </Popover>
        </SidebarMenuItem>
      </SidebarMenu>
    </div>
  );
}
