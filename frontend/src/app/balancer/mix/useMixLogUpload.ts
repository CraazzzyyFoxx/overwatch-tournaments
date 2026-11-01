"use client";

import { useQueryClient } from "@tanstack/react-query";

import { isMixHost } from "@/app/balancer/mix/pickup-lineup";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { usePermissions } from "@/hooks/usePermissions";
import { customGameKeys, type CustomGame } from "@/services/custom-game.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

/**
 * What a viewer who may file match logs under a mix is handed: the mix, what to run once a log is accepted, and
 * whether the mix's game fetches matches by id (`capabilities.match_fetch`), so a round may be filed by that id too.
 */
export type MixLogUpload = { customGameId: number; onUploaded: () => void; matchFetch: boolean };

/**
 * `null` unless the viewer may file a match log under this mix: the host, a co-host or a superuser (a closed mix
 * still takes logs, so unlike `canWriteMix` the status is not checked), or anyone holding `log.create` in the mix's
 * workspace -- the server's rule for `rpc.stats.logs.upload`. `onUploaded` refetches the mix's history: the parser's
 * own completion arrives as `workspace.logs` (which also stales the mix keys), but the chip should appear at once.
 */
export function useMixLogUpload(game: CustomGame | undefined): MixLogUpload | null {
  const queryClient = useQueryClient();
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  // The same read the mix screens already make for the game: one cache entry.
  const metadata = useDisciplineMetadata(game?.workspace_id ?? "all", game?.discipline ?? null);
  const { isSuperuser, canAccessPermission } = usePermissions();
  if (game == null) return null;
  if (!isMixHost(game, currentUserId, isSuperuser) && !canAccessPermission("log.create", game.workspace_id)) {
    return null;
  }
  return {
    customGameId: game.id,
    matchFetch: metadata.data?.discipline.capabilities.match_fetch === true,
    onUploaded: () =>
      void queryClient.invalidateQueries({ queryKey: customGameKeys.matches(game.workspace_id, game.id) })
  };
}
