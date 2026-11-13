"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";
import { GitCompare } from "lucide-react";

import SharePlayerCard, { type ShareCardData } from "@/app/(site)/users/components/header/SharePlayerCard";
import FavoriteStarButton from "@/components/FavoriteStarButton";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";

interface ProfileToolbarProps {
  /** Player data used to render the shareable card. */
  card: ShareCardData;
  /** Id of the player this toolbar belongs to, for the favorite star and the Compare subject. */
  playerId: number;
}

/**
 * Header toolbar for the player profile. Share opens the player-card dialog
 * (copy image / download PNG / copy link — design-book §6/§9); Compare opens
 * the players-compare page with this player preselected as the subject; the star toggles this player in the
 * visitor's favorites (account-scoped, `FavoriteStarButton`/`useFavoritePlayers`).
 */
const ProfileToolbar = ({ card, playerId }: ProfileToolbarProps) => {
  const t = useTranslations();

  return (
    <div className="flex items-center gap-2">
      <SharePlayerCard card={card} />
      <Button asChild variant="outline" size="sm">
        <HoverPrefetchLink
          href={{ pathname: "/users/compare", query: { user_id: playerId } }}
          aria-label={t("users.profile.toolbar.comparePlayers")}
        >
          <GitCompare aria-hidden />
          {t("users.profile.toolbar.compare")}
        </HoverPrefetchLink>
      </Button>
      <FavoriteStarButton playerId={playerId} size="sm" className="h-8 w-8" />
    </div>
  );
};

export default ProfileToolbar;
