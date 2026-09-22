"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import meService from "@/services/me.service";
import { useAuthProfile } from "@/hooks/useAuthProfile";

// Single shared cache key: the star button, the profile toolbar, and the
// account-settings list all read/write the same list, so favoriting from any
// one of them must invalidate the other two instead of leaving them stale.
const FAVORITE_PLAYERS_QUERY_KEY = ["me", "favorite-players"] as const;

export function useFavoritePlayers() {
  const { user } = useAuthProfile();
  const query = useQuery({
    queryKey: FAVORITE_PLAYERS_QUERY_KEY,
    queryFn: () => meService.getFavoritePlayers(),
    enabled: !!user,
  });
  const queryClient = useQueryClient();
  const favoriteIds = useMemo(() => new Set((query.data ?? []).map((p) => p.id)), [query.data]);

  const add = useMutation({
    mutationFn: (id: number) => meService.addFavoritePlayer(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: FAVORITE_PLAYERS_QUERY_KEY }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => meService.removeFavoritePlayer(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: FAVORITE_PLAYERS_QUERY_KEY }),
  });

  return {
    favoritePlayers: query.data ?? [],
    favoriteIds,
    isFavorited: (id: number) => favoriteIds.has(id),
    toggle: (id: number) => (favoriteIds.has(id) ? remove.mutate(id) : add.mutate(id)),
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}
