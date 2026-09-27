"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import FavoriteStarButton from "@/components/FavoriteStarButton";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useFavoritePlayers } from "@/hooks/useFavoritePlayers";
import { getPlayerSlug } from "@/lib/player";

export default function FavoritesSection() {
  const t = useTranslations("accountSettings");
  const { favoritePlayers, isLoading, isError, refetch } = useFavoritePlayers();

  if (isLoading) {
    return (
      <div className="space-y-1.5" aria-hidden>
        {["a", "b", "c"].map((key) => (
          <Skeleton key={key} className="h-11 rounded-lg" />
        ))}
      </div>
    );
  }

  // A failed load must not read as "you have no favorites".
  if (isError) {
    return <PageStateCard state="error" onAction={() => void refetch()} />;
  }

  if (favoritePlayers.length === 0) {
    return (
      <PageStateCard state="empty" title={t("favorites.empty")} description={t("favorites.emptyHint")} />
    );
  }

  return (
    <ul className="space-y-1.5">
      {favoritePlayers.map((player) => (
        <li
          key={player.id}
          className="flex items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] py-1 pl-3 pr-1"
        >
          <Link
            href={`/users/${getPlayerSlug(player.name)}`}
            title={player.name}
            className="flex-1 truncate rounded-sm py-1.5 text-sm text-[color:var(--aqt-fg)] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {player.name}
          </Link>
          <FavoriteStarButton playerId={player.id} size="sm" />
        </li>
      ))}
    </ul>
  );
}
