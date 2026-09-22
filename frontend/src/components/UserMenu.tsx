"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import Image from "next/image";
import { Globe, LogOut, Settings, UserIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { useTranslations } from "next-intl";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { logout } from "@/lib/auth/logout";

type UserMenuProps = {
  username: string;
  avatarUrl?: string | null;
  profileHref: string;
};

const UserMenu = ({ username, avatarUrl, profileHref }: UserMenuProps) => {
  const router = useRouter();
  const clearAuth = useAuthProfileStore((s) => s.clear);
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const t = useTranslations();

  const handleLogout = () => {
    // Drop the cached profile first so the UI can't render a stale identity
    // while the POST is in flight; `logout` then clears the cookies server-side
    // and hard-navigates.
    clearAuth();
    void logout();
  };

  return (
    <DropdownMenu>
      {/* A real <button>, not `asChild` onto Avatar: Avatar.Root renders a
          <span>, so `asChild` handed the trigger's behaviour to a
          non-focusable element — the account menu was keyboard-dead and
          nameless (the sr-only initials lived in AvatarFallback, which unmounts
          as soon as the avatar image resolves). */}
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t("common.openMenu")}
          className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <Avatar className="h-8 w-8 aspect-square">
            <AvatarImage src={avatarUrl ?? undefined} alt="" />
            <AvatarFallback>
              <Image src="/discord-white.svg" alt="" width={16} height={16} aria-hidden />
            </AvatarFallback>
          </Avatar>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56 liquid-glass" align="end">
        <DropdownMenuLabel>{username}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup className="p-1 space-y-1">
          <DropdownMenuItem
            onClick={() => router.push(profileHref)}
            className="cursor-pointer rounded-md transition-colors focus:bg-accent focus:text-accent-foreground"
          >
            <UserIcon className="mr-2 h-4 w-4" aria-hidden />
            <span>{t("common.profile")}</span>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => openSettings("profile")}
            className="cursor-pointer rounded-md transition-colors focus:bg-accent focus:text-accent-foreground"
          >
            <Settings className="mr-2 h-4 w-4" aria-hidden />
            <span>{t("common.accountSettings")}</span>
          </DropdownMenuItem>
          {/* Language row: a real control, not a menu action — kept as a plain
              row (not DropdownMenuItem) so clicking a segment neither closes the
              menu nor fires a menu "select". The switcher manages its own state. */}
          <div className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5">
            <div className="flex items-center gap-2 text-sm">
              <Globe className="h-4 w-4" aria-hidden />
              <span>{t("common.language")}</span>
            </div>
            <LanguageSwitcher />
          </div>
          <DropdownMenuItem
            onClick={handleLogout}
            className="cursor-pointer rounded-md text-destructive transition-colors focus:bg-destructive/15 focus:text-destructive"
          >
            <LogOut className="mr-2 h-4 w-4" aria-hidden />
            <span>{t("common.logout")}</span>
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default UserMenu;
