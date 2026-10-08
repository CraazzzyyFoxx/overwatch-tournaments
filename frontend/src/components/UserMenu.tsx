"use client";

import { useId, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import Link from "next/link";
import { Bell, ChevronRight, LayoutDashboard, LogOut, Settings, User } from "lucide-react";
import { useTranslations } from "next-intl";

import LanguageSwitcher, { LanguageMenuRadioGroup } from "@/components/LanguageSwitcher";
import { useCanAccessAdminEntry } from "@/components/site/useCanAccessAdminEntry";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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

const MENU_ITEM_CLASS =
  "flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]";

/**
 * The signed-in header control: a round avatar button opening the account
 * menu — identity, profile, the admin entry for those who have one, settings,
 * language and sign-out. The notification inbox is the bell's, not this menu's.
 *
 * A Popover, not a DropdownMenu: `role="menu"` cannot hold the segmented
 * language control (a plain button inside a menu is unreachable). Radix owns
 * dismissal and focus restoration.
 */
const UserMenu = ({ user }: Readonly<{ user: AuthProfile }>) => {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const nameId = useId();
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const signOut = useSignOut();
  const canAccessAdmin = useCanAccessAdminEntry();
  const profileHref = getAuthProfileHref(user);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/* A real <button>, not `asChild` onto Avatar: Avatar.Root renders a
          <span>, which is neither focusable nor nameable. The name lives on
          the button, so it survives the avatar image replacing the fallback. */}
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("common.openMenu")}
          className="relative flex size-9 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-full border-2 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] text-xs font-bold text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:border-[color:var(--aqt-border-3)] focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:border-[color:var(--aqt-border-3)]"
        >
          <Avatar className="size-full rounded-full">
            <AvatarImage src={user.avatarUrl ?? undefined} alt="" />
            <AvatarFallback className="bg-transparent text-xs font-bold">
              {initials(user.username)}
            </AvatarFallback>
          </Avatar>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        collisionPadding={12}
        aria-labelledby={nameId}
        className="w-[340px] max-w-[calc(100vw-24px)] rounded-xl border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] p-1.5 shadow-[0_18px_50px_rgb(0_0_0/0.5)]"
      >
        <div className="flex items-center gap-3 px-2.5 pb-3 pt-2">
          <Avatar aria-hidden className="size-9 rounded-full border-2 border-[color:var(--aqt-border-2)]">
            <AvatarImage src={user.avatarUrl ?? undefined} alt="" />
            <AvatarFallback className="bg-[color:var(--aqt-card-2)] text-xs font-bold text-[color:var(--aqt-fg-muted)]">
              {initials(user.username)}
            </AvatarFallback>
          </Avatar>
          <span className="min-w-0">
            <span id={nameId} className="block truncate font-semibold" title={user.username}>
              {user.username}
            </span>
            <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">
              {profileHref ? (
                <>
                  {t("nav.account.playerLabel")}{" "}
                  <PopoverClose asChild>
                    <Link href={profileHref} className="text-[color:var(--aqt-teal)]">
                      {user.primaryLinkedPlayer?.playerName}
                    </Link>
                  </PopoverClose>
                </>
              ) : (
                <button
                  type="button"
                  className="text-[color:var(--aqt-teal)] outline-none focus-visible:underline"
                  onClick={() => {
                    setOpen(false);
                    openSettings("profile");
                  }}
                >
                  {t("common.linkPlayer")}
                </button>
              )}
            </span>
          </span>
        </div>
        <div className="my-1.5 h-px bg-[color:var(--aqt-border)]" />
        {profileHref ? (
          <PopoverClose asChild>
            <Link href={profileHref} className={MENU_ITEM_CLASS}>
              <User className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{t("nav.account.myProfile")}</span>
            </Link>
          </PopoverClose>
        ) : null}
        {canAccessAdmin ? (
          <PopoverClose asChild>
            <Link href="/admin" className={MENU_ITEM_CLASS}>
              <LayoutDashboard className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{t("nav.items.admin.title")}</span>
            </Link>
          </PopoverClose>
        ) : null}
        <button
          type="button"
          className={MENU_ITEM_CLASS}
          onClick={() => {
            setOpen(false);
            openSettings("profile");
          }}
        >
          <Settings className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{t("common.accountSettings")}</span>
        </button>
        <div className="my-1.5 h-px bg-[color:var(--aqt-border)]" />
        <div className="flex items-center justify-between gap-3 px-2.5 py-1.5">
          <span className="text-[color:var(--aqt-fg-dim)]">{t("common.language")}</span>
          <LanguageSwitcher />
        </div>
        <div className="my-1.5 h-px bg-[color:var(--aqt-border)]" />
        <button
          type="button"
          className={cn(MENU_ITEM_CLASS, "text-[color:var(--aqt-fg-muted)]")}
          onClick={signOut}
        >
          <LogOut className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{t("common.logout")}</span>
        </button>
      </PopoverContent>
    </Popover>
  );
};

export default UserMenu;
