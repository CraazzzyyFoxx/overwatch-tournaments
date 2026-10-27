"use client";

import { useId, type ComponentPropsWithoutRef, type ReactNode } from "react";
import Link from "next/link";
import { LayoutDashboard, LogOut, Settings, User } from "lucide-react";
import { useTranslations } from "next-intl";

import LanguageSwitcher from "@/components/LanguageSwitcher";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { useCanAccessAdminEntry } from "@/components/site/useCanAccessAdminEntry";
import { Button } from "@/components/ui/button";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RowButton } from "@/components/ui/row-button";
import { getAuthProfileHref } from "@/lib/auth/profile-links";
import { logout } from "@/lib/auth/logout";
import { cn } from "@/lib/utils";
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

export const ACCOUNT_MENU_ITEM_CLASS =
  "flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-hidden transition-colors hover:bg-[color:var(--aqt-overlay-3)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]";

export function AccountMenuSeparator() {
  return <div aria-hidden className="my-1.5 h-px bg-[color:var(--aqt-border)]" />;
}

type AccountMenuPanelProps = ComponentPropsWithoutRef<typeof PopoverContent> & {
  user: AuthProfile;
  /** Surface rows after account settings (the site's admin entry, the admin's notification settings). */
  actions?: ReactNode;
  /** Surface section placed above language (the admin community switcher). */
  children?: ReactNode;
};

/**
 * The account panel both surfaces open: identity, profile, settings, language
 * and sign-out. A Popover, not a DropdownMenu: `role="menu"` cannot hold the
 * segmented language control (a plain button inside a menu is unreachable).
 * Radix owns dismissal and focus restoration.
 */
export function AccountMenuPanel({
  user,
  actions,
  children,
  className,
  ...props
}: Readonly<AccountMenuPanelProps>) {
  const t = useTranslations();
  const nameId = useId();
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const signOut = useSignOut();
  const profileHref = getAuthProfileHref(user);

  return (
    <PopoverContent
      sideOffset={8}
      collisionPadding={12}
      aria-labelledby={nameId}
      className={cn(
        "max-h-[var(--radix-popover-content-available-height)] w-[340px] max-w-[calc(100vw-24px)] overflow-y-auto p-1.5",
        className
      )}
      {...props}
    >
      <div className="flex items-center gap-3 px-2.5 pb-3 pt-2">
        <PlayerAvatar
          user={{ name: user.username, avatar_url: user.avatarUrl ?? null }}
          size={36}
          className="border-2 border-[color:var(--aqt-border-2)]"
        />
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
              <PopoverClose asChild>
                <Button
                  variant="link"
                  size="inline"
                  className="text-[color:var(--aqt-teal)]"
                  onClick={() => openSettings("profile")}
                >
                  {t("common.linkPlayer")}
                </Button>
              </PopoverClose>
            )}
          </span>
        </span>
      </div>
      <AccountMenuSeparator />
      {profileHref ? (
        <PopoverClose asChild>
          <Link href={profileHref} className={ACCOUNT_MENU_ITEM_CLASS}>
            <User className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{t("nav.account.myProfile")}</span>
          </Link>
        </PopoverClose>
      ) : null}
      {actions}
      <PopoverClose asChild>
        <RowButton className={ACCOUNT_MENU_ITEM_CLASS} onClick={() => openSettings()}>
          <Settings className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{t("common.accountSettings")}</span>
        </RowButton>
      </PopoverClose>
      {children}
      <AccountMenuSeparator />
      <div className="flex items-center justify-between gap-3 px-2.5 py-1.5">
        <span className="text-[color:var(--aqt-fg-dim)]">{t("common.language")}</span>
        <LanguageSwitcher />
      </div>
      <AccountMenuSeparator />
      <RowButton className={cn(ACCOUNT_MENU_ITEM_CLASS, "text-[color:var(--aqt-fg-muted)]")} onClick={signOut}>
        <LogOut className="size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{t("common.logout")}</span>
      </RowButton>
    </PopoverContent>
  );
}

/**
 * The signed-in header control: a round avatar button opening the account
 * panel, plus the admin entry for those who have one. The notification inbox
 * is the bell's, not this menu's.
 */
const UserMenu = ({ user }: Readonly<{ user: AuthProfile }>) => {
  const t = useTranslations();
  const canAccessAdmin = useCanAccessAdminEntry();

  return (
    <Popover>
      {/* A real button, not `asChild` onto Avatar: Avatar.Root renders a
          <span>, which is neither focusable nor nameable. The name lives on
          the button, so it survives the avatar image replacing the fallback. */}
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          aria-label={t("common.openMenu")}
          className="relative shrink-0 overflow-hidden rounded-full border-2 hover:border-[color:var(--aqt-border-3)] data-[state=open]:border-[color:var(--aqt-border-3)]"
        >
          <PlayerAvatar user={{ name: user.username, avatar_url: user.avatarUrl ?? null }} size={32} className="border-0" />
        </Button>
      </PopoverTrigger>
      <AccountMenuPanel
        user={user}
        align="end"
        actions={
          canAccessAdmin ? (
            <PopoverClose asChild>
              <Link href="/admin" className={ACCOUNT_MENU_ITEM_CLASS}>
                <LayoutDashboard className="size-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{t("nav.items.admin.title")}</span>
              </Link>
            </PopoverClose>
          ) : null
        }
      />
    </Popover>
  );
};

export default UserMenu;
