"use client";

import React from "react";
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

type UserMenuProps = {
  username: string;
  avatarUrl?: string | null;
  profileHref: string;
  logoutHref?: string;
};

const UserMenu = ({ username, avatarUrl, profileHref, logoutHref = "/auth/logout" }: UserMenuProps) => {
  const initials = username?.slice(0, 2).toUpperCase();
  const router = useRouter();
  const clearAuth = useAuthProfileStore((s) => s.clear);
  const openSettings = useAccountSettingsModalStore((s) => s.open);
  const t = useTranslations();

  const handleLogout = () => {
    // Clear auth store before redirecting
    clearAuth();
    // Use window.location for full page navigation to ensure cookies are properly handled
    window.location.href = logoutHref;
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Avatar className="h-8 w-8 aspect-square cursor-pointer">
          <AvatarImage src={avatarUrl ?? undefined} />
          <AvatarFallback>
            <Image src="/discord-white.svg" alt="Discord" width={16} height={16} />
            <span className="sr-only">{initials}</span>
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent 
        className="w-56 liquid-glass"
        align="end"
        style={
          {
            "--lg-a": "139 92 246",
            "--lg-b": "59 130 246",
            "--lg-c": "236 72 153"
          } as React.CSSProperties
        }
      >
        <DropdownMenuLabel>{username}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup className="p-1 space-y-1">
          <DropdownMenuItem
            onClick={() => router.push(profileHref)}
            className="cursor-pointer focus:bg-white/10 focus:text-white transition-colors rounded-md"
          >
            <UserIcon className="mr-2 h-4 w-4" />
            <span>{t("common.profile")}</span>
          </DropdownMenuItem>
          <DropdownMenuItem 
            onClick={() => openSettings("profile")}
            className="cursor-pointer focus:bg-white/10 focus:text-white transition-colors rounded-md"
          >
            <Settings className="mr-2 h-4 w-4" />
            <span>{t("common.accountSettings")}</span>
          </DropdownMenuItem>
          {/* Language row: a real control, not a menu action — kept as a plain
              row (not DropdownMenuItem) so clicking a segment neither closes the
              menu nor fires a menu "select". The switcher manages its own state. */}
          <div className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5">
            <div className="flex items-center gap-2 text-sm">
              <Globe className="h-4 w-4" />
              <span>{t("common.language")}</span>
            </div>
            <LanguageSwitcher />
          </div>
          <DropdownMenuItem 
            onClick={handleLogout}
            className="cursor-pointer focus:bg-red-500/20 focus:text-red-400 text-red-500 transition-colors rounded-md"
          >
            <LogOut className="mr-2 h-4 w-4" />
            <span>{t("common.logout")}</span>
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default UserMenu;
