"use client";

import { useId, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import Link from "next/link";
import { Bell, ChevronRight, LogOut, Settings } from "lucide-react";
import { useTranslations } from "next-intl";

import LanguageSwitcher, { LanguageMenuRadioGroup } from "@/components/LanguageSwitcher";
import NotificationList from "@/components/notifications/NotificationList";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useNotifications } from "@/hooks/useNotifications";
import { getAuthProfileHref } from "@/lib/auth/profile-links";
import { logout } from "@/lib/auth/logout";
import { cn, initials } from "@/lib/utils";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { useAuthProfileStore, type AuthProfile } from "@/stores/auth-profile.store";

function useSignOut() {
  const clearAuth = useAuthProfileStore((s) => s.clear);
  // Drop the cached profile first so the UI can't render a stale identity
  // while the POST is in flight; `logout` then clears the cookies server-side
  // and hard-navigates.
  return () => {
    clearAuth();
    void logout();
  };
}

/** Avatar, username and linked player: the row both account surfaces open with. */
function AccountIdentity({ user, nameId }: Readonly<{ user: AuthProfile; nameId?: string }>) {
  const t = useTranslations();

  return (
    <>
      <Avatar aria-hidden className="size-9 rounded-lg">
        <AvatarImage src={user.avatarUrl ?? undefined} alt="" />
        <AvatarFallback className="rounded-lg text-xs font-medium">
          {initials(user.username)}
        </AvatarFallback>
      </Avatar>
      <span className="grid min-w-0 flex-1 leading-tight">
        <span id={nameId} className="truncate font-semibold" title={user.username}>
          {user.username}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {user.primaryLinkedPlayer?.playerName ?? t("common.linkPlayer")}
        </span>
      </span>
    </>
  );
}

type AccountMenuContentProps = ComponentPropsWithoutRef<typeof DropdownMenuContent> & {
  user: AuthProfile;
  /** Surface-specific rows (the admin workspace list), placed after the account rows. */
  children?: ReactNode;
};

/**
 * The admin sidebar's account menu body. Identity card first (a real link to
 * the public profile, or the "link your player" action when there is none),
 * then settings, language, and sign-out in its own group. The site header uses
 * `UserMenu` instead, which pairs the account with the notification inbox.
 */
export function AccountMenuContent({
  user,
  children,
  className,
  ...props
}: Readonly<AccountMenuContentProps>) {
  const t = useTranslations();
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const signOut = useSignOut();
  const profileHref = getAuthProfileHref(user);

  const identity = (
    <>
      <AccountIdentity user={user} />
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
      <DropdownMenuItem onSelect={signOut}>
        <LogOut aria-hidden />
        {t("common.logout")}
      </DropdownMenuItem>
    </DropdownMenuContent>
  );
}

const IDENTITY_CLASS =
  "flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-accent/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring";
const STRIP_BUTTON_CLASS =
  "size-8 shrink-0 text-muted-foreground hover:bg-accent/60 hover:text-foreground";

/**
 * The signed-in header control: one black panel with the account strip on
 * top, the notification inbox below and the language switch at the foot.
 * A Popover, not a DropdownMenu: `role="menu"` cannot hold the inbox rows (a
 * link and two buttons each, tooltips, a scroll region). Radix owns dismissal
 * and focus restoration.
 */
const UserMenu = ({ user }: Readonly<{ user: AuthProfile }>) => {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const nameId = useId();
  const headingId = useId();
  const notifications = useNotifications(user.id);
  const { unreadCount } = notifications;
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const signOut = useSignOut();
  const profileHref = getAuthProfileHref(user);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/* A real <button>, not `asChild` onto Avatar: Avatar.Root renders a
          <span>, which is neither focusable nor nameable. The name lives on
          the button, so it survives the avatar image replacing the fallback. */}
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={
            unreadCount == null
              ? t("common.openMenu")
              : t("common.openMenuUnread", { count: unreadCount })
          }
          className="relative flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <Avatar className="size-8">
            <AvatarImage src={user.avatarUrl ?? undefined} alt="" />
            <AvatarFallback className="text-xs font-medium">{initials(user.username)}</AvatarFallback>
          </Avatar>
          {unreadCount != null && unreadCount > 0 && (
            <span
              aria-hidden
              className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-label font-bold tabular-nums leading-none text-destructive-foreground ring-2 ring-background"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        collisionPadding={12}
        aria-labelledby={nameId}
        animate={false}
        // Land on the panel, not its first action: focusing that button would
        // pop its tooltip on every open. Tab still reaches it first.
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          (event.currentTarget as HTMLElement).focus();
        }}
        // The strip and the language row are fixed; the inbox is the part that
        // gives up height when the viewport is short.
        className="flex max-h-[var(--radix-popover-content-available-height)] w-[380px] max-w-[calc(100vw-1.5rem)] flex-col bg-black p-0 motion-safe:data-[state=open]:animate-in motion-safe:data-[state=closed]:animate-out motion-safe:data-[state=open]:fade-in-0 motion-safe:data-[state=closed]:fade-out-0 motion-safe:duration-150 motion-safe:ease-out"
      >
        <div className="flex shrink-0 items-center gap-0.5 border-b p-2">
          <PopoverClose asChild>
            {profileHref ? (
              <Link href={profileHref} className={IDENTITY_CLASS}>
                <AccountIdentity user={user} nameId={nameId} />
                <span className="sr-only">{t("common.profile")}</span>
              </Link>
            ) : (
              // No linked player means no public profile: the card opens the
              // settings where one gets linked, instead of navigating away.
              <button type="button" className={IDENTITY_CLASS} onClick={() => openSettings("profile")}>
                <AccountIdentity user={user} nameId={nameId} />
              </button>
            )}
          </PopoverClose>
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <PopoverClose asChild>
                  <Button
                    static={false}
                    variant="ghost"
                    size="icon"
                    className={STRIP_BUTTON_CLASS}
                    onClick={() => openSettings("profile")}
                  >
                    <Settings aria-hidden />
                    <span className="sr-only">{t("common.accountSettings")}</span>
                  </Button>
                </PopoverClose>
              </TooltipTrigger>
              <TooltipContent>{t("common.accountSettings")}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  static={false}
                  variant="ghost"
                  size="icon"
                  className={STRIP_BUTTON_CLASS}
                  onClick={signOut}
                >
                  <LogOut aria-hidden />
                  <span className="sr-only">{t("common.logout")}</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("common.logout")}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <NotificationList headingId={headingId} {...notifications} />
        <div className="flex shrink-0 items-center justify-between gap-3 border-t px-4 py-2">
          <span className="text-xs text-muted-foreground">{t("common.language")}</span>
          <LanguageSwitcher />
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default UserMenu;
