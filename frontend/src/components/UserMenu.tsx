"use client";

import type { ComponentPropsWithoutRef, ReactNode } from "react";
import Link from "next/link";
import { Bell, ChevronRight, LogOut, Settings } from "lucide-react";
import { useTranslations } from "next-intl";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { LanguageMenuRadioGroup } from "@/components/LanguageSwitcher";
import { getAuthProfileHref } from "@/lib/auth/profile-links";
import { logout } from "@/lib/auth/logout";
import { cn } from "@/lib/utils";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { useAuthProfileStore, type AuthProfile } from "@/stores/auth-profile.store";

export function getInitials(username?: string | null) {
  return username ? username.slice(0, 2).toUpperCase() : "AQ";
}

type AccountMenuContentProps = ComponentPropsWithoutRef<typeof DropdownMenuContent> & {
  user: AuthProfile;
  /** Surface-specific rows (the admin workspace list), placed after the account rows. */
  children?: ReactNode;
};

/**
 * The account menu body, shared by the site header and the admin sidebar.
 * Identity card first (a real link to the public profile, or the "link your
 * player" action when there is none), then settings, language, and sign-out in
 * its own group.
 */
export function AccountMenuContent({
  user,
  children,
  className,
  ...props
}: Readonly<AccountMenuContentProps>) {
  const t = useTranslations();
  const clearAuth = useAuthProfileStore((s) => s.clear);
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const profileHref = getAuthProfileHref(user);

  const handleLogout = () => {
    // Drop the cached profile first so the UI can't render a stale identity
    // while the POST is in flight; `logout` then clears the cookies server-side
    // and hard-navigates.
    clearAuth();
    void logout();
  };

  const identity = (
    <>
      <Avatar aria-hidden className="size-9 rounded-lg">
        <AvatarImage src={user.avatarUrl ?? undefined} alt="" />
        <AvatarFallback className="rounded-lg text-xs font-medium">
          {getInitials(user.username)}
        </AvatarFallback>
      </Avatar>
      <span className="grid min-w-0 flex-1 leading-tight">
        <span className="truncate font-semibold" title={user.username}>
          {user.username}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {user.primaryLinkedPlayer?.playerName ?? t("common.linkPlayer")}
        </span>
      </span>
      <ChevronRight aria-hidden className="text-muted-foreground" />
    </>
  );

  return (
    <DropdownMenuContent className={cn("w-64 liquid-glass-panel", className)} {...props}>
      {profileHref ? (
        <DropdownMenuItem asChild className="gap-3">
          <Link href={profileHref}>
            {identity}
            <span className="sr-only">{t("common.profile")}</span>
          </Link>
        </DropdownMenuItem>
      ) : (
        // No linked player means no public profile: the card becomes the way
        // to link one, opened in place instead of navigating away.
        <DropdownMenuItem className="gap-3" onSelect={() => openSettings("profile")}>
          {identity}
        </DropdownMenuItem>
      )}
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => openSettings("profile")}>
        <Settings aria-hidden />
        {t("common.accountSettings")}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => openSettings("notifications")}>
        <Bell aria-hidden />
        {t("common.notificationSettings")}
      </DropdownMenuItem>
      {children}
      <DropdownMenuSeparator />
      <LanguageMenuRadioGroup />
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={handleLogout}>
        <LogOut aria-hidden />
        {t("common.logout")}
      </DropdownMenuItem>
    </DropdownMenuContent>
  );
}

const UserMenu = ({ user }: Readonly<{ user: AuthProfile }>) => {
  const t = useTranslations();

  return (
    <DropdownMenu>
      {/* A real <button>, not `asChild` onto Avatar: Avatar.Root renders a
          <span>, so `asChild` handed the trigger's behaviour to a
          non-focusable element — the account menu was keyboard-dead and
          nameless. The name lives on the button, so it survives the avatar
          image replacing the fallback. */}
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t("common.openMenu")}
          className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <Avatar className="size-8">
            <AvatarImage src={user.avatarUrl ?? undefined} alt="" />
            <AvatarFallback className="text-xs font-medium">{getInitials(user.username)}</AvatarFallback>
          </Avatar>
        </button>
      </DropdownMenuTrigger>
      <AccountMenuContent user={user} align="end" />
    </DropdownMenu>
  );
};

export default UserMenu;
