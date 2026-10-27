"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import FavoriteStarButton from "@/components/FavoriteStarButton";
import { HandleLabel } from "@/components/HandleLabel";
import { Card } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useFavoritePlayers } from "@/hooks/useFavoritePlayers";
import { getPlayerSlug } from "@/lib/player";

/** One player per row, at least 44px tall: a touch target for the name and the star. */
const ROW_CLASS = "flex min-h-11 items-center gap-2 py-1 pl-4 pr-2";

export default function FavoritesSection() {
  const t = useTranslations("accountSettings");
  const { favoritePlayers, isLoading, isError, refetch } = useFavoritePlayers();

  if (isLoading) {
    return (
      <Card aria-hidden className="divide-y divide-border/60">
        {["a", "b", "c"].map((key) => (
          <div key={key} className={ROW_CLASS}>
            <Skeleton className="h-4 w-40" />
            <Skeleton className="ms-auto size-7" />
          </div>
        ))}
      </Card>
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
    <Card asChild className="divide-y divide-border/60">
      <ul>
        {favoritePlayers.map((player) => (
          <li key={player.id} className={ROW_CLASS}>
            <Link
              href={`/users/${getPlayerSlug(player.name)}`}
              title={player.name}
              className="min-w-0 flex-1 rounded-sm py-1.5 text-body text-[color:var(--aqt-fg)] underline-offset-4 hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <HandleLabel handle={player.name} className="block" />
            </Link>
            <FavoriteStarButton playerId={player.id} size="sm" />
          </li>
        ))}
      </ul>
    </Card>
  );
}
