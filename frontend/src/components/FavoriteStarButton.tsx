"use client";

import type { MouseEvent } from "react";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useFavoritePlayers } from "@/hooks/useFavoritePlayers";

interface FavoriteStarButtonProps {
  playerId: number;
  size?: "sm" | "md";
  className?: string;
}

const BUTTON_SIZE_CLASS: Record<NonNullable<FavoriteStarButtonProps["size"]>, string> = {
  sm: "h-7 w-7",
  md: "h-9 w-9",
};

const ICON_SIZE: Record<NonNullable<FavoriteStarButtonProps["size"]>, number> = {
  sm: 14,
  md: 18,
};

/**
 * Star toggle reused across the profile toolbar, search results, and the
 * account-settings favorites list — one component, one shared react-query
 * cache via `useFavoritePlayers`. Nested inside clickable rows/`CommandItem`s
 * in two of those three places, so the click must never bubble: an anonymous
 * visitor gets the login modal instead of a doomed API call, and an
 * authenticated click always stops propagation before toggling.
 */
export default function FavoriteStarButton({ playerId, size = "md", className }: Readonly<FavoriteStarButtonProps>) {
  const t = useTranslations();
  const { user } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const { isFavorited, toggle } = useFavoritePlayers();
  const favorited = isFavorited(playerId);

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!user) {
      openAuthModal(getCurrentPathForAuthRedirect(window.location));
      return;
    }
    toggle(playerId);
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={handleClick}
      aria-label={favorited ? t("common.favorite.remove") : t("common.favorite.add")}
      className={cn(BUTTON_SIZE_CLASS[size], className)}
    >
      <Star
        size={ICON_SIZE[size]}
        aria-hidden
        className={
          favorited
            ? "fill-[color:var(--aqt-amber)] text-[color:var(--aqt-amber)]"
            : "text-[color:var(--aqt-fg-muted)]"
        }
      />
    </Button>
  );
}
